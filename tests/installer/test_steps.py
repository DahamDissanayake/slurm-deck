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
    "gpu_admin_user": "root", "nfs_root": "/shared",
}
REPLIES = {r"^id -u sdweb": "990\n", r"^id -g sdweb": "990\n", r"^id -u sdworker": "991\n",
           r"^id -g sdworker": "991\n", r"cat .*\.pub": "ssh-ed25519 AAAAkey deck-agent\n",
           r" ping$": '{"ok": true}\n', r"^getent group sd-agent \| cut": "985\n"}


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
                     accept_small=True, apply_hardening=True, log=lambda msg: None)


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
    first = [c for c in ctx.gpu.cmds if "useradd" in c]
    ctx.gpu.fail_on, ctx.login.cmds = None, []
    steps.run_all(ctx)
    assert [c for c in ctx.gpu.cmds if "useradd" in c] == first * 2   # only the failed step reran
    assert not any("nproc" in c for c in ctx.login.cmds)   # preflight stays done
    assert "summary" in ctx.state.data["done"]


def test_accounts_login_and_secrets_rerun_even_when_done(ctx):
    # Both are idempotent, so a fixed installer reaches an existing install.
    steps.run_all(ctx)
    ctx.login.cmds, ctx.login.inputs, ctx.gpu.cmds = [], [], []
    steps.run_all(ctx)
    cmds = " ".join(ctx.login.cmds)
    assert "groupadd --system sd-agent" in cmds                 # accounts_login
    assert "/etc/slurm-deck-web/agent.env" in cmds              # secrets
    assert "systemctl restart deck-agent" not in cmds           # agent stays done
    assert ctx.gpu.cmds == []                                   # gpuhost_bootstrap stays done


def test_accounts_login_puts_sdweb_and_sdworker_in_the_socket_group(ctx):
    steps.accounts_login(ctx)
    cmds = ctx.login.cmds
    make = cmds.index("getent group sd-agent >/dev/null || groupadd --system sd-agent")
    assert cmds.index("usermod -aG sd-agent sdweb") > make
    assert cmds.index("usermod -aG sd-agent sdworker") > make


def test_compose_env_and_agent_env_name_the_socket_group(ctx):
    steps.run_all(ctx)
    written = " ".join(ctx.login.inputs)
    assert "SD_AGENT_GID=985" in written
    assert "SD_AGENT_SOCKET_GROUP=sd-agent" in written


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
              "agent_db_password": "y", "compose_dir": "/srv/deploy", "agent_gid": 3,
              "session_hostname": "sessions.deck.example.org",
              **{k: "x" for k in steps.MAIL_SECRETS}}
    for tmpl in sorted(steps.TEMPLATES.glob("*.tmpl")):
        assert not re.search(r"=$", steps.render(tmpl.name, {**values, "mail_from": "x"}), re.M)
        with pytest.raises(steps.InstallError):
            steps.render(tmpl.name,
                         {**values, **{k: "" for k in values if k not in steps.OPTIONAL}})


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


def test_deck_agent_may_write_the_sites_nfs_root(ctx):
    # The unit is ProtectSystem=strict; only the NFS root the site gave is writable.
    ctx.state.data["answers"]["nfs_root"] = "/data/nfs"
    steps.run_all(ctx)
    conf = "/etc/systemd/system/deck-agent.service.d/nfs-root.conf"
    cmds = ctx.login.cmds
    at = [n for n, c in enumerate(cmds) if f"mv {conf}.new" in c]
    assert [ctx.login.inputs[n] for n in at] == ["[Service]\nReadWritePaths=/data/nfs\n"]
    assert at[0] < next(n for n, c in enumerate(cmds) if "restart deck-agent" in c)


def test_the_first_admin_is_listed_in_the_admins_file_before_create_admin(ctx):
    steps.run_all(ctx)
    add = next(i for i, c in enumerate(ctx.login.cmds) if "/etc/slurm-deck-web/admins" in c)
    create = next(i for i, c in enumerate(ctx.login.cmds) if "create-admin" in c)
    assert add < create
    assert ctx.login.cmds[add] == steps.admins_add_cmd("/etc/slurm-deck-web/admins", "ada")


def test_admins_add_cmd_lists_a_name_once_and_keeps_the_others(tmp_path):
    import getpass
    f = tmp_path / "admins"
    f.write_text("kasun\n")
    f.chmod(0o664)
    owner = f"{getpass.getuser()}:"
    for _ in range(2):
        subprocess.run(["sh", "-c", steps.admins_add_cmd(str(f), "ada", owner)], check=True)
    assert f.read_text() == "kasun\nada\n"
    assert f.stat().st_mode & 0o777 == 0o644
    (tmp_path / "new").unlink(missing_ok=True)
    subprocess.run(["sh", "-c", steps.admins_add_cmd(str(tmp_path / "new"), "ada", owner)],
                   check=True)
    assert (tmp_path / "new").read_text() == "ada\n"


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


