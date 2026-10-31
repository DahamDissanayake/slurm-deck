"""/api/envs against a fake deck-agent: builds as jobs, lazy results, warnings."""

from dataclasses import replace
from pathlib import Path

import pytest
from accounts_helpers import _account, _client

from sdweb.agent import AgentCallError

pytestmark = pytest.mark.pg

SPECS = Path(__file__).resolve().parents[2] / "deploy/cluster/envs"
MINE = "/shared/users/amasha/my-envs"


class EnvAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.live: list[str] = []
        self.log = b""
        self.missing: list[str] = []
        self.refuse_write = False

    def call(self, verb, payload=None, *, session=None):
        self.calls.append((verb, payload))
        if verb == "fs.write" and self.refuse_write:
            raise AgentCallError("fs_refused",
                                 "You can only change files in your own folder.", 403)
        return {"env.list": {"prebuilt": [], "images": [], "mine": [
                    {"name": "oldenv", "path": f"{MINE}/oldenv", "kind": "mine",
                     "ready": False}] + ([{"name": "mytorch", "path": f"{MINE}/mytorch",
                                           "kind": "mine", "ready": False}]
                                         if any(c[0] == "job.submit" for c in self.calls[:-1])
                                         else [])},
                "job.submit": {"job_id": "700", "folder": "/shared/jobs/amasha/env"},
                "job.list": {"jobs": [{"job_id": j, "state": "RUNNING"} for j in self.live]},
                "env.check_imports": {"missing": self.missing},
                "qos.limits": {"max_wall_s": None, "max_pods_per_user": None},
                }.get(verb, {})

    def stream_with_headers(self, verb, payload=None, *, session=None):
        self.calls.append((verb, payload))
        return {}, iter([self.log])


@pytest.fixture
def envs(env):
    app, _, _ = env
    app.state.settings = replace(app.state.settings, env_spec_dir=str(SPECS))
    app.state.agent = EnvAgent()
    _account(app, "amasha")
    _account(app, "dinuka", role="admin")
    return app, app.state.agent, _client(app, "amasha")


def _build(c):
    r = c.post("/api/envs/build", json={"kind": "conda", "name": "mytorch",
                                        "packages": "torch"})
    assert r.status_code == 201, r.text
    return r.json()["job_id"]


def test_build_submits_a_cpu_job(envs):
    _, agent, c = envs
    _build(c)
    _, payload = next(x for x in agent.calls if x[0] == "job.submit")
    assert f"{MINE}/mytorch" in payload["script"] and "SD_ENV_MISSING" in payload["script"]
    assert "as_ops" not in payload


def test_a_running_build_is_listed_as_building(envs):
    _, agent, c = envs
    agent.live = [_build(c)]
    [b] = c.get("/api/envs").json()["builds"]
    assert (b["name"], b["state"], b["job_id"]) == ("mytorch", "building", "700")


def test_failed_build_is_listed_not_ready_with_missing(envs):
    _, agent, c = envs
    _build(c)
    agent.log = b"Collecting torch\nSD_ENV_MISSING torch\n"
    r = c.get("/api/envs").json()
    [b] = r["builds"]
    assert (b["state"], b["missing"]) == ("failed", ["torch"])
    [mine] = [m for m in r["mine"] if m["name"] == "mytorch"]
    assert (mine["ready"], mine["missing"]) == (False, ["torch"])
    assert not [v for v, _ in agent.calls if v == "fs.write"]
    c.get("/api/envs")   # the result is stored: the log isn't read again
    assert [v for v, _ in agent.calls].count("joblog.read") == 1


def test_good_build_writes_the_ready_marker(envs):
    _, agent, c = envs
    _build(c)
    agent.log = b"SD_ENV_OK\n"
    assert c.get("/api/envs").json()["builds"][0]["state"] == "ok"
    assert ("fs.write", {"path": f"{MINE}/mytorch/.sd-env-ok", "text": ""}) in agent.calls


def test_a_refused_marker_write_does_not_fail_the_listing(envs):
    # SLURM-91: a build path that resolves outside the user's folder (a link
    # into /shared) makes the marker write 403; the listing must still work.
    _, agent, c = envs
    _build(c)
    agent.log = b"SD_ENV_OK\n"
    agent.refuse_write = True
    r = c.get("/api/envs")
    assert r.status_code == 200, r.text
    assert r.json()["builds"][0]["state"] == "ok"
    [mine] = [m for m in r.json()["mine"] if m["name"] == "mytorch"]
    assert mine["ready"] is True


def test_prebuilt_install_is_admin_only(envs):
    app, agent, c = envs
    assert c.post("/api/admin/envs/install", json={"spec": "vision"}).status_code == 403
    admin = _client(app, "dinuka")
    assert admin.post("/api/admin/envs/install", json={"spec": "nope"}).status_code == 404
    r = admin.post("/api/admin/envs/install", json={"spec": "vision"})
    assert r.status_code == 201, r.text
    _, payload = [x for x in agent.calls if x[0] == "job.submit"][-1]
    assert payload["as_ops"] is True
    assert "conda env create -p /shared/envs/vision -f /shared/envs/.specs/vision.yml" \
        in payload["script"]


def test_preview_warns_about_missing_packages(envs):
    _, agent, c = envs
    agent.missing = ["tensorboard"]
    r = c.post("/api/jobs/preview", json={"intent": "batch", "env_kind": "conda",
                                          "conda_env": "/shared/envs/vision",
                                          "script": "/shared/users/amasha/train.py"})
    assert r.json()["warnings"] == [
        "Python package 'tensorboard' isn't in the chosen environment."]
    assert ("env.check_imports", {"env_path": "/shared/envs/vision",
                                  "script_path": "/shared/users/amasha/train.py"}) in agent.calls


def test_build_lands_in_the_users_own_area_not_shared_envs(envs):
    _, agent, c = envs
    _build(c)
    _, payload = next(x for x in agent.calls if x[0] == "job.submit")
    assert "conda create -y -p /shared/users/amasha/my-envs/mytorch" in payload["script"]
    assert "/shared/envs/mytorch" not in payload["script"]


def test_build_with_a_taken_name_is_a_clear_error(envs):
    _, agent, c = envs
    r = c.post("/api/envs/build", json={"kind": "conda", "name": "oldenv"})
    assert r.status_code == 409 and r.json()["error"] == "env_name_taken"
    assert "already exists" in r.text and "Permission denied" not in r.text
    assert not [x for x in agent.calls if x[0] == "job.submit"]
