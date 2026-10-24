"""Job verbs. Submitting, cancelling and reading history run as the user;
extensions run as root, but only after deck-agent re-checks the owner, the
extension cap and the partition's MaxTime itself, one extension per job at a
time."""

from __future__ import annotations

import re
import sys
import threading
from typing import Any

from deckagent.audit import audit
from deckagent.config import AgentConfig
from deckagent.identity import PosixIdentity, identity_for_user, ops_identity
from deckagent.protocol import AgentError, Caller, RawResponse, RequestContext
from deckagent.runas import run_as
from deckagent.slurmcmd import run_slurm
from deckagent.verbs import files, verb
from sdcore.connect import parse_session_line
from sdcore.slurmparse import (
    SACCT_FORMAT,
    SQUEUE_FORMAT,
    parse_sacct,
    parse_slurm_duration,
    parse_squeue,
)
from sdcore.validate import in_user_job_jail, user_job_root, validate_sbatch

PEOPLE = frozenset({"user", "admin"})
FOLDER_RE = re.compile(r"[A-Za-z0-9._-]{1,80}")
USER_HOURS = (1, 2, 4)
DEFAULT_CAP_HOURS = 24
LIVE_STATES = frozenset({"PENDING", "RUNNING", "SUSPENDED", "CONFIGURING", "COMPLETING",
                         "REQUEUED", "RESIZING"})
LOG_MAX = 1024 * 1024
EXTRA_FILES = frozenset({"tbguard.py"})
EXTRA_MAX = 64 * 1024
_WRITE = ("import os, sys; fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640);"
          " os.write(fd, sys.stdin.buffer.read())")

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


# Seams for tests: which identities run the work.
def _identity(caller: Caller, config: AgentConfig) -> PosixIdentity:
    return identity_for_user(caller, config)


def _ops_identity(caller: Caller, config: AgentConfig) -> PosixIdentity:
    return ops_identity(caller, config)