def test_db_firewall_is_loaded_before_the_web_stack_publishes_postgres(ctx):
    steps.run_all(ctx)
    names = [n for n, _ in steps.STEPS]
    assert names.index("agent") < names.index("db_firewall") < names.index("web_stack")
    nft = next(i for i, c in enumerate(ctx.login.cmds) if "sd-db-port.nft.new" in c)
    up = next(i for i, c in enumerate(ctx.login.cmds) if "docker compose up" in c)
    assert nft < up
    written = " ".join(ctx.login.inputs)
    assert "table inet sd_db" in written and "ExecStart=/usr/sbin/nft -f" in written
    assert ("systemctl daemon-reload && systemctl enable sd-db-firewall "
            "&& systemctl restart sd-db-firewall") in ctx.login.cmds
    assert "nft list table inet sd_db >/dev/null" in ctx.login.cmds


def test_preflight_needs_nft_for_the_db_firewall(ctx):
    ctx.login.codes = {"command -v nft": 1}
    with pytest.raises(steps.InstallError, match="nftables"):
        steps.preflight(ctx)


def _harden_runs(target, mode):
    return [c for c in target.cmds if re.search(rf"/harden/[\w-]+\.sh --{mode}\b", c)]


def test_harden_checks_every_script_on_its_node_then_applies_when_confirmed(ctx):
    ctx.apply_hardening = True
    ctx.state.data["answers"].update(nfs_root="/srv/share", sysadmins="amasha,dinuka")
    assert steps.harden(ctx) is None
    lib = "/usr/local/lib/slurm-deck"
    for t in (ctx.login, ctx.gpu):   # staged root-owned, in the layout the scripts expect
        staged = " ".join(t.cmds)
        assert f"{lib}/cluster/harden/remove-docker-group.sh.new" in staged
        assert f"{lib}/cluster/sd-stats-writer.new" in staged
        assert f"{lib}/systemd/sd-stats-writer.service.new" in staged
    login_checks, gpu_checks = _harden_runs(ctx.login, "check"), _harden_runs(ctx.gpu, "check")
    assert [re.search(r"harden/([\w-]+)\.sh", c)[1] for c in login_checks] == [
        "remove-docker-group", "service-accounts"]
    assert [re.search(r"harden/([\w-]+)\.sh", c)[1] for c in gpu_checks] == [
        "remove-docker-group", "service-accounts", "shared-areas", "named-acls"]
    for t in (ctx.login, ctx.gpu):
        checks, applies = _harden_runs(t, "check"), _harden_runs(t, "apply")
        assert len(applies) == len(checks)
        assert t.cmds.index(checks[-1]) < t.cmds.index(applies[0])   # every check before any apply
        assert all("NFS_ROOT=/srv/share SYSADMINS=amasha,dinuka " in c for c in checks + applies)
    login_docker = next(c for c in _harden_runs(ctx.login, "apply") if "docker-group" in c)
    assert login_docker.endswith("--apply --keep slurmadmin")   # it runs docker compose
    gpu_docker = next(c for c in _harden_runs(ctx.gpu, "apply") if "docker-group" in c)
    assert gpu_docker.endswith("--apply")   # the GPU admin is root: nobody extra to keep


def test_harden_keeps_a_non_root_gpu_admin_in_the_docker_group(ctx):
    ctx.apply_hardening = True
    ctx.state.data["answers"]["gpu_admin_user"] = "root-daham"
    steps.harden(ctx)
    gpu_docker = next(c for c in _harden_runs(ctx.gpu, "apply") if "docker-group" in c)
    assert gpu_docker.endswith("--apply --keep root-daham")


def test_install_does_not_finish_until_the_hardening_is_applied(ctx):
    ctx.apply_hardening = False   # no --apply-hardening and no terminal to say yes on
    with pytest.raises(steps.InstallError, match="--apply-hardening"):
        steps.run_all(ctx)
    assert _harden_runs(ctx.login, "check") and _harden_runs(ctx.gpu, "check")
    assert not _harden_runs(ctx.login, "apply") and not _harden_runs(ctx.gpu, "apply")
    assert "harden" not in ctx.state.data["done"] and "summary" not in ctx.state.data["done"]
    ctx.apply_hardening = True
    steps.run_all(ctx)   # the rerun resumes at harden
    assert _harden_runs(ctx.gpu, "apply")
    assert ctx.state.data["done"][-2:] == ["harden", "summary"]


def test_harden_stops_the_install_when_a_script_fails(ctx):
    ctx.apply_hardening = True
    ctx.gpu.fail_on = r"shared-areas\.sh --check"   # e.g. sd-ops is missing
    with pytest.raises(steps.InstallError):
        steps.harden(ctx)
    assert not _harden_runs(ctx.gpu, "apply")


