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
    apply_hardening: bool = False
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
    ("session_hostname", "Hostname for notebook, TensorBoard and terminal sessions "
     "(blank: sessions.<public hostname>)", ""),
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
    ("sysadmins", "Sysadmins who keep the docker group (comma-separated)", ""),
]


def preflight(ctx: Ctx) -> None:
    checks = [  # (what, shell test, a small machine is only a warning)
        ("at least 4 vCPUs", '[ "$(nproc)" -ge 4 ]', True),
        ("at least 12 GB RAM", "[ \"$(awk '/MemTotal/{print $2}' /proc/meminfo)\" -ge 11500000 ]", True),
        ("swap is present", "[ \"$(awk '/SwapTotal/{print $2}' /proc/meminfo)\" -gt 0 ]", True),
        ("sinfo works", "sinfo -h >/dev/null", False),
        ("munge works", "munge -n | unmunge >/dev/null", False),
        ("Docker with Compose v2", "docker compose version >/dev/null", False),
        ("nftables (nft)", "command -v nft >/dev/null", False),
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
    # Sessions get their own name, never the app's (SLURM-56): a job's pages
    # must not share an origin with the platform.
    if not str(answers.get("session_hostname") or "").strip():
        answers["session_hostname"] = f"sessions.{answers['public_hostname']}"
    if answers["session_hostname"].lower() == str(answers["public_hostname"]).lower():
        raise InstallError("site_values: the session hostname must differ from the public one")
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
            "compose_dir": str(ctx.repo / "deploy"),
            "db_password": ctx.secret("db_password"), "agent_db_password": ctx.secret("agent_db_password")}


def admins_add_cmd(path: str, username: str, owner: str = "root:root") -> str:
    """List username in deck-agent's admins file (root 0644), once, keeping the others.
    deck-agent gives the admin role only to names in this file."""
    p, u = shlex.quote(path), shlex.quote(username)
    return (f"touch {p} && chown {owner} {p} && chmod 0644 {p} "
            f"&& (grep -qxF -- {u} {p} || printf '%s\\n' {u} >> {p})")


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
    ctx.login.run(admins_add_cmd(f"{CONF}/admins", ctx.answers["admin_username"]))


def agent(ctx: Ctx) -> None:
    venv, admin = "/opt/slurm-deck-web/agent-venv", ctx.answers["admin_unix_user"]
    ctx.login.run(f"install -d -o {shlex.quote(admin)} /opt/slurm-deck-web")
    ctx.login.run(f"[ -x {venv}/bin/python ] || python3 -m venv {venv}")
    ctx.login.run(f"{venv}/bin/pip install -q {shlex.quote(str(ctx.repo) + '[agent]')}")
    ctx.login.write("/etc/systemd/system/deck-agent.service",
                    (ctx.repo / "deploy/systemd/deck-agent.service").read_text())
    # The unit can write only the NFS root it lists (/shared); this adds the site's.
    ctx.login.run("install -d /etc/systemd/system/deck-agent.service.d")
    ctx.login.write("/etc/systemd/system/deck-agent.service.d/nfs-root.conf",
                    f"[Service]\nReadWritePaths={ctx.answers['nfs_root']}\n")
    ctx.login.run("systemctl daemon-reload && systemctl enable deck-agent && systemctl restart deck-agent")
    call = ("curl -sf --unix-socket /run/slurm-deck-web/agent.sock -X POST "
            "-H 'Content-Type: application/json' -d '{}' http://agent/v1/cluster.disk_free")
    ctx.login.run(f"for i in $(seq 20); do runuser -u sdworker -- {call} >/dev/null && exit 0; "
                  "sleep 1; done; exit 1")   # a one-shot call as the worker account


def db_firewall(ctx: Ctx) -> None:
    """Postgres is published on the login node's loopback for deck-agent (root); this
    nftables table refuses everyone else, there and on the Docker bridges (SLURM-66)."""
    lib = "/usr/local/lib/slurm-deck"
    ctx.login.run(f"install -d -m 0755 {lib}")
    ctx.login.write(f"{lib}/sd-db-port.nft", (ctx.repo / "deploy/cluster/sd-db-port.nft").read_text())
    ctx.login.write("/etc/systemd/system/sd-db-firewall.service",
                    (ctx.repo / "deploy/systemd/sd-db-firewall.service").read_text())
    ctx.login.run("systemctl daemon-reload && systemctl enable sd-db-firewall "
                  "&& systemctl restart sd-db-firewall")
    ctx.login.run("nft list table inet sd_db >/dev/null")


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


def backups(ctx: Ctx) -> None:
    """The nightly backup: a timer that runs deploy/cluster/sd-backup.sh as the admin account."""
    a, systemd = ctx.answers, ctx.repo / "deploy/systemd"
    unit = (systemd / "sd-backup.service").read_text().replace("@REPO@", str(ctx.repo))
    timer = (systemd / "sd-backup.timer").read_text().replace("@CLUSTER_TZ@", a["timezone"])
    ctx.login.run(f"install -d -m 0700 -o {shlex.quote(a['admin_unix_user'])} /var/backups/slurm-deck")
    ctx.login.write("/etc/systemd/system/sd-backup.service",
                    unit.replace("User=slurmadmin", f"User={a['admin_unix_user']}"))
    ctx.login.write("/etc/systemd/system/sd-backup.timer", timer)
    ctx.login.run("systemctl daemon-reload && systemctl enable --now sd-backup.timer")


