"""Usage verbs: GPU-hours, CPU-hours and jobs by state from sacct (personal: as
the caller; cluster-wide: admins), and per-user disk use (du as sd-ops)."""

from __future__ import annotations

import posixpath
import threading
import time
from typing import Any

from deckagent.config import AgentConfig
from deckagent.identity import PosixIdentity, identity_for_user, ops_identity
from deckagent.protocol import AgentError, Caller, RequestContext
from deckagent.runas import run_as
from deckagent.slurmcmd import run_slurm
from deckagent.verbs import cluster, verb
from sdcore.usage import SACCT_USAGE_FORMAT, SacctRow, UsageSummary, by_user, parse_usage, summarize
from sdcore.validate import user_job_root, user_upload_root

PEOPLE = frozenset({"user", "admin"})
ADMIN = frozenset({"admin"})
DAYS = (7, 30, 90)
DISK_CACHE_S = 600
DU_TIMEOUT_S = 600

_disk_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_disk_lock = threading.Lock()


# Seams for tests: who the work runs as.
def _identity(caller: Caller, config: AgentConfig) -> PosixIdentity:
    return identity_for_user(caller, config)


def _ops_identity(caller: Caller, config: AgentConfig) -> PosixIdentity:
    return ops_identity(caller, config)


def _days(payload: dict[str, Any]) -> int:
    days = payload.get("days")
    if days not in DAYS:
        raise AgentError("bad_days", "Choose 7, 30 or 90 days.", 422)
    return int(days)


def _admin_only(ctx: RequestContext) -> None:
    if ctx.caller.role != "admin" or ctx.caller.acting_admin:
        raise AgentError("not_allowed", "Only admins can see everyone's usage.", 403)


def _rows(ctx: RequestContext, days: int, *, everyone: bool) -> list[SacctRow]:
    args = ["sacct", "-X", "-S", f"now-{days}days", "--parsable2", "--noheader",
            f"--format={SACCT_USAGE_FORMAT}"]
    if everyone:
        out = run_slurm(ctx.config, [*args, "-a"], timeout=120)
    else:
        out = run_slurm(ctx.config, args, as_ident=_identity(ctx.caller, ctx.config), timeout=120)
    return parse_usage(out)


def _numbers(s: UsageSummary) -> dict[str, Any]:
    return {"gpu_hours": round(s.gpu_hours, 2), "cpu_hours": round(s.cpu_hours, 2),
            "jobs_by_state": s.jobs_by_state}


@verb("usage.personal", allow=PEOPLE)
def personal(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    days = _days(payload)
    pods_total = int(cluster.status(ctx, {})["pods_total"])
    return {"days": days, "pods_total": pods_total,
            **_numbers(summarize(_rows(ctx, days, everyone=False), pods_total))}


@verb("usage.cluster", allow=ADMIN)
def cluster_usage(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    _admin_only(ctx)
    days = _days(payload)
    pods_total = int(cluster.status(ctx, {})["pods_total"])
    rows = _rows(ctx, days, everyone=True)
    return {"days": days, "pods_total": pods_total,
            "users": [{"user": u, **_numbers(s)} for u, s in by_user(rows, pods_total)],
            "total": _numbers(summarize(rows, pods_total))}


def _du(ctx: RequestContext, ident: PosixIdentity, tree: str) -> dict[str, int]:
    """Bytes per folder under tree; du exits non-zero on unreadable files but still prints."""
    r = run_as(ident, ["du", "-b", "--max-depth=1", tree], timeout=DU_TIMEOUT_S)
    sizes: dict[str, int] = {}
    for line in r.stdout.decode(errors="replace").splitlines():
        size, _, path = line.partition("\t")
        if size.isdigit() and posixpath.dirname(path.rstrip("/")) == tree:
            sizes[posixpath.basename(path.rstrip("/"))] = int(size)
    if r.returncode != 0 and not sizes:
        raise AgentError("du_failed", "Couldn't measure disk use.", 502)
    return sizes


@verb("admin.disk_usage", allow=ADMIN)
def disk_usage(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Bytes per user over users/<u> and jobs/<u>, measured at most every 10 minutes."""
    _admin_only(ctx)
    root = ctx.config.nfs_root
    with _disk_lock:
        hit = _disk_cache.get(root)
        if hit and time.monotonic() - hit[0] < DISK_CACHE_S:
            return hit[1]
        ident = _ops_identity(ctx.caller, ctx.config)
        users = _du(ctx, ident, posixpath.dirname(user_upload_root(root, "x")))
        jobs = _du(ctx, ident, posixpath.dirname(user_job_root(root, "x")))
        rows: list[dict[str, Any]] = [
            {"user": u, "bytes": users.get(u, 0) + jobs.get(u, 0),
             "users_bytes": users.get(u, 0), "jobs_bytes": jobs.get(u, 0)}
            for u in sorted(users.keys() | jobs.keys())]
        rows.sort(key=lambda r: (-r["bytes"], r["user"]))
        result = {"users": rows, "total_bytes": sum(r["bytes"] for r in rows)}
        _disk_cache[root] = (time.monotonic(), result)
        return result
