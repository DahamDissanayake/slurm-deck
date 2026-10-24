"""Batch job-script rendering, ported from legacy/v1.4-tui tests/test_jobs.py.

The legacy folder-creation tests belong to deck-agent now (it creates job
folders as the user); the renderer tests are here.
"""

import os
import shlex
import shutil
import socket
import subprocess
import sys
from datetime import datetime

import pytest

from sdcore.connect import SessionInfo, parse_session_line
from sdcore.sbatch import (
    EnvChoice,
    JobSpec,
    SessionOptions,
    free_port_snippet,
    gres_directive,
    job_folder_name,
    parse_smoke,
    pip_install_block,
    render_batch,
    render_notebook,
    render_smoke,
    render_tensorboard,
    render_terminal,
    run_command_for,
)

FOLDER = "/shared/jobs/amasha/train_model_20260601_045303"


def spec(**kwargs) -> JobSpec:
    values = dict(job_name="train_model", partition="gpu-short", gpu_shards=2, cpus=8,
                  mem_gb=32, time_limit="04:00:00", run_command="python train.py --epochs 10",
                  user="amasha", modules=["CUDA/11.8", "Python/3.11"],
                  conda_env="/shared/envs/pytorch")
    values.update(kwargs)
    return JobSpec(**values)


def render(s: JobSpec, folder: str = FOLDER, **kw) -> str:
    return render_batch(s, folder, home="/home/amasha", mail_types="END,FAIL", **kw)


def test_batch_sets_clean_env_and_home():
    s = render_batch(spec(user="amasha"), "/shared/jobs/amasha/t_1", home="/home/amasha",
                     mail_types="END,FAIL")
    assert "#SBATCH --export=NONE" in s and "export HOME=/home/amasha" in s
    assert "export USER=amasha" in s and "export PATH=/usr/local/bin:/usr/bin:/bin" in s
    assert s.index("export HOME=") < s.index("conda activate")
    assert s.index("export HOME=") < s.index("module load")


def test_batch_sets_alloc_conf_only_with_gpu():
    assert "expandable_segments:True" in render(spec(gpu_shards=1))
    assert "expandable_segments" not in render(spec(gpu_shards=0))


def test_render_header():
    s = render(spec())
    assert s.startswith("#!/bin/bash\n")
    # The Slurm job name is the folder name (job name + timestamp), unique per run.
    for line in ("#SBATCH --job-name=train_model_20260601_045303",
                 "#SBATCH --partition=gpu-short", "#SBATCH --cpus-per-task=8",
                 "#SBATCH --mem=32G", "#SBATCH --gres=shard:2", "#SBATCH --time=04:00:00",
                 f"#SBATCH --chdir={FOLDER}", f"#SBATCH --output={FOLDER}/slurm-%j.out",
                 f"#SBATCH --error={FOLDER}/slurm-%j.err"):
        assert line in s, line


def test_render_time_limit_only_when_set():
    assert "#SBATCH --time=" not in render(spec(time_limit=""))


def test_render_gpu_only_when_pods():
    assert "--gres" not in render(spec(gpu_shards=0))


def test_render_array_uses_array_log_names():
    s = render(spec(array="0-9", dependency="afterok:12"))
    assert "#SBATCH --array=0-9" in s and "#SBATCH --dependency=afterok:12" in s
    assert f"#SBATCH --output={FOLDER}/slurm-%A_%a.out" in s


def test_render_mail_only_with_a_mail_user():
    assert "--mail-user" not in render(spec())
    s = render(spec(mail_user="amasha@iit.ac.lk"))
    assert "#SBATCH --mail-user=amasha@iit.ac.lk" in s and "#SBATCH --mail-type=END,FAIL" in s


def test_render_run_command_and_modules():
    s = render(spec())
    assert "module load CUDA/11.8" in s and "module load Python/3.11" in s
    assert s.rstrip().endswith("python train.py --epochs 10")
    assert f"cd {FOLDER}" in s


def test_render_conda_sources_conda_sh_from_the_nfs_root():
    s = render(spec(conda_env="my-env"), nfs_root="/data/share")
    assert "source /data/share/miniforge3/etc/profile.d/conda.sh" in s
    assert "conda activate my-env" in s


def test_render_venv_model_and_data_paths():
    s = render(spec(conda_env="", venv_path="/shared/users/amasha/venv",
                    model_path="/shared/models/llm", data_path="/shared/data/c10"))
    assert "source /shared/users/amasha/venv/bin/activate" in s
    assert "export MODEL_PATH=/shared/models/llm" in s and "export HF_HOME=/shared/models/llm" in s
    assert "export DATA_PATH=/shared/data/c10" in s


def test_render_container_quotes_the_command():
    s = render(spec(container_image="/shared/images/llm.sif",
                    run_command="python x.py --msg \"it's\""), nfs_root="/shared")
    assert "apptainer exec --nv --bind /shared /shared/images/llm.sif bash -lc " in s
    assert "conda activate" not in s
    assert "'python x.py --msg \"it'\"'\"'s\"'" in s     # shlex-quoted, not repr()


