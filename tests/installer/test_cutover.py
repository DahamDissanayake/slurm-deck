"""The cutover tools against fixture snapshots and fake system commands (Linux, bash)."""

import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

CUTOVER = Path(__file__).resolve().parents[2] / "deploy" / "cutover"

pytestmark = pytest.mark.skipif(sys.platform != "linux" or not shutil.which("bash"),
                                reason="the cutover tools run on Linux")

PASSWD = """root:x:0:0:root:/root:/bin/bash
slurm:x:990:990::/var/lib/slurm:/usr/sbin/nologin
sdweb:x:991:991::/nonexistent:/usr/sbin/nologin
sysadmin:x:1001:1001::/home/sysadmin:/bin/bash
gpudev:x:1100:1100::/home/gpudev:/bin/bash
tuiuser:x:1101:1101::/home/tuiuser:/usr/sbin/nologin
both:x:1102:1102::/home/both:/bin/bash
shelly:x:1103:1103::/home/shelly:/bin/bash
adminuser:x:1104:1104::/home/adminuser:/bin/bash
webacct:x:20001:20001::/nonexistent:/usr/sbin/nologin
"""
GROUP = """gpuusers:x:2000:gpudev,tuiuser,both,sysadmin
gpuadmins:x:2001:adminuser
shellusers:x:2002:both,shelly
webusers:x:2003:webacct
"""
FAKES = ("userdel", "groupdel", "pkill", "sacctmgr", "usermod", "groupadd", "systemctl", "sshd",
         "docker")


@pytest.fixture
def node(tmp_path):
    """An /etc, a snapshot of it, and fakes that log `name args` to calls.log."""
    etc, snap, bindir = tmp_path / "etc", tmp_path / "snap", tmp_path / "bin"
    for d in (etc / "ssh/sshd_config.d", snap / "login/sshd_config.d", bindir):
        d.mkdir(parents=True)
    for f, text in (("passwd", PASSWD), ("group", GROUP), ("shadow", "x\n"), ("gshadow", "x\n")):
        (etc / f).write_text(text)
        (snap / "login" / f).write_text(text)
    for base in (snap / "login", etc / "ssh"):
        conf = base / "sshd_config.d/10-forcecommand.conf"
        conf.write_text("ForceCommand /opt/slurm-deck/gw\n")
    for name in FAKES:
        f = bindir / name
        f.write_text(f'#!/bin/bash\necho "{name} $*" >> "{tmp_path}/calls.log"\n')
        f.chmod(0o755)

    def run(script, *args, **env):
        python_dir = str(Path(sys.executable).parent)
        full = {"PATH": f"{bindir}:{python_dir}:/usr/bin:/bin", "ETC_DIR": str(etc),
                "NODE": "login",
                "SYSADMINS": "sysadmin", "SYSADMIN_GROUP": "gpuadmins", "HOME": str(tmp_path),
                "CUTOVER_ROOT": str(tmp_path / "root"), "SNAPSHOT_BASE": str(tmp_path / "snaps"),
                **env}
        interpreter = "python3" if script.endswith(".py") else "bash"
        return subprocess.run([interpreter, str(CUTOVER / script), *args], capture_output=True,
                              text=True, env=full)
    run.etc, run.snap, run.tmp = etc, snap, tmp_path
    log = tmp_path / "calls.log"
    run.calls = lambda: log.read_text() if log.exists() else ""
    return run


def _classify(node, **env):
    r = node("classify.py", str(node.snap), **env)
    assert r.returncode == 0, r.stderr
    return json.loads((node.snap / "cutover-plan.json").read_text())


def test_gpuusers_with_a_shell_who_are_not_shell_users_are_removed(node):
    plan = _classify(node)
    assert {"gpudev", "tuiuser", "adminuser"} <= set(plan["remove"])   # gpuadmins count too


def test_dual_membership_is_flagged(node):
    plan = _classify(node)
    assert [f["user"] for f in plan["flagged"]] == ["both"] and "both" not in plan["remove"]
    assert plan["shell"] == ["shelly"]


def test_sysadmins_service_and_web_accounts_are_never_removed(node):
    plan = _classify(node)
    assert plan["sysadmin"] == ["sysadmin"] and "sysadmin" not in plan["remove"]
    assert {"root", "slurm", "sdweb", "webacct"} <= set(plan["service"])
    assert plan["uids"]["gpudev"] == 1100


def test_naming_a_gpu_user_as_a_shell_user_flags_them_instead_of_removing_them(node):
    plan = _classify(node, SHELL_USERS="gpudev")
    assert "gpudev" not in plan["remove"] and "gpudev" in [f["user"] for f in plan["flagged"]]


def _plan(node):
    plan = _classify(node)
    path = node.tmp / "plan.json"
    path.write_text(json.dumps(plan))
    return path


