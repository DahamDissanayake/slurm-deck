"""The installer's steps. Each runs shell commands through a Target (this
machine, or the GPU host over SSH) and is safe to run twice: the commands
themselves check before they change anything, and State records what finished,
so a rerun after a failure resumes at the step that failed.

With --check every Target is a Dry one: commands are listed, none is run."""

from __future__ import annotations

import json
import secrets
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any

from deploy.installer.state import State

TEMPLATES = Path(__file__).parent / "templates"
CONF = "/etc/slurm-deck-web"
KEY = f"{CONF}/sdprov_ed25519"
OPS_UIDS = range(850, 900)
OPTIONAL = {"mail_from"}   # the only template values allowed to be empty


class InstallError(Exception):
    pass


class Target:
    """Where commands run. run() takes a shell command line."""
    name = "login"

    def run(self, cmd: str, input_text: str | None = None,
            check: bool = True) -> subprocess.CompletedProcess[str]:
        raise NotImplementedError

    def write(self, path: str, content: str, mode: str = "0644", owner: str = "root:root") -> None:
        tmp = shlex.quote(path + ".new")
        self.run(f"umask 077 && cat > {tmp} && chown {owner} {tmp} && chmod {mode} {tmp} "
                 f"&& mv {tmp} {shlex.quote(path)}", input_text=content)


class Local(Target):
    def run(self, cmd: str, input_text: str | None = None,
            check: bool = True) -> subprocess.CompletedProcess[str]:
        r = subprocess.run(["sh", "-c", cmd], input=input_text, text=True, capture_output=True)
        if check and r.returncode != 0:
            raise InstallError(f"{self.name}: {cmd}\n{r.stderr.strip()}")
        return r


class SSH(Local):
    """The GPU host through an admin login (root, or any account with sudo)."""
    name = "gpu"

    def __init__(self, host: str, user: str, key: str = "") -> None:
        self.host, self.user, self.key = host, user, key

    def run(self, cmd: str, input_text: str | None = None,
            check: bool = True) -> subprocess.CompletedProcess[str]:
        remote = cmd if self.user == "root" else f"sudo sh -c {shlex.quote(cmd)}"
        ssh = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
               *(["-i", self.key] if self.key else []), f"{self.user}@{self.host}", remote]
        r = subprocess.run(ssh, input=input_text, text=True, capture_output=True)
        if check and r.returncode != 0:
            raise InstallError(f"gpu: {cmd}\n{r.stderr.strip()}")
        return r


class Dry(Target):
    """--check: records the command and pretends it worked."""
    def __init__(self, real: Target, planned: list[str]) -> None:
        self.name, self.planned = real.name, planned

    def run(self, cmd: str, input_text: str | None = None,
            check: bool = True) -> subprocess.CompletedProcess[str]:
        self.planned.append(f"[{self.name}] {cmd}")
        return subprocess.CompletedProcess(cmd, 0, "", "")


@dataclass
class Ctx:
    login: Target
    gpu_target: Callable[[dict[str, Any]], Target]
    state: State
    repo: Path
    check: bool = False
    accept_small: bool = False
    planned: list[str] = field(default_factory=list)
    log: Callable[[str], None] = print

    @property
    def answers(self) -> dict[str, Any]:
        return dict(self.state.data["answers"])

    @property
    def gpu(self) -> Target:
        gpu = self.gpu_target(self.answers)
        return Dry(gpu, self.planned) if self.check else gpu

    def secret(self, name: str, nbytes: int = 24) -> str:
        """Made once and kept in the state file, so a rerun writes the same value."""
        return str(self.state.data["generated"].setdefault(name, secrets.token_hex(nbytes)))

    def out(self, target: Target, cmd: str, planned: str) -> str:
        """A command's output; in --check, a placeholder."""
        return target.run(cmd).stdout.strip() or (planned if self.check else "")


def render(name: str, values: dict[str, Any]) -> str:
    """A template with its values; an empty required value is an error."""
    tmpl = Template((TEMPLATES / name).read_text())
    ids = tmpl.get_identifiers()
    empty = [i for i in ids if i not in OPTIONAL and not str(values.get(i, "")).strip()]
    if empty:
        raise InstallError(f"{name}: no value for {', '.join(sorted(empty))}")
    return tmpl.substitute({i: values.get(i, "") for i in ids})


