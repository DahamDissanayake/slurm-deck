"""Cluster verbs: node and pod status, the queue, free disk and time left."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from typing import Any

from deckagent.protocol import RequestContext
from deckagent.slurmcmd import run_slurm
from deckagent.verbs import verb
from sdcore.slurmparse import (
    SQUEUE_FORMAT,
    merge_gpu_stats,
    parse_scontrol_node,
    parse_slurm_duration,
    parse_squeue,
)

ALL = frozenset({"user", "admin", "worker"})


def _stats_file(path: str) -> tuple[dict[str, Any] | None, float | None]:
    try:
        with open(path) as f:
            return json.load(f), os.fstat(f.fileno()).st_mtime
    except (OSError, ValueError):
        return None, None


@verb("cluster.status", allow=ALL)
def status(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    cfg = ctx.config
    node = parse_scontrol_node(run_slurm(cfg, ["scontrol", "show", "node", cfg.compute_node,
                                               "--oneliner"])) if cfg.compute_node else None
    if node is not None:
        gpu_json, mtime = _stats_file(cfg.stats_file)
        node = merge_gpu_stats(node, gpu_json, time.time(), mtime=mtime)
    part = run_slurm(cfg, ["scontrol", "show", "partition", cfg.partition, "--oneliner"])
    max_time = next((t.partition("=")[2] for t in part.split() if t.startswith("MaxTime=")), "")
    return {"node": asdict(node) if node else None,
            "pods_total": node.shard_total if node else 0,
            "pods_used": node.shard_alloc if node else 0,
            "partition_max_s": parse_slurm_duration(max_time)}


def _queue(ctx: RequestContext, *extra: str) -> list[Any]:
    return parse_squeue(run_slurm(ctx.config, ["squeue", "--noheader",
                                               f"--format={SQUEUE_FORMAT}", *extra]))


@verb("cluster.queue", allow=ALL)
def queue(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Everyone sees every job's owner, state and pods; only admins and the
    job's owner see its name."""
    caller = ctx.caller
    jobs = []
    for q in _queue(ctx):
        job = {"job_id": q.job_id, "user": q.user, "state": q.state, "pods": q.pods,
               "time_used": q.time_used, "time_limit": q.time_limit,
               "time_left_s": q.time_left_s}
        if caller.role == "admin" or (caller.username and caller.username == q.user):
            job["name"] = q.name
        jobs.append(job)
    return {"jobs": jobs}


@verb("cluster.disk_free", allow=ALL)
def disk_free(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, int]:
    st = os.statvfs(ctx.config.nfs_root)
    total = st.f_blocks * st.f_frsize
    return {"total_bytes": total, "used_bytes": total - st.f_bfree * st.f_frsize,
            "free_bytes": st.f_bavail * st.f_frsize}


@verb("job.time_left_all", allow=frozenset({"worker"}))
def time_left_all(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jobs": [{"job_id": q.job_id, "user": q.user, "time_left_s": q.time_left_s,
                      "state": q.state} for q in _queue(ctx, "--states=RUNNING")
                     if q.state == "RUNNING"]}
