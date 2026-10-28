"""Launch specs: what the New job flow edits before it becomes a JobSpec.

Ported from legacy/v1.4-tui slurmdeck/launchspec.py. Intents are now
`notebook`, `batch`, `terminal` (replaces the TUI's shell) and `smoke`. Every
intent but smoke defaults to the site's default time limit (8 h); smoke is
fixed at 1 pod, 4 CPU, 8 GB, 30 minutes. The TUI-only
wording helpers and the recent-scripts scan were not ported.
"""

from __future__ import annotations

from dataclasses import dataclass

from sdcore.pods import pod_count_known, resources_for
from sdcore.sbatch import SMOKE_CPUS, SMOKE_MEM_GB, SMOKE_TIME, JobSpec
from sdcore.slurmparse import NodeStats

DEFAULT_TIME = "08:00:00"


@dataclass
class LaunchSpec:
    intent: str
    script: str = ""
    env_kind: str = "prebuilt"      # prebuilt | conda | venv | container | none
    conda_env: str = ""
    venv_path: str = ""
    container_image: str = ""
    gpu_shards: int = 1             # the pod count: one shard is one pod
    cpus: int = 8
    mem_gb: int = 14
    time_limit: str = DEFAULT_TIME
    data_path: str = ""
    model_path: str = ""
    args: str = ""
    array: str = ""
    dependency: str = ""
    mail: bool = True
    requirements: str = ""
    packages: str = ""
    port: int = 8888


def apply_pods(ls: LaunchSpec, k: int, stats: NodeStats | None) -> None:
    """Request k pods, sizing cpus/mem_gb from the node's live totals.

    When the pod count is unknown (no stats, or zero shards reported) cpus and
    mem_gb are left as they are: pods.pod_resources would answer 1 CPU / 1 GB
    there, and writing that in would shrink every job to 1/1. gpu_shards still
    records the request, floored at 1.
    """
    if not pod_count_known(stats):
        ls.gpu_shards = max(1, k)
        return
    ls.cpus, ls.mem_gb, ls.gpu_shards = resources_for(k, stats)


def default_spec(intent: str, stats: NodeStats | None,
                 default_time: str = DEFAULT_TIME) -> LaunchSpec:
    """A fresh one-pod LaunchSpec for intent, sized from live stats when given."""
    ls = LaunchSpec(intent=intent)
    if intent == "smoke":
        # The smoke test is a fixed small job, the same size on any cluster.
        ls.cpus, ls.mem_gb, ls.time_limit = SMOKE_CPUS, SMOKE_MEM_GB, SMOKE_TIME
        return ls
    apply_pods(ls, 1, stats)
    ls.time_limit = default_time
    return ls


_TASK_TYPE = {"notebook": "notebook", "terminal": "terminal", "smoke": "smoke"}


def to_job_spec(ls: LaunchSpec, *, user: str, partition: str, job_name: str,
                run_command: str) -> JobSpec:
    return JobSpec(
        job_name=job_name, partition=partition,
        gpu_shards=ls.gpu_shards, cpus=ls.cpus, mem_gb=ls.mem_gb,
        time_limit=ls.time_limit, run_command=run_command, user=user,
        model_path=ls.model_path, conda_env=ls.conda_env, venv_path=ls.venv_path,
        task_type=_TASK_TYPE.get(ls.intent, "custom"),
        container_image=ls.container_image, array=ls.array,
        dependency=ls.dependency, data_path=ls.data_path,
    )


# A template stores the JobSpec task_type, not the intent. "interactive" was a
# TUI shell allocation; loaded as batch it would become a job that runs nothing.
_TEMPLATE_INTENT = {"notebook": "notebook", "interactive": "terminal", "terminal": "terminal"}


def from_template(tdata: dict, stats: NodeStats | None) -> LaunchSpec:
    """A LaunchSpec from a stored template. Fields the template lacks keep the
    default_spec sizing (live when stats are given), never 1 CPU / 1 GB."""
    ls = default_spec(_TEMPLATE_INTENT.get(tdata.get("task_type", ""), "batch"), stats)
    for f_ in ("conda_env", "venv_path", "container_image", "data_path",
               "model_path", "array", "dependency", "time_limit"):
        if tdata.get(f_):
            setattr(ls, f_, tdata[f_])
    for f_ in ("gpu_shards", "cpus", "mem_gb"):
        if tdata.get(f_) is not None:
            setattr(ls, f_, int(tdata[f_]))
    if tdata.get("extra_args"):
        ls.args = tdata["extra_args"]
    return ls


def from_rerun(parsed: dict, script: str, stats: NodeStats | None) -> LaunchSpec:
    """Rebuild a launch from a previous job's parsed sbatch.

    Re-run has to mean re-run: the environment, data path and arguments are
    carried as well as the sizing. stats only backs fields the old job didn't
    record.
    """
    ls = default_spec("batch", stats)
    ls.script = script
    for f_ in ("gpu_shards", "cpus", "mem_gb"):
        if parsed.get(f_) is not None:
            setattr(ls, f_, int(parsed[f_]))
    for f_ in ("time_limit", "array", "dependency",
               "conda_env", "venv_path", "container_image", "data_path"):
        if parsed.get(f_):
            setattr(ls, f_, parsed[f_])
    if parsed.get("extra_args"):
        ls.args = parsed["extra_args"]
    if ls.container_image:
        ls.env_kind = "container"
    elif ls.conda_env:
        ls.env_kind = "conda"
    elif ls.venv_path:
        ls.env_kind = "venv"
    return ls
