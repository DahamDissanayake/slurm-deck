"""Batch job scripts: JobSpec and the sbatch renderer.

Ported from legacy/v1.4-tui slurmdeck/jobs.py (JobSpec, gres_directive,
render_sbatch, pip_install_block). Changes from legacy:
- the job starts from a clean environment (`--export=NONE`) with HOME, USER
  and PATH set explicitly, before any module load or env activation;
- PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True when the job has a GPU pod;
- every path and value placed in shell code is shlex-quoted, and #SBATCH values
  that could add a directive (whitespace, control characters) are refused.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath


@dataclass
class JobSpec:
    job_name: str
    partition: str
    gpu_shards: int          # GPU pods (gres/shard) to request
    cpus: int
    mem_gb: int
    time_limit: str          # "" means no --time directive
    run_command: str
    user: str
    modules: list[str] = field(default_factory=list)
    uploads: list[str] = field(default_factory=list)
    model_path: str = ""
    conda_env: str = ""
    venv_path: str = ""
    task_type: str = "custom"
    container_image: str = ""  # path to a .sif; when set, conda/venv are skipped
    array: str = ""            # Slurm --array spec, e.g. "0-9" or "1-100%4"
    dependency: str = ""       # Slurm --dependency, e.g. "afterok:12345"
    data_path: str = ""        # exported as DATA_PATH
    mail_user: str = ""        # job mail goes here when set


def gres_directive(gpu_shards: int) -> str:
    """The --gres value for a pod request, or "" when the job needs no GPU."""
    return f"shard:{gpu_shards}" if gpu_shards > 0 else ""


def job_folder_name(job_name: str, now: datetime) -> str:
    return f"{job_name}_{now:%Y%m%d_%H%M%S}"


_UNSAFE_DIRECTIVE = re.compile(r"[\s\x00-\x1f\x7f]")


def _directive(key: str, value: object) -> str:
    text = str(value)
    if not text or _UNSAFE_DIRECTIVE.search(text):
        raise ValueError(f"unsafe value for --{key}: {text!r}")
    return f"#SBATCH --{key}={text}"


def pip_install_block(requirements: str, packages: str) -> str:
    """Bash that pip-installs the declared dependencies into the user site
    (~/.local) before the run, so shared prebuilt envs stay untouched."""
    if requirements:
        target = f"-r {shlex.quote(requirements)}"
        what = shlex.quote(PurePosixPath(requirements).name)
    elif packages:
        target = " ".join(shlex.quote(t) for t in packages.split())
        what = shlex.quote(packages)
    else:
        return ""
    return (
        f"echo Installing dependencies: {what}\n"
        f"python3 -m pip install --user --no-warn-script-location {target} \\\n"
        '    || { echo "Dependency install FAILED - see pip output above." >&2; exit 1; }\n'
        'export PATH="$HOME/.local/bin:$PATH"\n'
    )


def render_batch(spec: JobSpec, folder: str, home: str, mail_types: str, *,
                 nfs_root: str = "/shared") -> str:
    """The sbatch script for a batch job running in `folder`.

    nfs_root locates the shared conda install and is bound into containers.
    """
    q = shlex.quote
    log = "slurm-%A_%a" if spec.array else "slurm-%j"
    lines = [
        "#!/bin/bash",
        # The folder name (job name + timestamp) is the Slurm job name, so each
        # run is distinct in the queue and in sacct.
        _directive("job-name", PurePosixPath(folder).name),
        _directive("partition", spec.partition),
        _directive("cpus-per-task", spec.cpus),
        _directive("mem", f"{spec.mem_gb}G"),
    ]
    if spec.gpu_shards > 0:
        lines.append(_directive("gres", gres_directive(spec.gpu_shards)))
    if spec.time_limit:
        lines.append(_directive("time", spec.time_limit))
    if spec.array:
        lines.append(_directive("array", spec.array))
    if spec.dependency:
        lines.append(_directive("dependency", spec.dependency))
    if spec.mail_user:
        lines.append(_directive("mail-user", spec.mail_user))
        lines.append(_directive("mail-type", mail_types))
    lines += [
        _directive("output", f"{folder}/{log}.out"),
        _directive("error", f"{folder}/{log}.err"),
        _directive("chdir", folder),
        # Start clean: nothing from the submitting process leaks into the job.
        "#SBATCH --export=NONE",
        "",
        f"export HOME={q(home)}",
        f"export USER={q(spec.user)}",
        "export PATH=/usr/local/bin:/usr/bin:/bin",
    ]
    if spec.gpu_shards > 0:
        # Pods share one GPU; expandable segments cut fragmentation-driven OOMs.
        lines.append("export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True")
    lines.append("")

    for mod in spec.modules:
        lines.append(f"module load {q(mod)}")
    if spec.modules:
        lines.append("")

    if spec.container_image:
        lines.append(f"cd {q(folder)}")
        lines.append(f"apptainer exec --nv --bind {q(nfs_root)} {q(spec.container_image)} "
                     f"bash -lc {q(spec.run_command)}")
        return "\n".join(lines) + "\n"

    if spec.conda_env:
        # conda.sh must be sourced in a non-interactive shell, or `conda
        # activate` fails quietly and the job runs in the base environment.
        conda_sh = f"{nfs_root.rstrip('/')}/miniforge3/etc/profile.d/conda.sh"
        lines += [
            f"[ -f {q(conda_sh)} ] && source {q(conda_sh)}",
            f"conda activate {q(spec.conda_env)}",
            "",
        ]
    elif spec.venv_path:
        lines += [f"source {q(spec.venv_path + '/bin/activate')}", ""]

    if spec.model_path:
        lines += [f"export MODEL_PATH={q(spec.model_path)}",
                  f"export HF_HOME={q(spec.model_path)}", ""]
    if spec.data_path:
        lines += [f"export DATA_PATH={q(spec.data_path)}", ""]

    lines.append(f"cd {q(folder)}")
    lines.append(spec.run_command)
    return "\n".join(lines) + "\n"