def test_harden_comes_after_the_accounts_it_needs_and_before_the_summary():
    names = [n for n, _ in steps.STEPS]
    assert names.index("gpuhost_bootstrap") < names.index("harden") < names.index("summary")
    assert names[-2:] == ["harden", "summary"]


def test_preflight_needs_python3_venv(ctx):
    ctx.login.codes = {"import ensurepip, venv": 1}
    with pytest.raises(steps.InstallError, match="install python3-venv"):
        steps.preflight(ctx)


def test_preflight_names_the_compose_plugin_when_docker_compose_is_missing(ctx):
    ctx.login.codes = {"docker compose version": 1}
    with pytest.raises(steps.InstallError, match="Compose v2 plugin.*docker-compose-v2"):
        steps.preflight(ctx)


def test_agent_rebuilds_a_venv_that_has_no_pip(ctx):
    steps.agent(ctx)
    venv = "/opt/slurm-deck-web/agent-venv"
    assert (f"[ -x {venv}/bin/pip ] || {{ rm -rf {venv}; python3 -m venv {venv}; }}"
            in ctx.login.cmds)


def _secrets_env(ctx):
    writes = zip(ctx.login.cmds, ctx.login.inputs, strict=True)
    return [i for c, i in writes if "secrets.env.new" in c][-1]


def test_resend_without_an_api_key_is_an_error(ctx):
    ctx.state.data["answers"]["mail_provider"] = "resend"
    with pytest.raises(steps.InstallError, match="resend_api_key"):
        steps.run_all(ctx)


def test_resend_key_from_the_answers_file_reaches_secrets_env(ctx):
    ctx.state.data["answers"]["mail_provider"] = "resend"
    steps.run_all(ctx, {"resend_api_key": "re_secret123"})
    env = _secrets_env(ctx)
    assert "SD_RESEND_API_KEY=re_secret123" in env
    assert re.search(r"^SD_SMTP_PASSWORD=$", env, re.M)                  # unused: empty
    assert ctx.state.data["answers"]["resend_api_key"] == "re_secret123"   # kept for reruns


def test_smtp_needs_host_port_user_and_password(ctx):
    ctx.state.data["answers"]["mail_provider"] = "smtp"
    with pytest.raises(steps.InstallError, match="smtp_host, smtp_password, smtp_port, smtp_user"):
        steps.run_all(ctx)


def test_smtp_answers_reach_secrets_env(ctx):
    ctx.state.data["answers"]["mail_provider"] = "smtp"
    steps.run_all(ctx, {"smtp_host": "mail.example.org", "smtp_port": "587",
                        "smtp_user": "deck", "smtp_password": "pw-secret"})
    env = _secrets_env(ctx)
    for line in ("SD_SMTP_HOST=mail.example.org", "SD_SMTP_PORT=587", "SD_SMTP_USER=deck",
                 "SD_SMTP_PASSWORD=pw-secret", "SD_SMTP_STARTTLS=true"):
        assert re.search(rf"^{line}$", env, re.M)
    assert re.search(r"^SD_RESEND_API_KEY=$", env, re.M)


def test_smtp_port_must_be_a_number(ctx):
    ctx.state.data["answers"]["mail_provider"] = "smtp"
    with pytest.raises(steps.InstallError, match="smtp_port"):
        steps.run_all(ctx, {"smtp_host": "h", "smtp_port": "smtp", "smtp_user": "u",
                            "smtp_password": "p"})


def test_mail_secrets_are_taken_on_a_rerun_after_site_values_is_done(ctx):
    # The live install resumes past site_values; the key comes in the answers file then.
    steps.run_all(ctx)
    ctx.state.data["answers"]["mail_provider"] = "resend"
    steps.run_all(ctx, {"resend_api_key": "re_later"})
    assert "SD_RESEND_API_KEY=re_later" in _secrets_env(ctx)


def test_mail_secrets_are_asked_hidden_on_a_terminal(ctx, monkeypatch):
    ctx.state.data["answers"]["mail_provider"] = "resend"
    monkeypatch.setattr(steps.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("input() echoes"))
    monkeypatch.setattr(steps.getpass, "getpass", lambda prompt="": "re_typed")
    steps.mail_secrets(ctx)
    assert ctx.state.data["answers"]["resend_api_key"] == "re_typed"


def test_check_never_shows_the_mail_secrets(ctx, capsys):
    ctx.state.data["answers"].update(mail_provider="smtp", smtp_host="h", smtp_port="25",
                                     smtp_user="u", smtp_password="pw-secret",
                                     resend_api_key="re_secret123")
    logged = []
    login = ctx.login
    ctx.check, ctx.login, ctx.log = True, steps.Dry(login, ctx.planned), logged.append
    steps.run_all(ctx)
    shown = "\n".join(ctx.planned + logged) + capsys.readouterr().out
    assert "pw-secret" not in shown and "re_secret123" not in shown
