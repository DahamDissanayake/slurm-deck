"""Usage totals from sacct: GPU-hours, CPU-hours and jobs by state, from each
job's elapsed time and allocation (no sreport needed). One pod is one
gres/shard, 1/pods_total of the GPU. Ported from legacy/v1.4-tui
slurmdeck/accounting.py; no I/O: callers hand the sacct text in."""

from __future__ import annotations

from dataclasses import dataclass, field

from sdcore.slurmparse import _tres_value

# `sacct -X --parsable2 --noheader --format=SACCT_USAGE_FORMAT`
SACCT_USAGE_FORMAT = "User,State,ElapsedRaw,AllocTRES"


@dataclass(frozen=True)
class SacctRow:
    user: str
    state: str          # the first word: "CANCELLED by 1001" is CANCELLED
    elapsed_s: int
    cpus: int           # at least 1: a job always uses a CPU
    pods: int           # gres/shard allocated; 0 for a CPU-only job


@dataclass
class UsageSummary:
    gpu_hours: float = 0.0
    cpu_hours: float = 0.0
    jobs_by_state: dict[str, int] = field(default_factory=dict)


def parse_usage(text: str) -> list[SacctRow]:
    """Rows of sacct in SACCT_USAGE_FORMAT. Lines without a user or with an
    unreadable elapsed time are skipped."""
    rows = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 4 or not parts[0].strip():
            continue
        try:
            elapsed = int(parts[2])
        except ValueError:
            continue
        state = parts[1].split()[0] if parts[1].split() else "UNKNOWN"
        rows.append(SacctRow(parts[0].strip(), state, elapsed,
                             max(_tres_value(parts[3], "cpu"), 1),
                             _tres_value(parts[3], "gres/shard")))
    return rows


def summarize(rows: list[SacctRow], pods_total: int) -> UsageSummary:
    """Totals over rows. Without a known pod count there are no GPU-hours."""
    out = UsageSummary()
    for r in rows:
        hours = r.elapsed_s / 3600
        out.cpu_hours += hours * r.cpus
        if pods_total > 0:
            out.gpu_hours += hours * r.pods / pods_total
        out.jobs_by_state[r.state] = out.jobs_by_state.get(r.state, 0) + 1
    return out


def by_user(rows: list[SacctRow], pods_total: int) -> list[tuple[str, UsageSummary]]:
    """One summary per user, the heaviest GPU users first."""
    groups: dict[str, list[SacctRow]] = {}
    for r in rows:
        groups.setdefault(r.user, []).append(r)
    out = [(user, summarize(rs, pods_total)) for user, rs in groups.items()]
    return sorted(out, key=lambda x: (-x[1].gpu_hours, -x[1].cpu_hours, x[0]))
