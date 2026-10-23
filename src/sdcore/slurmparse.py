"""Pure parsing of Slurm command output and the GPU stats file.

Ported from legacy/v1.4-tui slurmdeck/slurm.py with the subprocess calls taken
out: callers run squeue / sacct / scontrol (through deck-agent) and hand the
text in here. Nothing in this module does I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

SQUEUE_FORMAT = "%i|%j|%u|%T|%P|%M|%l|%D|%b|%L"
SACCT_FORMAT = "JobID,JobName,User,State,Elapsed,Start,End,AllocTRES,ExitCode"

# Job states that count as history. Running and pending jobs come from squeue.
# Filtered here rather than with `sacct --state`, which drops completed jobs
# unless the end-time window matches.
SACCT_TERMINAL_STATES = frozenset({
    "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT",
    "OUT_OF_MEMORY", "NODE_FAIL", "PREEMPTED", "BOOT_FAIL", "DEADLINE",
})


@dataclass
class NodeStats:
    # Slurm allocation data (from scontrol)
    state: str
    cpu_load: float
    cpu_total: int
    cpu_alloc: int
    mem_total_mb: int
    mem_alloc_mb: int
    gpu_total: int          # physical GPUs on the node
    gpu_alloc: int          # physical GPUs with at least one shard in use
    # The GPU is split into schedulable shards (gres/shard, one per pod) so
    # several jobs can share it; these gate whether a new job can start.
    shard_total: int = 0
    shard_alloc: int = 0
    # Actual utilisation (from nvidia-smi via the stats writer)
    gpu_util: int = 0
    gpu_mem_used_mb: int = 0
    gpu_mem_total_mb: int = 0
    gpu_temp: int = 0
    gpu_power_w: float = 0.0
    cpu_util: int = 0
    cpu_load5: float = 0.0
    mem_used_mb: int = 0
    live_stats: bool = False   # True when the fields above came from fresh stats


@dataclass
class QueueEntry:
    job_id: str
    name: str
    state: str
    partition: str
    time_used: str
    nodes: int
    user: str = "?"
    time_limit: str = "N/A"
    pods: int = 0
    time_left_s: int | None = None


def _tres_value(tres: str, key: str) -> int:
    """Pull an integer TRES count (e.g. gres/shard=3) out of a TRES string."""
    for item in tres.split(","):
        item = item.strip()
        if item.startswith(key + "="):
            try:
                return int(item[len(key) + 1:])
            except ValueError:
                return 0
    return 0


def _mem_mb(text: str) -> int:
    """A Slurm memory size (`512M`, `14G`, `1T`, plain MB) in MB; 0 if unreadable."""
    scale = {"M": 1, "G": 1024, "T": 1024 * 1024}
    try:
        if text and text[-1] in scale:
            return int(float(text[:-1]) * scale[text[-1]])
        return int(text)
    except ValueError:
        return 0


def _gres_count(item: str) -> int:
    """The count in one GRES item: `gpu:2`, `gpu:rtx:1(S:0)`, `gres/shard:2`."""
    try:
        return int(item.split("(")[0].split(":")[-1])
    except ValueError:
        return 1


_DURATION = re.compile(r"^(?:(\d+)-)?(\d+)(?::(\d+))?(?::(\d+))?$")


def parse_slurm_duration(text: str) -> int | None:
    """Seconds in a Slurm time string, or None when it isn't a duration.

    Accepts `MM`, `MM:SS`, `HH:MM:SS`, `D-HH`, `D-HH:MM` and `D-HH:MM:SS`.
    `UNLIMITED`, `INVALID`, `NOT_SET` and anything else unreadable give None.
    """
    m = _DURATION.match(text.strip())
    if not m:
        return None
    days, a, b, c = m.groups()
    parts = [int(a)] + [int(x) for x in (b, c) if x is not None]
    if days is not None:
        # With a day count the fields are hours[:minutes[:seconds]].
        h, mi, s = (parts + [0, 0])[:3]
        return int(days) * 86400 + h * 3600 + mi * 60 + s
    if len(parts) == 1:
        return parts[0] * 60
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def _pods_from_gres(text: str) -> int:
    """Shards (pods) requested in squeue's %b: `gres/shard:2`, `shard:2`, `N/A`."""
    total = 0
    for item in text.split(","):
        item = item.strip()
        if "shard" in item:
            total += _gres_count(item)
    return total


