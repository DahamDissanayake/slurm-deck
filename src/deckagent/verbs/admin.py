"""Admin cluster control: QoS limits, node drain and resume, the pod grid and
resize, publishing into the shared areas, and service health. Admins only, and
not while viewing as a user. Slurm changes run as root; copies into the shared
areas run as sd-ops. Every change is written to the agent's audit log."""

from __future__ import annotations

import json
import os
import posixpath
import re
import subprocess
from typing import Any

from deckagent.audit import audit
from deckagent.gpuhost import GpuHost
from deckagent.identity import PosixIdentity, ops_identity
from deckagent.protocol import AgentError, RequestContext
from deckagent.runas import run_as
from deckagent.slurmcmd import run_slurm
from deckagent.verbs import cluster, verb
from sdcore.pods import fits_new_pod_count
from sdcore.slurmparse import _tres_value, parse_slurm_duration

ADMIN = frozenset({"admin"})
QOS_NAME = re.compile(r"[A-Za-z0-9_.-]{1,40}")
QOS_TRES = {"max_pods_per_user": "gres/shard", "max_gpus_per_user": "gres/gpu"}
AREAS = ("datasets", "models", "envs", "data", "images", "scripts")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
LOGIN_UNITS = ("slurmctld", "slurmdbd", "mariadb", "munge", "deck-agent", "docker")
EXISTS = 17       # the publish script's exit code for "that name is taken"
BAD_SOURCE = 18   # ... for "the source is a link, or leaves the user's folder"
# $1 source, $2 destination, $3 "1" to replace, $4 <nfs_root>/users. Run as
# sd-ops, which can read every user's folder, so the source is resolved first:
# it must be exactly the path asked for (no symlink anywhere below users/, the
# share root itself may be one) and inside one user's folder. The copy is made
# from the resolved path and checked again afterwards, so a link swapped in
# while copying is caught. Copies beside the target first, so a failed copy
# never leaves a half-replaced asset. The copy goes through tar with setuid and
# setgid stripped: a published file must not run as sd-ops, and deck-agent's
# RestrictSUIDSGID refuses any mkdir or chmod that would keep those bits.
PUBLISH = ('set -eo pipefail; root=$(realpath -e -- "$4") || exit 18; '
           'real=$(realpath -e -- "$1") || exit 18; '
           'case "$1" in "$4"/?*) ;; *) exit 18;; esac; '
           '[ "$real" = "$root/${1#"$4"/}" ] || exit 18; '
           'case "$real" in "$root"/?*) ;; *) exit 18;; esac; '
           'if [ -e "$2" ] && [ "$3" != 1 ]; then exit 17; fi; rm -rf -- "$2.new" "$2.tmp"; '
           'mkdir -- "$2.tmp"; base=$(basename -- "$real"); '
           'tar -C "$(dirname -- "$real")" --mode=ug-s -cf - -- "$base" | tar -C "$2.tmp" -xf -; '
           'mv -- "$2.tmp/$base" "$2.new"; rmdir -- "$2.tmp"; '
           'if [ "$(realpath -e -- "$1")" != "$real" ]; then rm -rf -- "$2.new"; exit 18; fi; '
           'rm -rf -- "$2"; mv -- "$2.new" "$2"')


def _ops_identity(ctx: RequestContext) -> PosixIdentity:   # a seam for tests
    return ops_identity(ctx.caller, ctx.config)


def _admin(ctx: RequestContext) -> None:
    if ctx.caller.role != "admin" or ctx.caller.acting_admin:
        raise AgentError("not_allowed", "Only admins can do that.", 403)


def _audit(ctx: RequestContext, verb_name: str, target: str, detail: dict[str, Any]) -> None:
    audit(ctx.config, actor=ctx.caller.username, acting_admin=ctx.caller.acting_admin,
          verb=verb_name, target=target, detail=detail, result="ok")


def _bad(code: str, message: str) -> AgentError:
    return AgentError(code, message, 422)


# --- QoS ---------------------------------------------------------------------

def _qos_rows(ctx: RequestContext) -> list[dict[str, Any]]:
    out = run_slurm(ctx.config, ["sacctmgr", "-n", "--parsable2", "show", "qos",
                                 "format=Name,MaxWall,MaxTRESPerUser,Priority"])
    rows = []
    for line in out.splitlines():
        p = line.split("|")
        if len(p) >= 4 and p[0].strip():
            rows.append({"name": p[0].strip(), "max_wall_s": parse_slurm_duration(p[1]),
                         "max_pods_per_user": _tres_value(p[2], "gres/shard") or None,
                         "max_gpus_per_user": _tres_value(p[2], "gres/gpu") or None,
                         "priority": int(p[3]) if p[3].strip().isdigit() else 0})
    return rows


