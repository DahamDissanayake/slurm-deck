"""The forced-command GPU-host helper, run with --root <tmp> --dry-run so
privileged commands are printed instead of run. Renames under the root happen."""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

if sys.platform != "linux":
    pytest.skip("the GPU-host helper runs on Linux", allow_module_level=True)

from sdcore.names import RESERVED, USERNAME_RE  # noqa: E402

HELPER = Path(__file__).resolve().parents[2] / "gpuhost" / "sd-gpu-helper"


WEB = ["webusers", "gpuusers"]


def run_helper(cmd: str, root: Path | None = None,
               accounts: dict | None = None) -> subprocess.CompletedProcess:
    """accounts: the host's accounts as {name: {"uid": n, "groups": [...]}}; the
    helper reads them instead of the test machine's (none by default)."""
    args = [sys.executable, str(HELPER), "--dry-run"]
    if root is not None:
        args += ["--root", str(root)]
        fake = root / "accounts.json"
        fake.write_text(json.dumps(accounts or {}))
        args += ["--fake-accounts", str(fake)]
    env = {**os.environ, "SSH_ORIGINAL_COMMAND": cmd}
    return subprocess.run(args, capture_output=True, text=True, env=env)


def _json(r: subprocess.CompletedProcess) -> dict:
    return json.loads(r.stdout)


@pytest.mark.parametrize("cmd", ["purge ..", "purge .", "purge a/b", "archive root",
                                 "create-account x 0", "create-account x abc",
                                 "create-account x 70000", "rm -rf /", "purge amasha; id",
                                 "purge amasha extra", "ping now", "", "folder-info Root",
                                 "delete-account slurmadmin", "create-folders sdweb 20001",
                                 "service-status slurmd"])
def test_refuses_bad_commands(tmp_path, cmd):
    r = run_helper(cmd, tmp_path)
    assert r.returncode == 2, (cmd, r.stdout, r.stderr)
    assert _json(r)["ok"] is False


def test_ping():
    r = run_helper("ping")
    assert r.returncode == 0 and _json(r) == {"ok": True, "pong": True}


def test_service_status_reports_only_the_allowed_units():
    r = run_helper("service-status")
    assert r.returncode == 0 and set(_json(r)["units"]) == {"slurmd", "munge", "sd-stats-writer"}


def test_uid_of_another_account_refused(tmp_path):
    taken = {"hassan": {"uid": 30000, "groups": WEB}}
    assert run_helper("create-account other-name 30000", tmp_path, taken).returncode == 2


# --- only web accounts (SLURM-49 finding 4) -------------------------------------------------

SYSADMIN = {"dahamadmin": {"uid": 1002, "groups": ["gpuadmins", "webusers", "gpuusers"]}}
SHELL_USER = {"tuser": {"uid": 2000, "groups": ["gpuusers", "docker"]}}
SUDOER = {"ops": {"uid": 1003, "groups": ["sudo", "webusers"]}}
WEB_USER = {"amasha": {"uid": 23456, "groups": WEB}}


@pytest.mark.parametrize("who", [SYSADMIN, SHELL_USER, SUDOER])
@pytest.mark.parametrize("op", ["delete-account", "purge", "archive"])
def test_mutating_commands_refuse_accounts_that_are_not_web_accounts(tmp_path, who, op):
    name = next(iter(who))
    for sub in ("users", "jobs"):
        (tmp_path / sub / name).mkdir(parents=True)
    r = run_helper(f"{op} {name}", tmp_path, who)
    assert r.returncode == 2, (op, name, r.stdout, r.stderr)
    assert "isn't a web account" in _json(r)["error"]
    assert "+ " not in r.stderr                         # nothing was run
    assert (tmp_path / "users" / name).is_dir()          # nothing was moved


@pytest.mark.parametrize("op", ["delete-account", "purge", "archive"])
def test_mutating_commands_accept_a_web_account(tmp_path, op):
    for sub in ("users", "jobs"):
        (tmp_path / sub / "amasha").mkdir(parents=True)
    r = run_helper(f"{op} amasha", tmp_path, WEB_USER)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("who", [SYSADMIN, SHELL_USER])
def test_create_account_never_takes_over_an_existing_account(tmp_path, who):
    name, acct = next(iter(who.items()))
    r = run_helper(f"create-account {name} {acct['uid']}", tmp_path, who)
    assert r.returncode == 2 and "isn't a web account" in _json(r)["error"]
    assert "passwd -l" not in r.stderr and "chown" not in r.stderr


def test_create_account_rerun_for_an_existing_web_account(tmp_path):
    r = run_helper("create-account amasha 23456", tmp_path, WEB_USER)
    assert r.returncode == 0, r.stderr
    assert "groupadd" not in r.stderr and "+ passwd -l amasha" in r.stderr


def test_create_folders_refuses_an_existing_non_web_account(tmp_path):
    r = run_helper("create-folders tuser 2000", tmp_path, SHELL_USER)
    assert r.returncode == 2 and "mkdir" not in r.stderr


def test_purge_after_the_account_is_gone_refuses_folders_another_account_owns(tmp_path):
    """No account named amasha any more, but users/amasha is owned by a UID that
    belongs to someone else: removing it would remove their files."""
    for sub in ("users", "jobs"):
        (tmp_path / sub / "amasha").mkdir(parents=True)
    owner = {"someone": {"uid": os.getuid(), "groups": ["gpuusers"]}}
    for op in ("purge", "archive"):
        r = run_helper(f"{op} amasha", tmp_path, owner)
        assert r.returncode == 2 and "belongs to someone" in _json(r)["error"]
    assert (tmp_path / "users" / "amasha").is_dir()