def test_render_quotes_paths_for_the_shell():
    s = render(spec(conda_env="", data_path="/shared/data/a b;rm -rf ~"))
    assert "export DATA_PATH='/shared/data/a b;rm -rf ~'" in s


@pytest.mark.parametrize("field, value", [
    ("partition", "gpu\n#SBATCH --uid=0"), ("mail_user", "a@b.c --uid=0"),
    ("array", "0-9\n#SBATCH --uid=0"), ("dependency", "afterok:1 --uid=0")])
def test_render_refuses_directive_values_that_could_add_directives(field, value):
    with pytest.raises(ValueError):
        render(spec(**{field: value}))


def test_render_refuses_a_folder_with_whitespace():
    with pytest.raises(ValueError):
        render(spec(), folder="/shared/jobs/amasha/a b")


def test_gres_directive():
    assert gres_directive(2) == "shard:2" and gres_directive(0) == ""


def test_job_folder_name():
    assert job_folder_name("train", datetime(2026, 6, 1, 4, 53, 3)) == "train_20260601_045303"


def test_pip_install_block_quotes_packages():
    block = pip_install_block("", "torch $(id) numpy")
    assert "echo Installing dependencies: 'torch $(id) numpy'" in block
    assert "pip install --user --no-warn-script-location torch '$(id)' numpy" in block
    assert pip_install_block("", "") == ""


def test_pip_install_block_requirements():
    block = pip_install_block("/shared/users/a/req s.txt", "")
    assert "-r '/shared/users/a/req s.txt'" in block


# ── EnvChoice, run commands and the smoke test (Phase 3) ─────────────────────

def test_run_command_quotes_a_script_path_and_args(tmp_path):
    script = '/shared/users/a/my "x" run.py'
    cmd = run_command_for(script, "--epochs 10 --name 'a b'")
    assert shlex.split(cmd) == ["python3", script, "--epochs", "10", "--name", "a b"]
    assert shlex.split(run_command_for("/shared/users/a/go.sh", ""))[0] == "bash"
    rendered = render(spec(run_command=cmd))
    if shutil.which("bash"):
        path = tmp_path / "job.sbatch"
        path.write_text(rendered)
        assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    assert shlex.split(rendered.rstrip().splitlines()[-1])[1] == script


def test_run_command_refuses_unbalanced_args():
    with pytest.raises(ValueError):
        run_command_for("/shared/users/a/x.py", "--name 'oops")


def test_env_choice_round_trips_spec_fields():
    assert EnvChoice("conda", "/shared/envs/pt").as_fields() == {
        "conda_env": "/shared/envs/pt", "venv_path": "", "container_image": ""}
    assert EnvChoice.from_fields("", "", "/shared/images/a.sif") == EnvChoice(
        "container", "/shared/images/a.sif")
    assert EnvChoice.from_fields("", "", "") == EnvChoice("none", "")


CONDA = EnvChoice("conda", "/shared/envs/pt")


def _smoke(env: EnvChoice = CONDA) -> str:
    return render_smoke("amasha", "/shared/jobs/amasha/smoke_test_1", "/home/amasha", env,
                        "gpu")


def test_smoke_uses_the_fixed_small_allocation():
    s = _smoke()
    for line in ("#SBATCH --gres=shard:1", "#SBATCH --cpus-per-task=4", "#SBATCH --mem=8G",
                 "#SBATCH --time=00:30:00", "#SBATCH --partition=gpu",
                 "#SBATCH --export=NONE", "conda activate /shared/envs/pt"):
        assert line in s, line
    assert s.index("export HOME=/home/amasha") < s.index("conda activate")


def test_smoke_script_is_valid_bash(tmp_path):
    if not shutil.which("bash"):
        pytest.skip("no bash")
    for env in (EnvChoice("conda", "/shared/envs/pt"), EnvChoice("venv", "/v"),
                EnvChoice("container", "/shared/images/x y.sif"), EnvChoice("none", "")):
        path = tmp_path / "smoke.sbatch"
        path.write_text(_smoke(env))
        assert subprocess.run(["bash", "-n", str(path)]).returncode == 0, env


def test_parse_smoke_reads_all_three_lines():
    out = ("GPU 0: NVIDIA RTX\nSMOKE nvidia-smi=ok\nnoise\nSMOKE torch-cuda=skipped\n"
           "SMOKE user-folder=fail\nSMOKE bogus line\n")
    assert parse_smoke(out) == {"nvidia-smi": "ok", "torch-cuda": "skipped",
                                "user-folder": "fail"}


# ── Session renderers (Phase 5) ──────────────────────────────────────────────

OPTS = SessionOptions(public_origin="https://slurmdeck.local",
                      jupyter_env="/shared/envs/data-science", port_lo=8800, port_hi=8999)
SESSION_FOLDER = "/shared/jobs/amasha/notebook_20260601_045303"


