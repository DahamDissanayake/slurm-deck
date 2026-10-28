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


def _header(spec: JobSpec, folder: str, home: str, mail_types: str) -> list[str]:
    """The #SBATCH directives and clean environment shared by every job kind."""
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
    return lines + [
        _directive("output", f"{folder}/{log}.out"),
        _directive("error", f"{folder}/{log}.err"),
        _directive("chdir", folder),
        *_clean_env(home, spec.user, spec.gpu_shards > 0),
    ]


def render_batch(spec: JobSpec, folder: str, home: str, mail_types: str, *,
                 nfs_root: str = "/shared") -> str:
    """The sbatch script for a batch job running in `folder`.

    nfs_root locates the shared conda install and is bound into containers.
    """
    q = shlex.quote
    lines = _header(spec, folder, home, mail_types)

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


# ── Interactive sessions: notebook, terminal, TensorBoard (Phase 5) ──────────
#
# Each session job binds its service to the node address on a free port in the
# session range, then prints exactly one line once something is listening:
#   SD_SESSION kind=<kind> node=<addr> port=<port> token=<token>
# (read by sdcore.connect.parse_session_line) and touches .sd-ready. The token
# reaches services through the environment, never the command line, where any
# user on the node could read it from ps.


@dataclass(frozen=True)
class SessionOptions:
    public_origin: str   # e.g. https://<public hostname>, for allow_origin
    jupyter_env: str     # the shared env JupyterLab runs from
    port_lo: int
    port_hi: int


_NODE_ADDR = """SD_NODE_ADDR=$(scontrol show node "${SLURMD_NODENAME:-$(hostname -s)}" \\
    2>/dev/null | sed -n 's/.*NodeAddr=\\([^ ]*\\).*/\\1/p')
[ -n "$SD_NODE_ADDR" ] || SD_NODE_ADDR=$(hostname -I | awk '{print $1}')
[ -n "$SD_NODE_ADDR" ] || SD_NODE_ADDR=127.0.0.1
SD_TOKEN=$(python3 -c 'import secrets; print(secrets.token_hex(24))')
export SD_TOKEN
"""


def free_port_snippet(lo: int, hi: int) -> str:
    """Bash that sets $SD_PORT to a free port in lo..hi, or exits.

    The scan starts at an offset from the job ID, so jobs starting together
    rarely probe the same port, then wraps to cover the whole range.
    """
    return f"""SD_PORT=$(python3 - <<'PYEOF'
import os, socket, sys
lo, hi = {lo}, {hi}
start = lo + int(os.environ.get("SLURM_JOB_ID", "0")) % (hi - lo + 1)
for p in list(range(start, hi + 1)) + list(range(lo, start)):
    s = socket.socket()
    try:
        s.bind(("", p))
    except OSError:
        continue
    finally:
        s.close()
    print(p)
    break
else:
    sys.exit(1)
PYEOF
)
[ -n "$SD_PORT" ] || {{ echo "ERROR: no free port in {lo}-{hi} on this node." >&2; exit 1; }}
"""


def _user_root(nfs_root: str) -> list[str]:
    """$SD_USER_ROOT, the user's own folder, with the shared read-only assets
    linked in. An existing real file or folder at a link's place is left alone."""
    root = shlex.quote(nfs_root.rstrip("/"))
    return [
        f'SD_USER_ROOT={root}/users/"$USER"',
        'mkdir -p "$SD_USER_ROOT"',
        "for _sd_asset in models envs data datasets; do",
        '    _sd_link="$SD_USER_ROOT/$_sd_asset"',
        '    if [ -L "$_sd_link" ] || [ ! -e "$_sd_link" ]; then',
        f'        ln -sfn {root}/"$_sd_asset" "$_sd_link"',
        "    fi",
        "done",
        "",
    ]


def _serve(kind: str, folder: str, launch: str) -> list[str]:
    """Start the service, then announce it once its port accepts connections."""
    return [
        f"{launch} &",
        "SD_SERVICE_PID=$!",
        "for _sd_i in $(seq 1 150); do",
        '    kill -0 "$SD_SERVICE_PID" 2>/dev/null || break',
        '    if (exec 3<>"/dev/tcp/$SD_NODE_ADDR/$SD_PORT") 2>/dev/null; then',
        f'        echo "SD_SESSION kind={kind} node=$SD_NODE_ADDR port=$SD_PORT token=$SD_TOKEN"',
        f"        touch {shlex.quote(folder + '/.sd-ready')}",
        "        break",
        "    fi",
        "    sleep 2",
        "done",
        'wait "$SD_SERVICE_PID"',
    ]


