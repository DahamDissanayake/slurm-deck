"""Batch job scripts: JobSpec and the sbatch renderer.

Ported from legacy/v1.4-tui slurmdeck/jobs.py (JobSpec, gres_directive,
render_sbatch, pip_install_block). Changes from legacy:
- the job starts from a clean environment (`--export=NONE`) with HOME, USER
  and PATH set explicitly, before any module load or env activation;
- PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True when the job has a GPU pod;
- every path and value placed in shell code is shlex-quoted, and #SBATCH values
  that could add a directive (whitespace, control characters) are refused.

Also the smoke-test job (render_smoke / parse_smoke), ported from legacy
slurmdeck/setup.py::_build_smoke_test_script.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

EnvKind = Literal["prebuilt", "conda", "venv", "container", "none"]


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


@dataclass(frozen=True)
class EnvChoice:
    """The environment a job runs in, as the web app sends it.

    prebuilt and conda both activate a conda env at `path`; venv sources
    `path`/bin/activate; container runs inside the `path` image; none runs as is.
    """

    kind: EnvKind
    path: str

    @classmethod
    def from_fields(cls, conda_env: str, venv_path: str, container_image: str) -> EnvChoice:
        if container_image:
            return cls("container", container_image)
        if conda_env:
            return cls("conda", conda_env)
        if venv_path:
            return cls("venv", venv_path)
        return cls("none", "")

    def as_fields(self) -> dict[str, str]:
        """The JobSpec/LaunchSpec fields this choice maps back to."""
        return {
            "conda_env": self.path if self.kind in ("prebuilt", "conda") else "",
            "venv_path": self.path if self.kind == "venv" else "",
            "container_image": self.path if self.kind == "container" else "",
        }


def gres_directive(gpu_shards: int) -> str:
    """The --gres value for a pod request, or "" when the job needs no GPU."""
    return f"shard:{gpu_shards}" if gpu_shards > 0 else ""


def job_folder_name(job_name: str, now: datetime) -> str:
    return f"{job_name}_{now:%Y%m%d_%H%M%S}"


def run_command_for(script: str, args: str) -> str:
    """The shell command that runs a user's script with their arguments.

    The path is one quoted word whatever it contains. args are split the way a
    shell would split them, then each word is quoted, so they can't run
    anything; unbalanced quotes raise ValueError.
    """
    interpreter = "bash" if script.endswith(".sh") else "python3"
    words = [interpreter, script, *shlex.split(args)]
    return " ".join(shlex.quote(w) for w in words)


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


def _clean_env(home: str, user: str, gpu: bool) -> list[str]:
    """Start clean: nothing from the submitting process leaks into the job."""
    lines = [
        "#SBATCH --export=NONE",
        "",
        f"export HOME={shlex.quote(home)}",
        f"export USER={shlex.quote(user)}",
        "export PATH=/usr/local/bin:/usr/bin:/bin",
    ]
    if gpu:
        # Pods share one GPU; expandable segments cut fragmentation-driven OOMs.
        lines.append("export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True")
    return lines + [""]


def _activate(env: EnvChoice, nfs_root: str) -> list[str]:
    """Activation lines for a conda or venv environment; none for the others."""
    q = shlex.quote
    if env.kind in ("prebuilt", "conda"):
        # conda.sh must be sourced in a non-interactive shell, or `conda
        # activate` fails quietly and the job runs in the base environment.
        conda_sh = f"{nfs_root.rstrip('/')}/miniforge3/etc/profile.d/conda.sh"
        return [f"[ -f {q(conda_sh)} ] && source {q(conda_sh)}",
                f"conda activate {q(env.path)}", ""]
    if env.kind == "venv":
        return [f"source {q(env.path + '/bin/activate')}", ""]
    return []


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
        *_clean_env(home, spec.user, spec.gpu_shards > 0),
    ]

    for mod in spec.modules:
        lines.append(f"module load {q(mod)}")
    if spec.modules:
        lines.append("")

    if spec.container_image:
        lines.append(f"cd {q(folder)}")
        lines.append(f"apptainer exec --nv --bind {q(nfs_root)} {q(spec.container_image)} "
                     f"bash -lc {q(spec.run_command)}")
        return "\n".join(lines) + "\n"

    lines += _activate(EnvChoice.from_fields(spec.conda_env, spec.venv_path, ""), nfs_root)

    if spec.model_path:
        lines += [f"export MODEL_PATH={q(spec.model_path)}",
                  f"export HF_HOME={q(spec.model_path)}", ""]
    if spec.data_path:
        lines += [f"export DATA_PATH={q(spec.data_path)}", ""]

    lines.append(f"cd {q(folder)}")
    lines.append(spec.run_command)
    return "\n".join(lines) + "\n"


# ── Smoke test ───────────────────────────────────────────────────────────────

SMOKE_CPUS = 4
SMOKE_MEM_GB = 8
SMOKE_TIME = "00:30:00"

_TORCH_CHECK = """python3 - <<'PYEOF'
try:
    import torch
except ImportError:
    print("SMOKE torch-cuda=skipped")
else:
    print("SMOKE torch-cuda=" + ("ok" if torch.cuda.is_available() else "fail"))
PYEOF"""


def render_smoke(user: str, folder: str, home: str, env: EnvChoice, partition: str, *,
                 nfs_root: str = "/shared") -> str:
    """A tiny one-pod job that checks the GPU, CUDA from the chosen environment
    and the user's folders, printing one `SMOKE <check>=ok|fail|skipped` line each."""
    q = shlex.quote
    lines = [
        "#!/bin/bash",
        _directive("job-name", PurePosixPath(folder).name),
        _directive("partition", partition),
        _directive("gres", gres_directive(1)),
        _directive("cpus-per-task", SMOKE_CPUS),
        _directive("mem", f"{SMOKE_MEM_GB}G"),
        _directive("time", SMOKE_TIME),
        _directive("output", f"{folder}/slurm-%j.out"),
        _directive("error", f"{folder}/slurm-%j.err"),
        _directive("chdir", folder),
        *_clean_env(home, user, gpu=True),
        "if nvidia-smi; then echo 'SMOKE nvidia-smi=ok'; else echo 'SMOKE nvidia-smi=fail'; fi",
        "",
    ]
    if env.kind == "container":
        lines.append(f"apptainer exec --nv --bind {q(nfs_root)} {q(env.path)} {_TORCH_CHECK}")
    else:
        lines += _activate(env, nfs_root)
        lines.append(_TORCH_CHECK)
    lines += [
        "",
        f'if [ -d "$HOME" ] && [ -w "$HOME" ] && touch {q(folder + "/.smoke")} '
        f'&& rm -f {q(folder + "/.smoke")}; then',
        "    echo 'SMOKE user-folder=ok'",
        "else",
        "    echo 'SMOKE user-folder=fail'",
        "fi",
    ]
    return "\n".join(lines) + "\n"


_SMOKE_LINE = re.compile(r"^SMOKE ([a-z-]+)=(ok|fail|skipped)$")


def parse_smoke(out_text: str) -> dict[str, str]:
    """{check: result} from the smoke job's output."""
    results = {}
    for line in out_text.splitlines():
        if m := _SMOKE_LINE.match(line.strip()):
            results[m.group(1)] = m.group(2)
    return results