# (key, prompt, default); no default means the answer is required.
SITE_FIELDS: list[tuple[str, str, str | None]] = [
    ("public_hostname", "Public hostname users open", None),
    ("gpu_host", "GPU host address (on virbr0)", None),
    ("login_addr", "Login node address", None),
    ("lan_addr", "LAN address users reach", None),
    ("nfs_root", "NFS root", "/shared"),
    ("partition", "Slurm partition", "gpu"),
    ("compute_node", "Compute node name", None),
    ("slurm_account", "Slurm account for new users", "default"),
    ("slurm_qos", "Slurm QOS for new users", "normal"),
    ("cluster_name", "Cluster name", "Slurm Deck"),
    ("timezone", "Timezone (IANA name)", "UTC"),
    ("mail_provider", "Mail provider (resend, smtp or none)", "none"),
    ("mail_from", "Mail from address", ""),
    ("admin_email", "First admin email", None),
    ("admin_name", "First admin full name", None),
    ("admin_username", "First admin username", None),
    ("admin_unix_user", "Account that runs docker compose (slurmadmin)", "slurmadmin"),
    ("gpu_admin_user", "GPU host admin login (root, or an account with sudo)", "root"),
    ("gpu_admin_key", "SSH key for that login (blank for the default)", ""),
]


def preflight(ctx: Ctx) -> None:
    checks = [  # (what, shell test, a small machine is only a warning)
        ("at least 4 vCPUs", '[ "$(nproc)" -ge 4 ]', True),
        ("at least 12 GB RAM", "[ \"$(awk '/MemTotal/{print $2}' /proc/meminfo)\" -ge 11500000 ]", True),
        ("swap is present", "[ \"$(awk '/SwapTotal/{print $2}' /proc/meminfo)\" -gt 0 ]", True),
        ("sinfo works", "sinfo -h >/dev/null", False),
        ("munge works", "munge -n | unmunge >/dev/null", False),
        ("Docker with Compose v2", "docker compose version >/dev/null", False),
        ("Python 3.11 or newer", "python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'", False),
    ]
    for what, test, soft in checks:
        if ctx.login.run(test, check=False).returncode == 0:
            continue
        if soft and ctx.accept_small:
            ctx.log(f"warning: this machine does not have {what}")
        else:
            raise InstallError(f"preflight: need {what}" + (" (--accept-small to go on)" if soft else ""))


def site_values(ctx: Ctx, given: dict[str, Any] | None = None) -> None:
    answers = {**ctx.state.data["answers"], **(given or {})}
    for key, prompt, default in SITE_FIELDS:
        if key in answers:
            continue
        value = default   # without a terminal (or an answers file entry) the default stands
        if sys.stdin.isatty():
            try:
                value = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip() or default
            except EOFError:
                pass
        if value is None:
            raise InstallError(f"site_values: no answer for {key} ({prompt}); "
                               "give it in the --answers file")
        answers[key] = value
    if ctx.login.run(f"mountpoint -q {shlex.quote(answers['nfs_root'])}", check=False).returncode:
        raise InstallError(f"site_values: {answers['nfs_root']} is not a mounted share")
    ctx.state.data["answers"] = answers
    if not ctx.check:
        ctx.state.save()


def _ops_uid(ctx: Ctx) -> int:
    """sd-ops needs the same UID on both nodes: reuse it, or take a free one."""
    kept = ctx.state.data.get("ops_uid")
    if kept:
        return int(kept)
    have = ctx.login.run("id -u sd-ops", check=False)
    if have.returncode == 0 and have.stdout.strip():
        uid = int(have.stdout)
    elif ctx.check:
        return OPS_UIDS[0]
    else:
        uid = next((u for u in OPS_UIDS if all(
            t.run(f"getent passwd {u}", check=False).returncode != 0
            for t in (ctx.login, ctx.gpu))), 0)
        if not uid:
            raise InstallError(f"no free UID in {OPS_UIDS.start}-{OPS_UIDS.stop - 1} on both nodes")
    ctx.state.data["ops_uid"] = uid
    ctx.state.save()
    return uid