def test_create_account_commands(tmp_path):
    r = run_helper("create-account amasha 23456", tmp_path)
    assert r.returncode == 0, r.stderr
    assert "+ groupadd -g 23456 amasha" in r.stderr
    assert ("+ useradd -u 23456 -g 23456 -m -d /home/amasha -s /usr/sbin/nologin "
            "-G webusers,gpuusers amasha") in r.stderr
    assert "+ passwd -l amasha" in r.stderr and "+ chown -R 23456:23456 /home/amasha" in r.stderr


def test_create_folders_commands(tmp_path):
    r = run_helper("create-folders amasha 23456", tmp_path)
    assert r.returncode == 0, r.stderr
    for sub in ("users", "jobs"):
        path = tmp_path / sub / "amasha"
        assert f"+ chown 23456:gpuadmins {path}" in r.stderr
        assert f"+ chmod 2770 {path}" in r.stderr
        assert f"+ setfacl -R -m g:gpuadmins:rwX -m d:g:gpuadmins:rwx {path}" in r.stderr


def test_purge_refuses_symlinked_user_dir(tmp_path):
    (tmp_path / "users").mkdir()
    (tmp_path / "jobs" / "amasha").mkdir(parents=True)
    (tmp_path / "users" / "amasha").symlink_to("/etc")
    r = run_helper("purge amasha", tmp_path)
    assert r.returncode == 2
    assert "rm " not in r.stderr          # nothing removed, not even jobs/amasha


def test_purge_removes_both_folders(tmp_path):
    for sub in ("users", "jobs"):
        (tmp_path / sub / "amasha").mkdir(parents=True)
    r = run_helper("purge amasha", tmp_path)
    assert r.returncode == 0, r.stderr
    assert f"+ rm -rf --one-file-system {tmp_path / 'users' / 'amasha'}" in r.stderr
    assert f"+ rm -rf --one-file-system {tmp_path / 'jobs' / 'amasha'}" in r.stderr


def test_archive_never_deletes_previous_archive(tmp_path):
    users = tmp_path / "users"
    (users / "amasha").mkdir(parents=True)
    (users / "amasha" / "new.txt").write_text("new")
    (users / "amasha.offboarded").mkdir()
    (users / "amasha.offboarded" / "old.txt").write_text("old")
    r = run_helper("archive amasha", tmp_path)
    assert r.returncode == 0, r.stderr
    assert (users / "amasha.offboarded" / "new.txt").read_text() == "new"
    older = [p for p in users.iterdir() if p.name.startswith("amasha.offboarded.")]
    assert len(older) == 1 and (older[0] / "old.txt").read_text() == "old"
    assert not (users / "amasha").exists()


def test_archive_refuses_a_symlink(tmp_path):
    (tmp_path / "users").mkdir()
    (tmp_path / "users" / "amasha").symlink_to(tmp_path)
    assert run_helper("archive amasha", tmp_path).returncode == 2


def test_folder_info_reports_owner_and_size(tmp_path):
    d = tmp_path / "users" / "amasha"
    d.mkdir(parents=True)
    (d / "f.bin").write_bytes(b"x" * 5000)
    info = _json(run_helper("folder-info amasha", tmp_path))
    assert info["ok"] and info["exists"] is True
    assert info["owner_uid"] == os.getuid() and info["bytes"] >= 5000 and info["mtime"]
    assert _json(run_helper("folder-info nobody-here", tmp_path)) == {"ok": True,
                                                                     "exists": False}


def test_delete_account_commands(tmp_path):
    r = run_helper("delete-account amasha", tmp_path)
    assert r.returncode == 0, r.stderr
    assert "+ pkill -KILL -u amasha" in r.stderr and "+ userdel amasha" in r.stderr
    assert "+ groupdel amasha" in r.stderr


def test_username_rule_matches_sdcore():
    loader = importlib.machinery.SourceFileLoader("sd_gpu_helper", str(HELPER))
    spec = importlib.util.spec_from_loader("sd_gpu_helper", loader)
    assert spec is not None
    helper = importlib.util.module_from_spec(spec)
    loader.exec_module(helper)
    assert helper.USERNAME_RE.pattern == USERNAME_RE.pattern
    assert helper.RESERVED == RESERVED


def test_child_command_output_never_reaches_stdout(tmp_path):
    """passwd prints "passwd: password changed." on stdout; deck-agent parses the
    helper's stdout as one JSON object, so child output must go to stderr."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("groupadd", "useradd", "passwd", "chown"):
        stub = bin_dir / name
        stub.write_text(f"#!/bin/sh\necho '{name}: password changed.'\n")
        stub.chmod(0o755)
    fake = tmp_path / "accounts.json"
    fake.write_text("{}")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "SSH_ORIGINAL_COMMAND": "create-account amasha 23456"}
    r = subprocess.run([sys.executable, str(HELPER), "--root", str(tmp_path),
                        "--fake-accounts", str(fake)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert json.loads(r.stdout) == {"ok": True}
    assert "passwd: password changed." in r.stderr


def test_purge_removes_the_envs_the_account_built(tmp_path):
    env = tmp_path / "users" / "amasha" / "my-envs" / "acceptenv" / "bin"
    env.mkdir(parents=True)
    (tmp_path / "jobs" / "amasha").mkdir(parents=True)
    r = run_helper("purge amasha", tmp_path, WEB_USER)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"rm -rf --one-file-system {tmp_path / 'users' / 'amasha'}" in r.stderr
