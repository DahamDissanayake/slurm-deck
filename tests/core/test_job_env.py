"""Every job script the platform renders starts from --export=NIL.

--export=NONE makes slurmd build the user's login environment (like
--get-user-env) by running a login shell as the user. Web accounts have the
shell /usr/sbin/nologin, so that fails and Slurm holds the job with
`user env retrieval failed requeued held`. NIL never asks for a login
environment, so each script sets what it needs itself.
"""

import pytest

from sdcore.envspec import render_env_build
from sdcore.hfdownload import render_hf_download
from sdcore.sbatch import (
    EnvChoice,
    JobSpec,
    SessionOptions,
    render_batch,
    render_notebook,
    render_smoke,
    render_tensorboard,
    render_terminal,
)
from sdcore.validate import user_job_root, validate_sbatch

USER, HOME = "amasha", "/home/amasha"
ENV = EnvChoice("conda", "/shared/envs/pt")
OPTS = SessionOptions(public_origin="https://deck.example", jupyter_env="/shared/envs/jupyter",
                      port_lo=40000, port_hi=40999)


def _spec() -> JobSpec:
    return JobSpec(job_name="t", partition="gpu", gpu_shards=1, cpus=1, mem_gb=1,
                   time_limit="00:05:00", run_command="python3 x.py", user=USER,
                   modules=["CUDA/12"], conda_env=ENV.path)


RENDERERS = {
    "batch": lambda f: render_batch(_spec(), f, HOME, "END,FAIL"),
    "notebook": lambda f: render_notebook(_spec(), f, HOME, ENV, OPTS, "END,FAIL"),
    "terminal": lambda f: render_terminal(_spec(), f, HOME, ENV, OPTS, "END,FAIL"),
    "tensorboard": lambda f: render_tensorboard(_spec(), f, HOME, ENV, f + "/logs", OPTS,
                                                "END,FAIL"),
    "env build": lambda f: render_env_build(USER, f, HOME, kind="conda", name="e",
                                            dest="/shared/users/amasha/envs/e",
                                            packages="numpy", requirements_path=None,
                                            spec_path=None),
    "model download": lambda f: render_hf_download(USER, f, HOME, repo_id="org/model",
                                                   partition="gpu", dest="/shared/models/m",
                                                   revision="main"),
    "smoke test": lambda f: render_smoke(USER, f, HOME, ENV, "gpu"),
}

FOLDER = "/shared/jobs/amasha/job_1"


@pytest.mark.parametrize("kind", RENDERERS)
def test_every_script_uses_export_nil(kind):
    s = RENDERERS[kind](FOLDER)
    assert "#SBATCH --export=NIL\n" in s
    assert "--export=NONE" not in s and "get-user-env" not in s


@pytest.mark.parametrize("kind", RENDERERS)
def test_every_script_sets_its_own_environment_first(kind):
    s = RENDERERS[kind](FOLDER)
    body = s[s.index("#SBATCH --export=NIL"):]
    for line in (f"export HOME={HOME}", f"export USER={USER}", f"export LOGNAME={USER}",
                 "export PATH=/usr/local/bin:/usr/bin:/bin", "export LANG=C.UTF-8"):
        assert line in body, line
    # Nothing runs before the environment is set.
    first_cmd = next(ln for ln in s.splitlines()[1:] if ln and not ln.startswith("#"))
    assert first_cmd == f"export HOME={HOME}"


@pytest.mark.parametrize("kind", RENDERERS)
def test_every_script_passes_the_agents_validation(tmp_path, kind):
    root = tmp_path
    folder = user_job_root(str(root), USER) + "/job_1"
    assert validate_sbatch(RENDERERS[kind](folder), USER, nfs_root=str(root)) == []


def test_modules_are_initialised_before_module_load():
    # The module command comes from the login profile, which NIL never loads.
    s = render_batch(_spec(), FOLDER, HOME, "END,FAIL")
    assert "/etc/profile.d/lmod.sh" in s
    assert s.index("/etc/profile.d/lmod.sh") < s.index("module load")


def test_no_module_init_without_modules():
    spec = _spec()
    spec.modules = []
    assert "lmod" not in render_batch(spec, FOLDER, HOME, "END,FAIL")