def _session(kind: str, env: EnvChoice = CONDA) -> str:
    s = spec(gpu_shards=1, modules=[], conda_env="")
    if kind == "notebook":
        return render_notebook(s, SESSION_FOLDER, "/home/amasha", env, OPTS, "END,FAIL")
    if kind == "terminal":
        return render_terminal(s, SESSION_FOLDER, "/home/amasha", env, OPTS, "END,FAIL")
    return render_tensorboard(s, SESSION_FOLDER, "/home/amasha", env,
                              "/shared/users/amasha/runs", OPTS, "END,FAIL")


def test_notebook_flags():
    s = _session("notebook")
    for flag in ["--FileContentsManager.delete_to_trash=False",
                 "--ServerApp.websocket_ping_interval=30",
                 "--ServerApp.websocket_ping_timeout=30",
                 "--ServerApp.base_url=/notebook/$SLURM_JOB_ID/",
                 "--ServerApp.allow_origin=https://slurmdeck.local",
                 "--port-retries=0", "--no-browser"]:
        assert flag in s, flag
    assert "pip install --user jupyterlab" not in s and "/shared/envs/data-science" in s
    assert "/shared/envs/data-science/bin/jupyter lab" in s
    # The token travels in the environment, not on the command line (ps).
    assert 'export JUPYTER_TOKEN="$SD_TOKEN"' in s and "IdentityProvider.token" not in s


def test_notebook_uses_the_user_env_as_kernel_or_falls_back():
    s = _session("notebook")
    assert "/shared/envs/pt/bin/python -c 'import ipykernel'" in s
    assert "SD_WARN kernel-fallback" in s
    assert "--MappingKernelManager.default_kernel_name=sd-user-env" in s


def test_terminal_flags():
    s = _session("terminal")
    assert "/shared/envs/data-science/bin/jupyter server" in s
    assert "--ServerApp.base_url=/terminal/$SLURM_JOB_ID/" in s
    assert "--ServerApp.terminals_enabled=True" in s and "export SHELL=/bin/bash" in s
    assert "conda activate /shared/envs/pt" in s     # terminals get the user's env
    assert 'SD_USER_ROOT=/shared/users/"$USER"' in s


def test_tensorboard_is_behind_the_guard():
    s = _session("tensorboard")
    assert "--host 127.0.0.1 --port \"$SD_INNER_PORT\"" in s
    assert "--path_prefix=/tensorboard/$SLURM_JOB_ID" in s
    assert f"python3 {SESSION_FOLDER}/tbguard.py --listen" in s
    assert "--logdir /shared/users/amasha/runs" in s


@pytest.mark.parametrize("kind", ["notebook", "terminal", "tensorboard"])
def test_session_line_printed_after_bind(kind):
    s = _session(kind)
    launch = s.index("SD_SERVICE_PID=$!")
    probe = s.index('/dev/tcp/$SD_NODE_ADDR/$SD_PORT')
    line = s.index(f"echo \"SD_SESSION kind={kind} node=$SD_NODE_ADDR port=$SD_PORT "
                   "token=$SD_TOKEN\"")
    assert launch < probe < line
    assert s.count("SD_SESSION kind=") == 1 and ".sd-ready" in s


@pytest.mark.parametrize("kind", ["notebook", "terminal", "tensorboard"])
def test_session_scripts_pass_bash_n(tmp_path, kind):
    if not shutil.which("bash"):
        pytest.skip("no bash")
    for env in (CONDA, EnvChoice("venv", "/v"), EnvChoice("container", "/i.sif"),
                EnvChoice("none", "")):
        path = tmp_path / "s.sbatch"
        path.write_text(_session(kind, env))
        assert subprocess.run(["bash", "-n", str(path)]).returncode == 0, (kind, env)


def test_port_scan_stays_in_range():
    if not shutil.which("bash") or sys.platform != "linux":
        pytest.skip("needs Linux bash")
    held = []
    try:
        for port in (18800, 18801):
            s = socket.socket()
            s.bind(("", port))
            s.listen()
            held.append(s)
        script = free_port_snippet(18800, 18802) + 'echo "$SD_PORT"\n'
        # Job 3 would start at 18800 + 3 % 3 = 18800; both taken, so it must land on 18802.
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                             env={**os.environ, "SLURM_JOB_ID": "3"})
        assert out.stdout.strip() == "18802"
        full = subprocess.run(["bash", "-c", free_port_snippet(18800, 18801)],
                              capture_output=True, text=True,
                              env={**os.environ, "SLURM_JOB_ID": "1"})
        assert full.returncode != 0
    finally:
        for s in held:
            s.close()


def test_parse_session_line_last_wins():
    out = ("starting\nSD_SESSION kind=notebook node=10.0.0.5 port=8801 token=aa11\n"
           "restarted\nSD_SESSION kind=notebook node=10.0.0.5 port=8805 token=bb22\n"
           "SD_SESSION kind=notebook node=x port=notaport token=cc\n")
    assert parse_session_line(out) == SessionInfo("notebook", "10.0.0.5", 8805, "bb22")
    assert parse_session_line("no session here\n") is None