def _account(name: str, uid: int | None = None) -> str:
    """A system account with no shell login, made only if it is missing."""
    flags = f"--system --no-create-home --shell /usr/sbin/nologin{f' --uid {uid}' if uid else ''}"
    return f"id -u {name} >/dev/null 2>&1 || useradd {flags} {name}"


def accounts_login(ctx: Ctx) -> None:
    uid = _ops_uid(ctx)
    for cmd in ("getent group webusers >/dev/null || groupadd webusers",
                _account("sdweb"), _account("sdworker"),
                _account("sd-ops", uid), "usermod -aG gpuadmins sd-ops"):
        ctx.login.run(cmd)


def gpuhost_bootstrap(ctx: Ctx) -> None:
    gpu, a = ctx.gpu, ctx.answers
    uid = _ops_uid(ctx)
    for cmd in ("getent group webusers >/dev/null || groupadd webusers",
                _account("sd-ops", uid), "usermod -aG gpuadmins sd-ops",
                "id -u sdprov >/dev/null 2>&1 || useradd --system --create-home "
                "--home-dir /home/sdprov --shell /bin/sh sdprov"):
        gpu.run(cmd)
    gpu.write("/usr/local/sbin/sd-gpu-helper", (ctx.repo / "gpuhost/sd-gpu-helper").read_text(), "0755")
    gpu.run(f"install -d -m 0755 {CONF}")
    gpu.write(f"{CONF}/gpu-helper.env", render("gpu-helper.env.tmpl", a))
    sudoers = (ctx.repo / "deploy/cluster/gpuhost/sudoers-sdprov").read_text()
    gpu.run("install -d -m 0755 /etc/sudoers.d")
    gpu.write("/etc/sudoers.d/sdprov.check", sudoers, "0440")   # only moved into place if valid
    gpu.run("visudo -cf /etc/sudoers.d/sdprov.check && mv /etc/sudoers.d/sdprov.check "
            "/etc/sudoers.d/sdprov || { rm -f /etc/sudoers.d/sdprov.check; exit 1; }")
    ctx.login.run(f"install -d -m 0755 {CONF}")
    ctx.login.run(f"[ -f {KEY} ] || ssh-keygen -q -t ed25519 -N '' -C deck-agent -f {KEY}; "
                  f"chmod 0600 {KEY}")
    pub = ctx.out(ctx.login, f"cat {KEY}.pub", "<public key>")
    gpu.run("install -d -m 0700 -o sdprov -g sdprov /home/sdprov/.ssh")
    gpu.write("/home/sdprov/.ssh/authorized_keys",
              f'restrict,command="sudo /usr/local/sbin/sd-gpu-helper" {pub}\n', "0600", "sdprov:sdprov")
    ping = ctx.login.run(f"ssh -i {KEY} -o BatchMode=yes -o StrictHostKeyChecking=accept-new "
                         f"sdprov@{shlex.quote(a['gpu_host'])} ping").stdout
    if not ctx.check and not json.loads(ping or "{}").get("ok"):
        raise InstallError("gpuhost_bootstrap: the helper did not answer ping")


def slurm_assoc(ctx: Ctx) -> None:
    a = ctx.answers
    ctx.login.run(f"sacctmgr -i add user sd-ops account={shlex.quote(a['slurm_account'])} "
                  f"qos={shlex.quote(a['slurm_qos'])}")


def _values(ctx: Ctx) -> dict[str, Any]:
    uid = lambda user: ctx.out(ctx.login, f"id -u {user}", "<uid>")  # noqa: E731
    gid = lambda user: ctx.out(ctx.login, f"id -g {user}", "<gid>")  # noqa: E731
    return {**ctx.answers, "web_uid": uid("sdweb"), "web_gid": gid("sdweb"),
            "worker_uid": uid("sdworker"), "worker_gid": gid("sdworker"),
            "db_password": ctx.secret("db_password"), "agent_db_password": ctx.secret("agent_db_password")}


