"""env.* verbs and job.submit as sd-ops, with run_as recorded (tests aren't root)."""

import sys

import pytest
from test_verbs_jobs import GOOD, _err, jobs  # noqa: F401  (jobs is a fixture)


@pytest.fixture
def envs(jobs, monkeypatch):  # noqa: F811
    from deckagent.verbs import envs as envs_mod

    monkeypatch.setattr(envs_mod, "_identity", lambda caller, config: _ident(caller.username))
    monkeypatch.setattr(envs_mod, "_ops_identity", lambda caller, config: _ident("sd-ops"))
    monkeypatch.setattr(envs_mod, "run_as", _run_as(jobs))
    shared = jobs.dir / "shared"
    for env, ok in (("envs/vision", True), ("envs/llm-serve", False),
                    ("users/amasha/envs/mine", True)):
        (shared / env / "bin").mkdir(parents=True)
        python = shared / env / "bin/python"
        python.write_text(f'#!/bin/sh\nexec {sys.executable} "$@"\n')
        python.chmod(0o755)
        if ok:
            (shared / env / ".sd-env-ok").write_text("")
    (shared / "images").mkdir()
    (shared / "images/pytorch.sif").write_text("sif")
    return jobs


def _ident(name):
    from deckagent.identity import PosixIdentity

    return PosixIdentity(name, 2001, 2001, (), f"/home/{name}")


def _run_as(agent):
    import subprocess

    def run(who, argv, *, input=None, timeout=60, cwd=None, env=None):
        agent.ran.append((who.name, argv[0].rsplit("/", 1)[-1]))
        return subprocess.run(argv, input=input, capture_output=True, timeout=timeout)
    return run


def test_list_shows_prebuilt_mine_and_images(envs):
    r = envs.call("env.list")
    root = str(envs.dir / "shared")
    assert {(e["name"], e["ready"]) for e in r["prebuilt"]} == {("vision", True),
                                                                 ("llm-serve", False)}
    assert r["mine"] == [{"name": "mine", "path": f"{root}/users/amasha/envs/mine",
                          "kind": "mine", "ready": True}]
    assert [e["name"] for e in r["images"]] == ["pytorch.sif"]


def test_check_imports_reports_missing(envs):
    script = envs.dir / "shared/users/amasha/train.py"
    script.write_text("import os, json\nimport tensorboard\nfrom torch import nn\n"
                      "from . import local\nimport helper\n")
    (envs.dir / "shared/users/amasha/helper.py").write_text("")
    r = envs.call("env.check_imports", {"env_path": str(envs.dir / "shared/envs/vision"),
                                        "script_path": str(script)})
    assert r["missing"] == ["tensorboard", "torch"]
    assert ("amasha", "python") in envs.ran


def test_check_imports_refuses_paths_outside_the_jail(envs):
    e = _err(envs, "env.check_imports", {"env_path": "/usr", "script_path": "/etc/passwd"})
    assert e.status == 403


def test_delete_own_env_only(envs):
    envs.call("env.delete", {"path": str(envs.dir / "shared/users/amasha/envs/mine")})
    assert not (envs.dir / "shared/users/amasha/envs/mine").exists()
    e = _err(envs, "env.delete", {"path": str(envs.dir / "shared/envs/vision")})
    assert e.status == 403 and (envs.dir / "shared/envs/vision").exists()


def test_submit_as_ops_is_admin_only(envs):
    payload = {"folder_name": "install_1", "script": GOOD, "as_ops": True}
    assert _err(envs, "job.submit", payload).status == 403
    r = envs.call("job.submit", payload, as_="admin:dinuka")
    assert r["folder"].endswith("jobs/sd-ops/install_1")
    assert ("sd-ops", "sbatch") in envs.ran
