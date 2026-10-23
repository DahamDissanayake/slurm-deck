"""Batch job-script rendering, ported from legacy/v1.4-tui tests/test_jobs.py.

The legacy folder-creation tests belong to deck-agent now (it creates job
folders as the user); the renderer tests are here.
"""

from datetime import datetime

import pytest

from sdcore.sbatch import (
    JobSpec,
    gres_directive,
    job_folder_name,
    pip_install_block,
    render_batch,
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