def _int(value: Any, what: str, low: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise _bad("bad_value", f"{what} must be a whole number of at least {low}.")
    return value


@verb("admin.qos_list", allow=ADMIN)
def qos_list(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    _admin(ctx)
    return {"qos": _qos_rows(ctx)}


@verb("admin.qos_set", allow=ADMIN)
def qos_set(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Change one limit of a QOS. MaxTRESPerUser holds several TRES at once, so
    only the one key is changed: the others are read back and written again."""
    _admin(ctx)
    name, field, value = str(payload.get("name", "")), payload.get("field"), payload.get("value")
    if not QOS_NAME.fullmatch(name) or name not in {r["name"] for r in _qos_rows(ctx)}:
        raise AgentError("not_found", "There is no such QOS.", 404)
    if field in QOS_TRES:
        out = run_slurm(ctx.config, ["sacctmgr", "-n", "--parsable2", "show", "qos", name,
                                     "format=MaxTRESPerUser"])
        tres = dict(i.partition("=")[::2] for i in (out.strip().splitlines() or [""])[0].split(",")
                    if "=" in i)
        if value is None:
            tres.pop(QOS_TRES[str(field)], None)
        else:
            tres[QOS_TRES[str(field)]] = str(_int(value, "The limit", 1))
        setting = "MaxTRESPerUser=" + (",".join(f"{k}={v}" for k, v in tres.items()) or "-1")
    elif field == "max_wall":
        if value is None:
            setting = "MaxWall=-1"
        else:
            days, rest = divmod(_int(value, "The time limit", 60), 86400)
            setting = f"MaxWall={days}-{rest // 3600:02d}:{rest % 3600 // 60:02d}:{rest % 60:02d}"
    elif field == "priority":
        setting = f"Priority={_int(value, 'The priority')}"
    else:
        raise _bad("bad_field", "That limit can't be changed.")
    run_slurm(ctx.config, ["sacctmgr", "-i", "modify", "qos", name, "set", setting], timeout=20)
    _audit(ctx, "admin.qos_set", name, {"set": setting})
    return {"qos": _qos_rows(ctx)}


# --- Node: drain, resume ----------------------------------------------------------

def _node(ctx: RequestContext, payload: dict[str, Any]) -> str:
    node = payload.get("node") or ctx.config.compute_node   # there is one node: the default
    if not node or node != ctx.config.compute_node:
        raise _bad("bad_node", "That isn't a node of this cluster.")
    return str(node)


def _node_jobs(ctx: RequestContext, node: str) -> list[dict[str, str]]:
    out = run_slurm(ctx.config, ["squeue", "--noheader", "--format=%i|%u|%j|%T",
                                 f"--nodelist={node}"])
    return [dict(zip(("job_id", "user", "name", "state"), (x.strip() for x in line.split("|")),
                     strict=True)) for line in out.splitlines() if line.count("|") == 3]


@verb("admin.node_jobs", allow=ADMIN)
def node_jobs(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    _admin(ctx)
    return {"jobs": _node_jobs(ctx, _node(ctx, payload))}


@verb("admin.drain", allow=ADMIN)
def drain(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    _admin(ctx)
    node, reason = _node(ctx, payload), str(payload.get("reason") or "").strip()
    if not reason or len(reason) > 200:
        raise _bad("reason_required", "Give a reason of up to 200 characters.")
    cancelled = []
    if payload.get("cancel_running") is True:
        for job in _node_jobs(ctx, node):
            run_slurm(ctx.config, ["scancel", job["job_id"]])
            cancelled.append(job["job_id"])
    run_slurm(ctx.config, ["scontrol", "update", f"nodename={node}", "state=drain",
                           f"reason={reason}"], timeout=20)
    _audit(ctx, "admin.drain", node, {"reason": reason, "cancelled": cancelled})
    return {"cancelled": cancelled}


@verb("admin.resume", allow=ADMIN)
def resume(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    _admin(ctx)
    node = _node(ctx, payload)
    run_slurm(ctx.config, ["scontrol", "update", f"nodename={node}", "state=resume"], timeout=20)
    _audit(ctx, "admin.resume", node, {})
    return {}


# --- Pods -------------------------------------------------------------------------

@verb("admin.pods", allow=ADMIN)
def pods(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Which job holds each pod (oldest job first; Slurm counts shards, it does
    not track which one), and whether each pod count from 1 to 8 would fit."""
    _admin(ctx)
    stats = cluster.node_stats(ctx)
    total = stats.shard_total if stats else 0
    jobs = sorted((q for q in cluster._queue(ctx, "--states=RUNNING") if q.pods > 0),
                  key=lambda q: int(re.match(r"\d+", q.job_id).group()))  # type: ignore[union-attr]
    cells: list[dict[str, Any]] = [{"pod": i, "job_id": None, "user": None} for i in range(total)]
    taken = 0
    for q in jobs:
        for _ in range(q.pods):
            if taken < total:
                cells[taken].update(job_id=q.job_id, user=q.user)
                taken += 1
    fits = [{"n": n, "ok": ok, "message": msg} for n in range(1, 9) if stats
            for ok, msg in [fits_new_pod_count(n, stats)]]
    return {"pods_total": total, "pods": cells, "fits": fits}


@verb("admin.pods_resize", allow=ADMIN)
def pods_resize(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Resize only with an empty queue and a pod count that fits; the script
    then rewrites the config on both nodes. Its output is passed through."""
    _admin(ctx)
    n = _int(payload.get("n"), "The pod count", 1)
    busy = run_slurm(ctx.config, ["squeue", "--noheader"]).strip().splitlines()   # fails closed
    if busy:
        raise AgentError("queue_busy", f"{len(busy)} job(s) are still active, so the pods "
                         "can't be resized.", 409)
    stats = cluster.node_stats(ctx)
    if stats is None:
        raise AgentError("no_stats", "The node's numbers can't be read, so the pods can't "
                         "be resized.", 409)
    fits, message = fits_new_pod_count(n, stats)
    if not fits:
        raise AgentError("pods_do_not_fit", message, 409)
    try:
        r = subprocess.run(["runuser", "-u", "slurmadmin", "--", ctx.config.resize_script, str(n)],
                           capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AgentError("resize_failed", f"The resize script could not run: {e}", 502) from None
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-40:])
    _audit(ctx, "admin.pods_resize", str(n), {"exit_code": r.returncode})
    if r.returncode != 0:
        raise AgentError("resize_failed", tail or "The resize failed.", 502,
                         {"exit_code": r.returncode})
    return {"output": tail}


# --- Shared areas -------------------------------------------------------------------

def _shared(ctx: RequestContext, area: Any, name: Any) -> str:
    if area not in AREAS or not isinstance(name, str) or not NAME.fullmatch(name):
        raise _bad("bad_asset", "Choose one of the shared areas and a plain name.")
    return posixpath.join(ctx.config.nfs_root.rstrip("/"), str(area), name)


@verb("admin.publish_shared", allow=ADMIN)
def publish_shared(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    _admin(ctx)
    dest = _shared(ctx, payload.get("area"), payload.get("name"))
    users = ctx.config.nfs_root.rstrip("/") + "/users"
    src = posixpath.normpath(str(payload.get("src", "")))
    if not src.startswith(users + "/"):
        raise _bad("bad_source", "Only something from a user's own area can be published.")
    r = run_as(_ops_identity(ctx), ["bash", "-c", PUBLISH, "bash", src, dest,
                                    "1" if payload.get("replace") is True else "0", users],
               timeout=3600)
    if r.returncode == EXISTS:
        raise AgentError("exists", "A file with that name already exists there.", 409)
    if r.returncode == BAD_SOURCE:
        raise _bad("bad_source", "That source is missing, is a link, or goes through a link "
                   "out of the user's folder.")
    if r.returncode != 0:
        raise AgentError("publish_failed", r.stderr.decode(errors="replace").strip()[-300:]
                         or "The copy failed.", 502)
    _audit(ctx, "admin.publish_shared", dest, {"src": src})
    return {"path": dest}


@verb("admin.unpublish_shared", allow=ADMIN)
def unpublish_shared(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    _admin(ctx)
    dest = _shared(ctx, payload.get("area"), payload.get("name"))
    r = run_as(_ops_identity(ctx), ["rm", "-rf", "--", dest], timeout=600)
    if r.returncode != 0:
        raise AgentError("unpublish_failed", r.stderr.decode(errors="replace").strip()[-300:],
                         502)
    _audit(ctx, "admin.unpublish_shared", dest, {})
    return {}


# --- deck-agent's own log ---------------------------------------------------------

AUDIT_TAIL_BYTES = 4 * 1024 * 1024   # only the end of the log is read
AUDIT_TAIL_MAX = 500


@verb("admin.audit_tail", allow=ADMIN)
def audit_tail(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """The newest entries of the agent's JSONL audit log, newest first, optionally only
    those after since_ts (an ISO time)."""
    _admin(ctx)
    limit = min(_int(payload.get("limit", 100), "The limit", 1), AUDIT_TAIL_MAX)
    since = str(payload.get("since_ts") or "")
    try:
        with open(ctx.config.audit_log, "rb") as f:
            f.seek(max(os.fstat(f.fileno()).st_size - AUDIT_TAIL_BYTES, 0))
            lines = f.read().decode(errors="replace").splitlines()
    except OSError:
        lines = []
    events: list[Any] = []
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue   # the first line of a tail read may be cut in half
        if (since and str(event.get("ts", "")) <= since) or len(events) >= limit:
            break
        events.append(event)
    return {"events": events}


# --- Service health ---------------------------------------------------------------

def _unit(name: str) -> str:
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True,
                           timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    word = r.stdout.strip()
    return word if word in ("active", "inactive", "failed") else "unknown"


@verb("admin.service_status", allow=ADMIN)
def service_status(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Each unit on the login node, and on the GPU host through its helper."""
    _admin(ctx)
    gpu: dict[str, str] = {}
    gpu_error = ""
    try:
        gpu = GpuHost(ctx.config).service_status()
    except AgentError as e:
        gpu_error = e.message
    return {"login": {u: _unit(u) for u in LOGIN_UNITS}, "gpu": gpu, "gpu_error": gpu_error}
