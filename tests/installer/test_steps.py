"""The installer's steps against a fake Target that records commands: nothing
runs. The installer is stdlib-only and runs on the login node (Linux)."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from deploy.installer import steps  # noqa: E402
from deploy.installer.state import State  # noqa: E402

ANSWERS = {
    "public_hostname": "deck.example.org", "gpu_host": "10.0.0.2", "login_addr": "10.0.0.1",
    "lan_addr": "192.168.1.5", "compute_node": "gpu1", "admin_email": "a@example.org",
    "admin_name": "Ada Admin", "admin_username": "ada", "admin_unix_user": "slurmadmin",
    "gpu_admin_user": "root",
}
REPLIES = {r"^id -u sdweb": "990\n", r"^id -g sdweb": "990\n", r"^id -u sdworker": "991\n",
           r"^id -g sdworker": "991\n", r"cat .*\.pub": "ssh-ed25519 AAAAkey deck-agent\n",
           r" ping$": '{"ok": true}\n'}


class FakeTarget(steps.Target):
    def __init__(self, name):
        self.name, self.cmds, self.fail_on, self.codes = name, [], None, {}
        self.inputs = []

    def run(self, cmd, input_text=None, check=True):
        self.cmds.append(cmd)
        self.inputs.append(input_text or "")
        if self.fail_on and re.search(self.fail_on, cmd):
            raise steps.InstallError(f"{self.name}: {cmd} failed")
        out = next((v for k, v in REPLIES.items() if re.search(k, cmd)), "")
        rc = next((c for k, c in self.codes.items() if re.search(k, cmd)),
                  1 if cmd.startswith("getent passwd") else 0)   # every UID is free
        return subprocess.CompletedProcess(cmd, rc, out, "")


@pytest.fixture
def ctx(tmp_path):
    login, gpu = FakeTarget("login"), FakeTarget("gpu")
    state = State(tmp_path / "install-state.json")
    state.data["answers"] = dict(ANSWERS)
    return steps.Ctx(login=login, gpu_target=lambda answers: gpu, state=state, repo=REPO,
                     accept_small=True, log=lambda msg: None)


def test_session_hostname_defaults_and_reaches_every_env_file(ctx):
    steps.run_all(ctx)
    assert ctx.state.data["answers"]["session_hostname"] == "sessions.deck.example.org"
    written = " ".join(ctx.login.inputs) + " ".join(ctx.gpu.inputs)
    assert "SD_SESSION_HOSTNAME=sessions.deck.example.org" in written   # web.env, compose env
    assert "SESSION_HOSTNAME=sessions.deck.example.org" in written      # gpu-helper.env


def test_session_hostname_must_differ_from_the_public_one(ctx):
    ctx.state.data["answers"]["session_hostname"] = "deck.example.org"
    with pytest.raises(steps.InstallError, match="session hostname"):
        steps.site_values(ctx)


def test_resume_skips_done_steps(ctx):
    ctx.gpu.fail_on = "sudoers"
    with pytest.raises(steps.InstallError):
        steps.run_all(ctx)
    assert ctx.state.data["done"] == ["preflight", "site_values", "accounts_login"]
    first = [c for c in ctx.login.cmds if "useradd" in c]
    ctx.gpu.fail_on = None
    steps.run_all(ctx)
    assert [c for c in ctx.login.cmds if "useradd" in c] == first   # no account was redone
    assert "summary" in ctx.state.data["done"]


def test_check_runs_nothing_and_saves_nothing(ctx, tmp_path):
    login, gpu = ctx.login, ctx.gpu_target({})
    ctx.check, ctx.login = True, steps.Dry(login, ctx.planned)   # what --check wires up
    steps.run_all(ctx)
    assert login.cmds == [] and gpu.cmds == []
    assert any("useradd" in c for c in ctx.planned)
    assert not (tmp_path / "install-state.json").exists()


def test_templates_never_contain_an_empty_required_value():
    values = {**ANSWERS, "nfs_root": "/shared", "partition": "gpu", "cluster_name": "Deck",
              "timezone": "UTC", "mail_provider": "none", "mail_from": "", "web_uid": 1,
              "slurm_account": "default", "slurm_qos": "normal",
              "web_gid": 1, "worker_uid": 2, "worker_gid": 2, "db_password": "x",
              "agent_db_password": "y", "compose_dir": "/srv/deploy",
              "session_hostname": "sessions.deck.example.org"}
    for tmpl in sorted(steps.TEMPLATES.glob("*.tmpl")):
        assert not re.search(r"=$", steps.render(tmpl.name, {**values, "mail_from": "x"}), re.M)
        with pytest.raises(steps.InstallError):
            steps.render(tmpl.name, {**values, **{k: "" for k in values if k != "mail_from"}})


MODE = re.compile(r"chown (\S+) (\S+)\.new && chmod (\d+) \2\.new")


def test_secret_files_get_the_documented_modes(ctx):
    steps.run_all(ctx)
    modes = {m[2]: (m[1], m[3]) for c in ctx.login.cmds for m in MODE.finditer(c)}
    d = "/etc/slurm-deck-web"
    assert modes[f"{d}/agent.env"] == ("root:root", "0600")
    assert modes[f"{d}/grant.key"] == ("root:root", "0600")
    assert modes[f"{d}/secrets.env"] == ("slurmadmin:sdweb", "0640")
    assert modes[f"{d}/web.env"] == ("slurmadmin:sdweb", "0640")
    assert f"chmod 0600 {d}/sdprov_ed25519" in " ".join(ctx.login.cmds)   # the GPU-host key


def test_network_waits_for_a_hand_made_forward_and_installs_the_scripts_on_the_gpu_host(ctx):
    assert steps.network(ctx) is True
    assert any("/usr/local/lib/slurm-deck/sd-web-forward.sh --apply" in c for c in ctx.gpu.cmds)
    assert any("systemctl enable --now sd-mdns-alias sd-mdns-sessions" in c
               for c in ctx.gpu.cmds)
    ctx.gpu.codes = {"sd-web-forward.sh --apply": 2}   # the 2225 forward wasn't found
    assert steps.network(ctx) is False


def test_backups_install_a_timer_for_the_admin_account_in_the_cluster_timezone(ctx):
    ctx.state.data["answers"]["timezone"] = "Asia/Colombo"
    steps.backups(ctx)
    written = " ".join(ctx.login.inputs)
    assert "OnCalendar=*-*-* 02:30:00 Asia/Colombo" in written and "@CLUSTER_TZ@" not in written
    assert f"ExecStart={REPO}/deploy/cluster/sd-backup.sh" in written and "@REPO@" not in written
    assert "systemctl daemon-reload && systemctl enable --now sd-backup.timer" in ctx.login.cmds
