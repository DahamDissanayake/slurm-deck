"""Input validation for job requests, submitted scripts and file paths.

Ported from legacy/v1.4-tui slurmdeck/validate.py. The legacy module read its
limits from env vars at import and called the daemon and scontrol from inside
the checks; here every limit, the shared root, the user's registered email and
the live node stats are passed in. The only I/O is resolving paths (symlinks
included) for the jail checks.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Protocol

from sdcore.names import valid_username


class _HasShards(Protocol):
    shard_total: int


def clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


_TIME_RE = re.compile(r"^(\d+):([0-5]\d):([0-5]\d)$")


def parse_hms(value: str) -> int | None:
    """Seconds in an `HH:MM:SS` time limit (hours may exceed 24), else None."""
    m = _TIME_RE.match(str(value).strip())
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def clean_time_limit(value: str, max_hours: int) -> str | None:
    """A normalised `HH:MM:SS` limit, capped at max_hours; None if unreadable."""
    seconds = parse_hms(value)
    if seconds is None:
        return None
    if seconds > max_hours * 3600:
        return f"{max_hours:02d}:00:00"
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


_JOB_NAME_RE = re.compile(r"[^A-Za-z0-9._\-]")


def clean_job_name(value: str) -> str:
    return _JOB_NAME_RE.sub("", str(value))[:64]


_MODULE_TOKEN_RE = re.compile(r"[A-Za-z0-9_.+\-/]+")


def clean_modules(value: str) -> list[str]:
    return _MODULE_TOKEN_RE.findall(str(value))[:20]


_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def clean_run_command(value: str) -> str:
    return _CONTROL_RE.sub(" ", str(value))[:1000]


_ARRAY_RE = re.compile(r"^\d+(-\d+)?(:\d+)?(,\d+(-\d+)?(:\d+)?)*(%\d+)?$")


def clean_array_spec(value: str) -> str | None:
    """A Slurm --array spec like `0-9`, `1-100%4` or `1,3,5`; None if invalid or empty."""
    v = str(value).strip()
    if not v:
        return None
    return v if _ARRAY_RE.match(v) else None


_DEP_RE = re.compile(
    r"^(after|afterok|afterany|afternotok|aftercorr|singleton)"
    r"(:\d+(_\d+)?)*$"
)


def clean_dependency(value: str) -> str | None:
    """A Slurm --dependency like `afterok:12345`; None if invalid or empty."""
    v = str(value).strip()
    if not v or v.endswith(":"):
        return None
    if not _DEP_RE.match(v):
        return None
    # Every type but singleton needs at least one job id.
    return v if v == "singleton" or ":" in v else None


# ── Per-user file-access jails ───────────────────────────────────────────────
#
# A username is a path segment here, so anything that isn't a valid username
# (`.`, `..`, `a/b`, `root`, ...) is refused before a path is built from it.


def _checked(username: str) -> str:
    if not valid_username(username):
        raise ValueError(f"invalid username: {username!r}")
    return username


def user_browse_roots(nfs_root: str, username: str) -> list[str]:
    """Directories a user may navigate in the file manager: their own area
    plus the shared read-only assets."""
    base = Path(nfs_root).resolve()
    return [
        str(base / "users" / _checked(username)),
        str(base / "models"),
        str(base / "envs"),
        str(base / "data"),
        str(base / "datasets"),
    ]


def user_upload_root(nfs_root: str, username: str) -> str:
    """The only directory a user may write into through upload or the file manager."""
    return str(Path(nfs_root).resolve() / "users" / _checked(username))


def user_job_root(nfs_root: str, username: str, jobs_subdir: str = "jobs") -> str:
    """The user's job workspace, where generated scripts, per-job working
    directories and job output go."""
    return str(Path(nfs_root).resolve() / jobs_subdir / _checked(username))


def _inside(path: str, roots: list[str]) -> bool:
    try:
        real = str(Path(path).resolve())
    except (OSError, ValueError):
        return False
    return any(real == root or real.startswith(root + os.sep) for root in roots)


def in_user_browse_jail(path: str, nfs_root: str, username: str) -> bool:
    """True when path (after resolving symlinks) is inside the user's
    browsable area. Other users' areas and job folders never are."""
    if not valid_username(username):
        return False
    return _inside(path, user_browse_roots(nfs_root, username))


def in_user_upload_jail(path: str, nfs_root: str, username: str) -> bool:
    """True when path is inside the user's own `users/<name>` area."""
    if not valid_username(username):
        return False
    return _inside(path, [user_upload_root(nfs_root, username)])


def in_user_job_jail(path: str, nfs_root: str, username: str,
                     jobs_subdir: str = "jobs") -> bool:
    """True when path is inside the user's own job workspace."""
    if not valid_username(username):
        return False
    return _inside(path, [user_job_root(nfs_root, username, jobs_subdir)])


# ── Submitted sbatch scripts ─────────────────────────────────────────────────

_IDENTITY_DIRECTIVES = {"uid", "gid", "get-user-env"}
# Flags that take a value; everything else is a boolean flag, so the token
# after it is parsed as its own directive rather than swallowed as a value.
_VALUE_FLAGS = {
    "output", "error", "chdir", "mail-user", "gres", "gpus", "gpus-per-task",
    "cpus-per-task", "mem", "mem-per-cpu", "mem-per-gpu", "job-name", "partition",
    "time", "account", "qos", "nodes", "ntasks", "ntasks-per-node", "array",
    "dependency", "nice", "uid", "gid", "open-mode", "mail-type", "comment",
    "export", "constraint", "exclude", "nodelist", "reservation", "wckey",
    "begin", "deadline", "signal", "switches", "distribution",
}