def test_cutover_check_changes_nothing(node):
    r = node("cutover.sh", "--check", str(_plan(node)))
    assert r.returncode == 0, r.stderr
    assert "gpudev" in r.stdout and "1100" in r.stdout          # who would go, with UIDs
    assert node.calls() == ""                                  # no command ran


def test_cutover_apply_removes_only_the_planned_accounts_and_keeps_their_data(node):
    r = node("cutover.sh", "--apply", str(_plan(node)))
    assert r.returncode == 0, r.stderr
    calls = node.calls()
    for gone in ("gpudev", "tuiuser", "adminuser"):
        assert f"userdel {gone}\n" in calls
    for kept in ("sysadmin", "both", "shelly", "slurm", "webacct"):
        assert f"userdel {kept}" not in calls
    assert "userdel -r" not in calls                          # homes and /shared data stay
    assert calls.index("sshd -t") < calls.index("userdel gpudev")   # logins are closed first
    conf = node.etc / "ssh/sshd_config.d/10-slurm-deck-cutover.conf"
    assert "AllowGroups shellusers gpuadmins" in conf.read_text()


def test_rollback_refuses_when_a_web_account_holds_a_removed_uid(node):
    plan = _plan(node)
    node.snap.joinpath("cutover-plan.json").write_text(plan.read_text())
    now = PASSWD.replace("tuiuser:x:1101:1101::/home/tuiuser:/usr/sbin/nologin\n", "")
    (node.etc / "passwd").write_text(now.replace("webacct:x:20001", "webacct:x:1101"))
    r = node("rollback.sh", "--apply", str(node.snap))
    assert r.returncode == 3
    assert "tuiuser" in r.stdout and "1101" in r.stdout and "webacct" in r.stdout
    assert "usermod" not in node.calls()


def test_rollback_restores_the_removed_accounts_and_the_forcecommand_drop_in(node):
    node.snap.joinpath("cutover-plan.json").write_text(_plan(node).read_text())
    removed = ("gpudev:", "tuiuser:", "adminuser:")
    gone = [ln for ln in PASSWD.splitlines() if not ln.startswith(removed)]
    (node.etc / "passwd").write_text("\n".join(gone) + "\n")
    (node.etc / "ssh/sshd_config.d/10-forcecommand.conf").unlink()
    assert node("rollback.sh", "--check", str(node.snap)).returncode == 0
    assert "gpudev" not in (node.etc / "passwd").read_text()            # --check changed nothing
    r = node("rollback.sh", "--apply", str(node.snap))
    assert r.returncode == 0, r.stderr
    restored = (node.etc / "passwd").read_text()
    assert "gpudev:x:1100" in restored and "tuiuser:x:1101" in restored
    assert (node.etc / "ssh/sshd_config.d/10-forcecommand.conf").exists()
    assert "sacctmgr" not in node.calls()   # no dump in this snapshot, nothing to load


def test_snapshot_copies_the_account_files_privately(node):
    r = node("snapshot.sh", str(node.tmp / "out"))
    assert r.returncode == 0, r.stderr
    copy = node.tmp / "out/login/passwd"
    assert copy.read_text() == PASSWD and stat.S_IMODE(copy.stat().st_mode) == 0o600
    assert (node.tmp / "out/login/sshd_config.d/10-forcecommand.conf").exists()


def test_retire_removes_the_tui_but_check_only_lists_it(node):
    root = node.tmp / "root"
    for p in ("opt/slurm-deck/app.py", "usr/local/bin/slurm-deck",
              "etc/sudoers.d/slurm-deck-admin"):
        (root / p).parent.mkdir(parents=True, exist_ok=True)
        (root / p).write_text("x")
    r = node("retire-tui.sh", "--check")
    assert r.returncode == 0 and "opt/slurm-deck" in r.stdout and (root / "opt/slurm-deck").exists()
    assert node("retire-tui.sh", "--apply").returncode == 0
    assert not (root / "opt/slurm-deck").exists()
    assert not (root / "usr/local/bin/slurm-deck").exists()
    assert "systemctl disable --now slurm-deck-audit" in node.calls()


def test_announce_lists_only_the_people_who_will_lose_their_account(node):
    import sqlite3
    db = node.tmp / "users.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE users (username TEXT, email TEXT, status TEXT)")
    con.executemany("INSERT INTO users VALUES (?, ?, ?)", [
        ("gpudev", "dev@x.org", "active"), ("shelly", "shelly@x.org", "active"),
        ("tuiuser", "old@x.org", "offboarded")])
    con.commit()
    r = node("cutover.sh", "--announce", "--check", str(_plan(node)), CUTOVER_DATE="2026-11-09",
             LEGACY_USERS_DB=str(db))
    assert r.returncode == 0, r.stderr
    assert "2026-11-09" in r.stdout and "would set the maintenance banner" in r.stdout
    assert (node.tmp / "announce-recipients.txt").read_text() == "gpudev <dev@x.org>\n"
    assert "docker" not in node.calls()