def secrets_step(ctx: Ctx) -> None:
    v, admin = _values(ctx), ctx.answers["admin_unix_user"]
    web_owner = f"{admin}:sdweb"
    ctx.login.run(f"install -d -m 0755 {CONF}")
    ctx.login.write(f"{CONF}/grant.key", ctx.secret("grant_key", 32) + "\n", "0600")
    ctx.login.write(f"{CONF}/agent.env", render("agent.env.tmpl", v), "0600")
    ctx.login.write(f"{CONF}/site.env", render("site.env.tmpl", v))
    ctx.login.write(f"{CONF}/web.env", render("web.env.tmpl", v), "0640", web_owner)
    ctx.login.write(f"{CONF}/secrets.env", render("secrets.env.tmpl", v), "0640", web_owner)
    ctx.login.write(str(ctx.repo / "deploy/.env"), render("compose.env.tmpl", v), "0640", web_owner)


def agent(ctx: Ctx) -> None:
    venv, admin = "/opt/slurm-deck-web/agent-venv", ctx.answers["admin_unix_user"]
    ctx.login.run(f"install -d -o {shlex.quote(admin)} /opt/slurm-deck-web")
    ctx.login.run(f"[ -x {venv}/bin/python ] || python3 -m venv {venv}")
    ctx.login.run(f"{venv}/bin/pip install -q {shlex.quote(str(ctx.repo) + '[agent]')}")
    ctx.login.write("/etc/systemd/system/deck-agent.service",
                    (ctx.repo / "deploy/systemd/deck-agent.service").read_text())
    ctx.login.run("systemctl daemon-reload && systemctl enable deck-agent && systemctl restart deck-agent")
    call = ("curl -sf --unix-socket /run/slurm-deck-web/agent.sock -X POST "
            "-H 'Content-Type: application/json' -d '{}' http://agent/v1/cluster.disk_free")
    ctx.login.run(f"for i in $(seq 20); do runuser -u sdworker -- {call} >/dev/null && exit 0; "
                  "sleep 1; done; exit 1")   # a one-shot call as the worker account


def web_stack(ctx: Ctx) -> None:
    a, compose = ctx.answers, f"cd {shlex.quote(str(ctx.repo / 'deploy'))} && docker compose"
    ctx.login.run(f"{compose} build && {compose} up -d")   # `up` runs the migration first
    r = ctx.login.run(
        f"{compose} run --rm web python -m sdweb.cli create-admin --email {shlex.quote(a['admin_email'])} "
        f"--full-name {shlex.quote(a['admin_name'])} --username {shlex.quote(a['admin_username'])} 2>&1",
        check=False)
    if r.returncode != 0 and "already exists" not in r.stdout:
        raise InstallError(f"web_stack: creating the first admin failed:\n{r.stdout.strip()}")
    if not ctx.check:
        ctx.log(r.stdout.strip())


def network(ctx: Ctx) -> bool:
    script = ctx.repo / "deploy/cluster/network/network.sh"
    if not script.exists():
        ctx.log("network: the network scripts are not in this checkout yet; skipped")
        return False
    ctx.login.run(f"{shlex.quote(str(script))} --apply")
    return True


def summary(ctx: Ctx) -> None:
    a = ctx.answers
    if ctx.check:
        return
    ctx.log(f"\nSlurm Deck is installed.\n  Open:        https://{a['public_hostname']}\n"
            f"  CA cert:     https://{a['public_hostname']}/ca.crt (install it once per device)\n"
            f"  If the name does not resolve, add to the hosts file:\n"
            f"               {a['lan_addr']} {a['public_hostname']}\n"
            f"  Cutover:     docs/runbooks/cutover.md")


STEPS: list[tuple[str, Callable[[Ctx], Any]]] = [
    ("preflight", preflight), ("site_values", site_values), ("accounts_login", accounts_login),
    ("gpuhost_bootstrap", gpuhost_bootstrap), ("slurm_assoc", slurm_assoc),
    ("secrets", secrets_step), ("agent", agent), ("web_stack", web_stack),
    ("network", network), ("summary", summary),
]


def run_all(ctx: Ctx, given: dict[str, Any] | None = None) -> None:
    """Run the steps not yet done, stopping at the first that fails."""
    for name, step in STEPS:
        if ctx.state.done(name):
            ctx.log(f"{name}: done already")
            continue
        ctx.log(f"==> {name}")
        try:
            finished = step(ctx, given) if step is site_values else step(ctx)
        except InstallError:
            ctx.log(f"{name} failed; fix the cause and run the installer again to resume")
            raise
        if finished is not False and not ctx.check:
            ctx.state.mark(name)