def _jupyter_flags(base: str, opts: SessionOptions) -> str:
    return (f'--no-browser --ip="$SD_NODE_ADDR" --port="$SD_PORT" --port-retries=0 '
            f'--ServerApp.root_dir="$SD_USER_ROOT" --ServerApp.base_url=/{base}/$SLURM_JOB_ID/ '
            f"--ServerApp.allow_origin={shlex.quote(opts.public_origin)} "
            "--FileContentsManager.delete_to_trash=False "
            "--ServerApp.websocket_ping_interval=30 --ServerApp.websocket_ping_timeout=30")


def _session_start(spec: JobSpec, folder: str, home: str, opts: SessionOptions,
                   mail_types: str, nfs_root: str) -> list[str]:
    return [*_header(spec, folder, home, mail_types),
            # Terminals spawn $SHELL; without it they fall back to sh (no history).
            "export SHELL=/bin/bash", _NODE_ADDR,
            free_port_snippet(opts.port_lo, opts.port_hi), *_user_root(nfs_root)]


def render_notebook(spec: JobSpec, folder: str, home: str, env: EnvChoice,
                    opts: SessionOptions, mail_types: str, *, nfs_root: str = "/shared") -> str:
    """JupyterLab from the shared Jupyter env, with the user's env as the
    default kernel when it has ipykernel (otherwise `SD_WARN kernel-fallback`)."""
    q = shlex.quote
    lines = _session_start(spec, folder, home, opts, mail_types, nfs_root)
    lines += [f"export JUPYTER_PATH={q(folder + '/.jupyter/share/jupyter')}",
              "SD_KERNEL_ARGS=()"]
    if env.kind in ("prebuilt", "conda", "venv"):
        py = q(env.path.rstrip("/") + "/bin/python")
        lines += [
            f"if {py} -c 'import ipykernel' 2>/dev/null; then",
            f"    {py} -m ipykernel install --prefix {q(folder + '/.jupyter')} "
            f"--name sd-user-env --display-name {q('Python (' + env.path + ')')} >/dev/null",
            "    SD_KERNEL_ARGS=(--MappingKernelManager.default_kernel_name=sd-user-env)",
            "else",
            '    echo "SD_WARN kernel-fallback"',
            "fi",
        ]
    else:
        lines.append('echo "SD_WARN kernel-fallback"')
    jupyter = q(opts.jupyter_env.rstrip("/") + "/bin/jupyter")
    lines += ['export JUPYTER_TOKEN="$SD_TOKEN"', 'cd "$SD_USER_ROOT"', ""]
    lines += _serve("notebook", folder,
                    f'{jupyter} lab {_jupyter_flags("notebook", opts)} "${{SD_KERNEL_ARGS[@]}}"')
    return "\n".join(lines) + "\n"


def render_terminal(spec: JobSpec, folder: str, home: str, env: EnvChoice,
                    opts: SessionOptions, mail_types: str, *, nfs_root: str = "/shared") -> str:
    """A Jupyter Server with terminals only; the terminals get the user's env."""
    q = shlex.quote
    lines = _session_start(spec, folder, home, opts, mail_types, nfs_root)
    lines += _activate(env, nfs_root)
    jupyter = q(opts.jupyter_env.rstrip("/") + "/bin/jupyter")
    lines += ['export JUPYTER_TOKEN="$SD_TOKEN"', 'cd "$SD_USER_ROOT"', ""]
    lines += _serve("terminal", folder, f"{jupyter} server {_jupyter_flags('terminal', opts)} "
                    "--ServerApp.terminals_enabled=True")
    return "\n".join(lines) + "\n"


def render_tensorboard(spec: JobSpec, folder: str, home: str, env: EnvChoice, logdir: str,
                       opts: SessionOptions, mail_types: str, *,
                       nfs_root: str = "/shared") -> str:
    """TensorBoard on 127.0.0.1, reachable only through the token guard
    (sdcore.tbguard, copied into the job folder by deck-agent at submit)."""
    q = shlex.quote
    lines = _session_start(spec, folder, home, opts, mail_types, nfs_root)
    lines += _activate(env, nfs_root)
    fallback = q(opts.jupyter_env.rstrip("/") + "/bin/tensorboard")
    lines += [
        f"SD_TB=$(command -v tensorboard || echo {fallback})",
        "SD_INNER_PORT=$(python3 -c 'import socket; s = socket.socket(); "
        's.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()\')',
        f'"$SD_TB" --logdir {q(logdir)} --host 127.0.0.1 --port "$SD_INNER_PORT" '
        "--path_prefix=/tensorboard/$SLURM_JOB_ID &",
        "",
    ]
    lines += _serve("tensorboard", folder,
                    f"python3 {q(folder + '/tbguard.py')} --listen \"$SD_NODE_ADDR:$SD_PORT\" "
                    '--upstream "127.0.0.1:$SD_INNER_PORT"')
    return "\n".join(lines) + "\n"