def _job_lock(job_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(job_id, threading.Lock())


def _job_id(payload: dict[str, Any]) -> str:
    job_id = str(payload.get("job_id", ""))
    if not re.fullmatch(r"\d+(_\d+)?", job_id):
        raise AgentError("bad_job_id", "That isn't a job id.", 400)
    return job_id


def _as_user(ident: PosixIdentity, argv: list[str], data: bytes | None = None) -> None:
    r = run_as(ident, argv, input=data, timeout=30)
    if r.returncode != 0:
        raise AgentError("job_folder_failed", r.stderr.decode(errors="replace").strip()[:300],
                         500)


def _extra_files(raw: Any) -> dict[str, str]:
    """Files written next to job.sbatch: only the TensorBoard token guard."""
    if raw is None:
        return {}
    if (not isinstance(raw, dict) or not set(raw) <= EXTRA_FILES
            or not all(isinstance(v, str) and len(v) <= EXTRA_MAX for v in raw.values())):
        raise AgentError("bad_extra_file", "Only tbguard.py can be added to a job folder.", 422)
    return dict(raw)


@verb("job.submit", allow=PEOPLE)
def submit(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """as_ops (admins only): submit as sd-ops, for work on the shared areas
    such as installing a prebuilt environment."""
    cfg, user, caller = ctx.config, str(ctx.caller.username), ctx.caller
    as_ops = payload.get("as_ops") is True
    if as_ops and (caller.role != "admin" or caller.acting_admin):
        raise AgentError("not_allowed", "Only admins can submit as the shared account.", 403)
    if as_ops:
        user = cfg.ops_user
    folder_name, script = str(payload.get("folder_name", "")), str(payload.get("script", ""))
    if not FOLDER_RE.fullmatch(folder_name) or folder_name in (".", ".."):
        raise AgentError("bad_folder", "That job folder name isn't allowed.", 422)
    problems = validate_sbatch(script, user, nfs_root=cfg.nfs_root)
    if problems:
        raise AgentError("bad_script", "; ".join(problems), 422, {"problems": problems})
    extra = _extra_files(payload.get("extra_files"))
    ident = _ops_identity(caller, cfg) if as_ops else _identity(caller, cfg)
    folder = f"{user_job_root(cfg.nfs_root, user)}/{folder_name}"
    path = f"{folder}/job.sbatch"
    _as_user(ident, ["mkdir", "-p", "-m", "0770", folder])
    _as_user(ident, [sys.executable, "-c", _WRITE, path], script.encode())
    for name, text in extra.items():
        _as_user(ident, [sys.executable, "-c", _WRITE, f"{folder}/{name}"], text.encode())
    out = run_slurm(cfg, ["sbatch", "--parsable", path], as_ident=ident, timeout=30)
    return {"job_id": out.strip().split(";")[0], "folder": folder}


@verb("job.list", allow=PEOPLE)
def list_jobs(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    out = run_slurm(ctx.config, ["squeue", "--noheader", f"--format={SQUEUE_FORMAT}",
                                 "-u", str(ctx.caller.username)])
    return {"jobs": [vars(q) for q in parse_squeue(out)]}


_KEY = re.compile(r"(?:^|\s)([A-Za-z][A-Za-z0-9:/_]*)=")


def _show(ctx: RequestContext, job_id: str, *, gone_code: str = "not_found") -> dict[str, str]:
    """scontrol show job --oneliner as a dict; values may contain spaces (paths)."""
    try:
        text = run_slurm(ctx.config, ["scontrol", "show", "job", job_id, "--oneliner"])
    except AgentError:
        if gone_code == "job_ended":
            raise AgentError("job_ended", "This job has already ended.", 409) from None
        raise AgentError("not_found", "There is no such job.", 404) from None
    marks = list(_KEY.finditer(text.strip()))
    fields = {m.group(1): text.strip()[m.end():(marks[i + 1].start() if i + 1 < len(marks)
                                                   else None)].strip()
              for i, m in enumerate(marks)}
    caller = ctx.caller
    fields["_owner"] = fields.get("UserId", "").split("(")[0]
    if caller.role != "admin" and fields["_owner"] != caller.username:
        raise AgentError("not_found", "There is no such job.", 404)
    return fields


@verb("job.show", allow=PEOPLE)
def show(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    f = _show(ctx, _job_id(payload))
    return {"owner": f["_owner"], "state": f.get("JobState", ""),
            "time_limit_s": parse_slurm_duration(f.get("TimeLimit", "")),
            "run_time_s": parse_slurm_duration(f.get("RunTime", "")),
            "std_out": f.get("StdOut", ""), "std_err": f.get("StdErr", ""),
            "work_dir": f.get("WorkDir", ""), "node": f.get("NodeList", ""),
            "exit_code": f.get("ExitCode", "")}


def _live(f: dict[str, str]) -> None:
    if f.get("JobState", "") not in LIVE_STATES:
        raise AgentError("job_ended", "This job has already ended.", 409)


@verb("job.cancel", allow=PEOPLE)
def cancel(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    job_id = _job_id(payload)
    f = _show(ctx, job_id, gone_code="job_ended")
    _live(f)
    own = f["_owner"] == ctx.caller.username
    run_slurm(ctx.config, ["scancel", job_id],
              as_ident=_identity(ctx.caller, ctx.config) if own else None)
    return {}


def _hours(seconds: int) -> int | float:
    h = seconds / 3600
    return int(h) if h == int(h) else round(h, 2)


def _slurm_time(seconds: int) -> str:
    days, rest = divmod(seconds, 86400)
    return f"{days}-{rest // 3600:02d}:{rest % 3600 // 60:02d}:{rest % 60:02d}"


def _cap_hours(ctx: RequestContext) -> int:
    value = getattr(ctx.store, "setting", lambda key: None)("extension_cap_hours")
    return int(value) if isinstance(value, int | float) and value > 0 else DEFAULT_CAP_HOURS


@verb("job.extend", allow=PEOPLE)
def extend(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    job_id, hours, admin = _job_id(payload), payload.get("hours"), ctx.caller.role == "admin"
    allowed = range(1, 25) if admin else USER_HOURS
    if not isinstance(hours, int) or isinstance(hours, bool) or hours not in allowed:
        raise AgentError("bad_hours", "Extend by 1, 2 or 4 hours.", 422)
    with _job_lock(job_id):   # re-read under the lock, so two clicks can't both pass
        f = _show(ctx, job_id, gone_code="job_ended")
        _live(f)
        current = parse_slurm_duration(f.get("TimeLimit", ""))
        if current is None:
            raise AgentError("no_limit", "This job has no time limit to extend.", 409)
        part = run_slurm(ctx.config, ["scontrol", "show", "partition", f.get("Partition", ""),
                                      "--oneliner"])
        max_time = next((t[8:] for t in part.split() if t.startswith("MaxTime=")), "")
        limits = [s for s in (parse_slurm_duration(max_time),) if s is not None]
        if not admin:
            limits.append(_cap_hours(ctx) * 3600)
        total = current + hours * 3600
        if limits and total > min(limits):
            t, lim = _hours(total), _hours(min(limits))
            raise AgentError("over_cap", f"This would take the job to {t} h; the limit is {lim} h.",
                             422, {"total_h": t, "limit_h": lim})
        run_slurm(ctx.config, ["scontrol", "update", f"JobId={job_id}",
                               f"TimeLimit={_slurm_time(total)}"])
    return {"new_limit_s": total}


@verb("job.history", allow=PEOPLE)
def history(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    days = payload.get("days", 30)
    if not isinstance(days, int) or not 1 <= days <= 365:
        raise AgentError("bad_days", "Choose between 1 and 365 days.", 422)
    args = ["sacct", "-X", "-S", f"now-{days}days", "--parsable2", "--noheader",
            f"--format={SACCT_FORMAT}"]
    if payload.get("all_users") is True:
        if ctx.caller.role != "admin" or ctx.caller.acting_admin:
            raise AgentError("not_allowed", "Only admins can see everyone's history.", 403)
        out = run_slurm(ctx.config, [*args, "-a"], timeout=60)
    else:
        out = run_slurm(ctx.config, args, as_ident=_identity(ctx.caller, ctx.config), timeout=60)
    return {"jobs": [vars(q) for q in parse_sacct(out)]}


@verb("joblog.read", allow=PEOPLE)
def joblog_read(ctx: RequestContext, payload: dict[str, Any]) -> RawResponse:
    f = _show(ctx, _job_id(payload))
    path = f.get("StdErr" if payload.get("stream") == "err" else "StdOut", "")
    owner = f["_owner"]
    if not path or not in_user_job_jail(path, ctx.config.nfs_root, owner):
        raise AgentError("not_found", "This job's log isn't available.", 404)
    if owner == ctx.caller.username:
        ident, who = _identity(ctx.caller, ctx.config), ["--user", owner]
    else:   # an admin reading someone else's log
        ident, who = _ops_identity(ctx.caller, ctx.config), ["--user", owner, "--admin"]
    size = files._run(ident, files._argv(ctx.config, "stat", who, path))["size"]
    limit = min(int(payload.get("limit") or LOG_MAX), LOG_MAX)
    opts = ("--offset", str(max(0, int(payload.get("offset") or 0))), "--limit", str(limit))
    return RawResponse(content_type="text/plain; charset=utf-8", headers={"X-SD-Size": str(size)},
                       chunks=files._stream(ident, files._argv(ctx.config, "read", who, path,
                                                               opts=opts)))


def _node_names(ctx: RequestContext, nodelist: str) -> set[str]:
    """The job's node by every name the SD_SESSION line may use for it."""
    if not nodelist or nodelist == "(null)":
        return set()
    names = {nodelist}
    out = run_slurm(ctx.config, ["scontrol", "show", "node", nodelist, "--oneliner"])
    for token in out.split():
        key, _, value = token.partition("=")
        if key in ("NodeAddr", "NodeHostName") and value:
            names.add(value)
    return names


@verb("session.info", allow=PEOPLE)
def session_info(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Where an interactive job's service listens, from the SD_SESSION line in
    the owner's own output (read as the owner, or as sd-ops for an admin). The
    line is trusted only if it names the job's allocated node and a session
    port, so a job can't point the proxy at another host or service."""
    job_id = _job_id(payload)
    f = _show(ctx, job_id)
    cfg, caller, owner = ctx.config, ctx.caller, f["_owner"]
    path, folder = f.get("StdOut", ""), f.get("WorkDir", "")
    if not path or not in_user_job_jail(path, cfg.nfs_root, owner):
        raise AgentError("not_found", "This job has no session output.", 404)
    if owner == caller.username:
        ident, who = _identity(caller, cfg), ["--user", owner]
    else:   # an admin opening someone else's session
        ident, who = _ops_identity(caller, cfg), ["--user", owner, "--admin"]
        audit(cfg, actor=caller.username, acting_admin=caller.acting_admin, verb="session.info",
              target=job_id, detail={"owner": owner}, result="ok")
    out: dict[str, Any] = {"state": f.get("JobState", ""), "ready": False, "kind": None,
                           "node": None, "port": None, "token": None}
    opts = ("--offset", "0", "--limit", str(LOG_MAX))
    text = b"".join(files._stream(ident, files._argv(cfg, "read", who, path, opts=opts)))
    info = parse_session_line(text.decode(errors="replace"))
    if info is None:
        return out
    if info.node not in _node_names(ctx, f.get("NodeList", "")):
        raise AgentError("session_mismatch",
                         "This job's session doesn't point at the node it runs on.", 409)
    lo, hi = cfg.session_ports
    if not lo <= info.port <= hi:
        raise AgentError("session_port_refused",
                         f"Port {info.port} is outside the session ports ({lo}-{hi}).", 409)
    try:
        files._run(ident, files._argv(cfg, "stat", who, f"{folder}/.sd-ready"))
        marked = True
    except AgentError:
        marked = False
    return {**out, "ready": marked and out["state"] == "RUNNING", "kind": info.kind,
            "node": info.node, "port": info.port, "token": info.token}


@verb("qos.limits", allow=PEOPLE)
def qos_limits(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, int | None]:
    cfg, user = ctx.config, str(ctx.caller.username)
    assoc = run_slurm(cfg, ["sacctmgr", "-n", "-P", "show", "assoc", f"user={user}",
                            "format=qos"]).split()
    qos = assoc[0].split(",")[0] if assoc else ""
    if not qos:
        return {"max_wall_s": None, "max_pods_per_user": None}
    row = run_slurm(cfg, ["sacctmgr", "-n", "-P", "show", "qos", qos,
                          "format=MaxWall,MaxTRESPU"]).strip().split("|")
    pods = re.search(r"gres/shard=(\d+)", row[1]) if len(row) > 1 else None
    return {"max_wall_s": parse_slurm_duration(row[0]) if row[0] else None,
            "max_pods_per_user": int(pods.group(1)) if pods else None}