def parse_squeue(text: str) -> list[QueueEntry]:
    """Rows of `squeue --noheader --format=SQUEUE_FORMAT`."""
    entries = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 10:
            continue
        entries.append(QueueEntry(
            job_id=parts[0], name=parts[1], user=parts[2],
            state=parts[3], partition=parts[4],
            time_used=parts[5], time_limit=parts[6],
            nodes=int(parts[7]) if parts[7].isdigit() else 1,
            pods=_pods_from_gres(parts[8]),
            time_left_s=parse_slurm_duration(parts[9]),
        ))
    return entries


def parse_sacct(text: str) -> list[QueueEntry]:
    """Finished jobs from `sacct --noheader --parsable2 -X --format=SACCT_FORMAT`.

    Step lines (`123.batch`) are dropped, `CANCELLED by 1234` becomes
    `CANCELLED`, and only terminal states are kept. Newest first, as sacct
    lists oldest first.
    """
    entries = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 8 or "." in parts[0]:
            continue
        words = parts[3].split()
        state = words[0] if words else ""
        if state not in SACCT_TERMINAL_STATES:
            continue
        entries.append(QueueEntry(
            job_id=parts[0],
            name=parts[1] or parts[0],
            user=parts[2] or "?",
            state=state,
            partition="",
            time_used=parts[4] or "-",
            nodes=1,
            pods=_tres_value(parts[7], "gres/shard"),
        ))
    entries.reverse()
    return entries


def parse_scontrol_node(text: str) -> NodeStats | None:
    """Allocation data from `scontrol show node <name> --oneliner`.

    None when the output doesn't describe a node. Live GPU fields stay at zero;
    merge them in with merge_gpu_stats.
    """
    d: dict[str, str] = {}
    for token in text.split():
        if "=" in token:
            k, _, v = token.partition("=")
            d[k] = v
    if "NodeName" not in d:
        return None

    def _i(key: str) -> int:
        try:
            return int(d.get(key, 0))
        except ValueError:
            return 0

    def _f(key: str) -> float:
        try:
            return float(d.get(key, 0.0))
        except ValueError:
            return 0.0

    gpu_total = 0
    shard_total = 0
    for item in d.get("Gres", "").split(","):
        item = item.strip()
        if item.startswith("gpu:"):
            gpu_total += _gres_count(item)
        elif item.startswith("shard:"):
            shard_total += _gres_count(item)

    alloc = d.get("AllocTRES", "")
    # Shard allocation is reported in AllocTRES. Without shards configured
    # (no GPU sharing at this site) count whole GPUs instead.
    shard_alloc = _tres_value(alloc, "gres/shard")
    if shard_total:
        gpu_alloc = 1 if shard_alloc > 0 else 0
    else:
        gpu_alloc = _tres_value(alloc, "gres/gpu")
    mem_alloc_mb = 0
    for item in alloc.split(","):
        if item.startswith("mem="):
            mem_alloc_mb = _mem_mb(item[4:])

    return NodeStats(
        state=d.get("State", "?").split("+")[0],
        cpu_load=_f("CPULoad"),
        cpu_total=_i("CPUTot"),
        cpu_alloc=_i("CPUAlloc"),
        mem_total_mb=_i("RealMemory"),
        mem_alloc_mb=mem_alloc_mb,
        gpu_total=gpu_total,
        gpu_alloc=gpu_alloc,
        shard_total=shard_total,
        shard_alloc=shard_alloc,
    )


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def merge_gpu_stats(stats: NodeStats, gpu_json: dict[str, Any] | None, now: float,
                    max_age_s: int = 10, mtime: float | None = None) -> NodeStats:
    """A copy of stats with live utilisation from the GPU stats file.

    The stats writer rewrites the file every few seconds; when its `mtime` is
    more than max_age_s before `now` the data is stale and stats come back
    unchanged, with live_stats False. Pass mtime=None for data read directly
    rather than from the file.
    """
    if not gpu_json:
        return replace(stats)
    if mtime is not None and now - mtime > max_age_s:
        return replace(stats)
    return replace(
        stats,
        gpu_util=_as_int(gpu_json.get("gpu_util")),
        gpu_mem_used_mb=_as_int(gpu_json.get("gpu_mem_used_mb")),
        gpu_mem_total_mb=_as_int(gpu_json.get("gpu_mem_total_mb")),
        gpu_temp=_as_int(gpu_json.get("gpu_temp")),
        gpu_power_w=_as_float(gpu_json.get("gpu_power_w")),
        cpu_util=_as_int(gpu_json.get("cpu_util")),
        cpu_load5=_as_float(gpu_json.get("cpu_load5")),
        mem_used_mb=_as_int(gpu_json.get("mem_used_mb")),
        live_stats=True,
    )