def _parse_sbatch_directives(text: str) -> list[tuple[str, str]]:
    """Every (key, value) directive across all #SBATCH lines.

    Handles several flags on one line (`#SBATCH --nice=0 --output=/x`), which
    Slurm honours; a first-flag-only parser would let the second flag through.
    Slurm only reads #SBATCH at column 0, so indented lines are ignored.
    """
    out: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.startswith("#SBATCH"):
            continue
        tokens = raw_line[len("#SBATCH"):].split()
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if not tok.startswith("-"):
                i += 1
                continue
            flag = tok.lstrip("-")
            if "=" in flag:
                key, _, val = flag.partition("=")
                out.append((key.lower(), val.strip().strip('"').strip("'")))
                i += 1
                continue
            key = flag.lower()
            if key in _VALUE_FLAGS and i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                out.append((key, tokens[i + 1].strip().strip('"').strip("'")))
                i += 2
            else:
                out.append((key, ""))
                i += 1
    return out


def pod_ceiling(node_stats: _HasShards | None, fallback: int) -> int:
    """The pod ceiling for --gres=shard:N requests.

    The live pod count when the node reports one. A missing reading, or one
    with zero shards (a GRES reporting hiccup, not a one-pod node), falls back
    to the configured maximum so healthy multi-pod requests aren't refused.
    """
    shards = getattr(node_stats, "shard_total", 0) if node_stats is not None else 0
    return shards if shards > 0 else fallback


def _mem_gb(val: str) -> int:
    unit = val[-1].upper() if val[-1].isalpha() else "M"
    num = int(val[:-1]) if val[-1].isalpha() else int(val)
    if unit == "M":
        return num // 1024
    if unit == "G":
        return num
    return num * 1024


def validate_sbatch(
    text: str,
    username: str,
    *,
    nfs_root: str,
    jobs_subdir: str = "jobs",
    registered_email: str | None = None,
    max_gpus: int = 8,
    max_gpu_shards: int = 4,
    max_cpus: int = 64,
    max_mem_gb: int = 256,
    node_stats: _HasShards | None = None,
) -> list[str]:
    """Errors in a submitted sbatch script; an empty list means it is acceptable.

    - --output / --error / --chdir must resolve inside the user's own upload
      area or job workspace.
    - --mail-user must equal registered_email. Fail closed: with no registered
      address, any non-empty --mail-user is refused.
    - --uid / --gid / --get-user-env are refused.
    - GPU, pod, CPU and memory requests over the limits get a pre-flight error.
      The pod ceiling comes from node_stats when it knows the pod count.
    """
    if not valid_username(username):
        return [f"invalid username: {username!r}"]

    errors: list[str] = []
    for key, val in _parse_sbatch_directives(text):
        if key in ("output", "error", "chdir"):
            val_clean = re.sub(r"%[a-zA-Z]", "0", val)
            if val_clean:
                target = val_clean if key == "chdir" else str(Path(val_clean).parent)
                if not (in_user_upload_jail(target, nfs_root, username)
                        or in_user_job_jail(target, nfs_root, username, jobs_subdir)):
                    errors.append(f"--{key} path is outside your personal workspace: {val!r}")

        elif key == "mail-user" and val:
            if not registered_email:
                errors.append(
                    f"--mail-user cannot be verified right now; remove it and retry: {val!r}")
            elif val.strip().lower() != registered_email.strip().lower():
                errors.append(
                    f"--mail-user must be your registered address "
                    f"({registered_email}); got: {val!r}")

        elif key in _IDENTITY_DIRECTIVES:
            errors.append(f"--{key} is not permitted in submitted scripts")

        elif key in ("gres", "gpus", "gpus-per-task"):
            try:
                n = int(val.split(":")[-1])
            except (ValueError, IndexError):
                continue
            if key == "gres" and val.lower().lstrip("-").startswith("shard"):
                ceiling = pod_ceiling(node_stats, max_gpu_shards)
                if n > ceiling:
                    errors.append(f"--gres requests {n} GPU pods; the cluster has {ceiling}")
            elif n > max_gpus:
                errors.append(f"--{key} requests {n} GPUs; cluster limit is {max_gpus}")

        elif key == "cpus-per-task":
            try:
                if int(val) > max_cpus:
                    errors.append(
                        f"--cpus-per-task {val} exceeds cluster limit of {max_cpus}")
            except ValueError:
                pass

        elif key == "mem" and val:
            try:
                if _mem_gb(val) > max_mem_gb:
                    errors.append(f"--mem {val} exceeds cluster limit of {max_mem_gb}G")
            except (ValueError, IndexError):
                pass

    return errors



def validate_against_qos(gpu_shards: int, time_limit: str, max_pods: int | None,
                         max_hours: int | None) -> tuple[bool, str]:
    """Refuse an out-of-policy request before submission: (ok, message).

    Counts pods (GPU shards), as the QOS does. None means no cap.
    """
    if max_pods is not None and gpu_shards > max_pods:
        return False, (f"Requested {gpu_shards} GPU pods but your QOS allows "
                       f"{max_pods} per user.")
    if max_hours is not None and time_limit:
        seconds = parse_hms(time_limit)
        if seconds is not None and seconds > max_hours * 3600:
            return False, (f"Requested {time_limit} exceeds the QOS wall-time "
                           f"limit of {max_hours}h.")
    return True, "ok"