def network(ctx: Ctx) -> bool:
    """On the GPU host: forward 80 and 443 to the login node, limit the session ports to it,
    and publish the name over mDNS. Returns False (tried again next run) when the host's
    2225 forward can't be found, so the forward has to be set up by hand."""
    gpu, src, lib = ctx.gpu, ctx.repo / "deploy/cluster/gpuhost", "/usr/local/lib/slurm-deck"
    gpu.run(f"install -d -m 0755 {lib}")
    gpu.write(f"{lib}/sd-web-forward.sh", (src / "sd-web-forward.sh").read_text(), "0755")
    gpu.write(f"{lib}/sd-session-ports.nft", (src / "sd-session-ports.nft").read_text())
    r = gpu.run(f"{lib}/sd-web-forward.sh --apply", check=False)
    ctx.log((r.stdout or "").strip())
    if r.returncode == 2:
        ctx.log(f"network: {r.stderr.strip()}")
        return False
    if r.returncode:
        raise InstallError(f"network: the forward failed: {r.stderr.strip()}")
    if gpu.run("command -v avahi-publish >/dev/null", check=False).returncode:
        ctx.log("network: avahi-utils isn't installed on the GPU host, so the .local name "
                "isn't announced; users can use the hosts-file line instead")
        return True
    for unit in ("sd-mdns-alias", "sd-mdns-sessions"):
        gpu.write(f"/etc/systemd/system/{unit}.service", (src / f"{unit}.service").read_text())
    gpu.run("systemctl daemon-reload && systemctl enable --now sd-mdns-alias sd-mdns-sessions")
    return True


# (script, nodes it runs on), in order: shared-areas.sh needs sd-ops (gpuhost_bootstrap).
HARDENING = [("remove-docker-group.sh", ("login", "gpu")),
             ("service-accounts.sh", ("login", "gpu")),
             ("shared-areas.sh", ("gpu",))]


def _confirm(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        return input(f"{question} [y/N]: ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def harden(ctx: Ctx) -> None:
    """The §10 cluster hardening (deploy/cluster/harden): each script's --check on its
    node, then --apply only once confirmed (--apply-hardening, or yes at the prompt).
    Unconfirmed, the step fails, so the install doesn't finish until it has been applied.
    The scripts run from a root-owned copy, not from the admin's checkout."""
    a, lib, src = ctx.answers, "/usr/local/lib/slurm-deck", ctx.repo / "deploy"
    nodes = {"login": ctx.login, "gpu": ctx.gpu}
    files = [(f"cluster/harden/{s}", "0755") for s, _ in HARDENING] + [
        ("cluster/sd-stats-writer", "0755"), ("systemd/sd-stats-writer.service", "0644")]
    for t in nodes.values():
        t.run(f"install -d -m 0755 {lib}/cluster/harden {lib}/systemd")
        for rel, mode in files:
            t.write(f"{lib}/{rel}", (src / rel).read_text(), mode)
    env = (f"NFS_ROOT={shlex.quote(a['nfs_root'])} "
           f"SYSADMINS={shlex.quote(str(a.get('sysadmins') or ''))} ")
    keep = {"login": a["admin_unix_user"],   # runs docker compose
            "gpu": "" if a["gpu_admin_user"] == "root" else a["gpu_admin_user"]}

    def cmd(script: str, node: str, mode: str) -> str:
        extra = f" --keep {shlex.quote(keep[node])}" if (
            mode == "apply" and script == "remove-docker-group.sh" and keep[node]) else ""
        return f"{env}{lib}/cluster/harden/{script} --{mode}{extra}"

    runs = [(s, n) for s, ns in HARDENING for n in ns]
    for script, node in runs:
        ctx.log(f"--- {node}: {script} --check\n"
                + nodes[node].run(cmd(script, node, "check")).stdout.strip())
    if not ctx.check and not ctx.apply_hardening and not _confirm(
            "Apply the hardening above (docker group, service accounts, shared areas)?"):
        raise InstallError("harden: review the --check output above, then run the installer "
                           "again with --apply-hardening (see docs/operations/cutover-runbook.md)")
    for script, node in runs:
        ctx.log(f"--- {node}: {script} --apply\n"
                + nodes[node].run(cmd(script, node, "apply")).stdout.strip())


def summary(ctx: Ctx) -> None:
    a = ctx.answers
    if ctx.check:
        return
    ctx.log(f"\nSlurm Deck is installed.\n  Open:        https://{a['public_hostname']}\n"
            f"  CA cert:     https://{a['public_hostname']}/ca.crt (install it once per device)\n"
            f"  If the name does not resolve, add to the hosts file:\n"
            f"               {a['lan_addr']} {a['public_hostname']} {a['session_hostname']}\n"
            f"  Cutover:     docs/operations/cutover-runbook.md")


STEPS: list[tuple[str, Callable[[Ctx], Any]]] = [
    ("preflight", preflight), ("site_values", site_values), ("accounts_login", accounts_login),
    ("gpuhost_bootstrap", gpuhost_bootstrap), ("slurm_assoc", slurm_assoc),
    ("secrets", secrets_step), ("agent", agent), ("db_firewall", db_firewall),
    ("web_stack", web_stack),
    ("backups", backups), ("network", network), ("harden", harden), ("summary", summary),
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
