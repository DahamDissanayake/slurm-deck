"""The jobs and cluster API against a fake deck-agent."""

from datetime import UTC, datetime

import pytest
from accounts_helpers import _account, _client

from sdweb.agent import AgentCallError

pytestmark = pytest.mark.pg

OOM = "slurmstepd: error: Detected 1 oom_kill event in StepId=518.batch. Some of your processes"
SPEC = {"intent": "batch", "script": "/shared/users/amasha/train.py", "args": "--epochs 3"}


class JobAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.errors: dict[str, AgentCallError] = {}
        self.show = {"owner": "amasha", "state": "RUNNING"}
        self.err_log = b""
        self.session = {"state": "RUNNING", "ready": False, "kind": None}

    def call(self, verb, payload=None, *, session=None):
        self.calls.append((verb, payload))
        if verb in self.errors:
            raise self.errors[verb]
        return {"qos.limits": {"max_wall_s": 8 * 3600, "max_pods_per_user": 4},
                "session.info": self.session,
                "cluster.status": {"node": None, "pods_total": 0},
                "job.submit": {"job_id": "512", "folder": "/shared/jobs/amasha/f"},
                "job.show": self.show, "job.extend": {"new_limit_s": 10 * 3600},
                "job.list": {"jobs": [{"job_id": "512", "state": "RUNNING"}]},
                }.get(verb, {})

    def stream_with_headers(self, verb, payload=None, *, session=None):
        self.calls.append((verb, payload))
        return {"x-sd-size": str(len(self.err_log))}, iter([self.err_log])


@pytest.fixture
def jobs_env(env):
    app, _, outbox = env
    app.state.agent = JobAgent()
    _account(app, "amasha")
    return app, app.state.agent, outbox, _client(app, "amasha")


def _jobs(app):
    from sqlalchemy import select

    from sdweb.models import Job

    with app.state.sessionmaker() as s:
        return s.scalars(select(Job)).all()


def test_submit_stores_the_row_after_the_agent(jobs_env):
    app, agent, _, c = jobs_env
    preview = c.post("/api/jobs/preview", json=SPEC).json()
    assert preview["problems"] == [] and "python3 /shared/users/amasha/train.py --epochs 3" \
        in preview["script"]
    r = c.post("/api/jobs", json=SPEC)
    assert (r.status_code, r.json()) == (201, {"job_id": "512"})
    [row] = _jobs(app)
    assert (row.kind, row.spec["args"]) == ("batch", "--epochs 3")
    verb, payload = next(x for x in agent.calls if x[0] == "job.submit")
    assert payload["folder_name"].startswith("train_") and "#SBATCH" in payload["script"]
    assert c.get("/api/jobs").json()["jobs"][0]["kind"] == "batch"
    assert c.get("/api/jobs/512/rerun").json()["spec"]["args"] == "--epochs 3"


def test_defaults_say_whether_terminal_jobs_are_enabled(jobs_env):
    from sdweb.models import Setting

    app, _, _, c = jobs_env
    assert c.get("/api/jobs/defaults").json()["terminal_enabled"] is True
    with app.state.sessionmaker() as s, s.begin():
        s.merge(Setting(key="terminal_jobs_enabled", value=False))
    try:
        assert c.get("/api/jobs/defaults").json()["terminal_enabled"] is False
    finally:
        with app.state.sessionmaker() as s, s.begin():
            s.merge(Setting(key="terminal_jobs_enabled", value=True))


def test_detail_includes_the_stored_script(jobs_env):
    _, _, _, c = jobs_env
    c.post("/api/jobs", json=SPEC)
    assert "#SBATCH" in c.get("/api/jobs/512").json()["script"]
    assert c.get("/api/jobs/999").json()["script"] is None   # no row: submitted elsewhere


def test_submit_rate_limit(jobs_env):
    from sdweb.models import Account, Job

    app, _, _, c = jobs_env
    with app.state.sessionmaker() as s, s.begin():
        me = s.query(Account).filter_by(username="amasha").one()
        for i in range(20):
            s.add(Job(job_id=str(i), account_id=me.id, kind="batch", name="j", folder="/f",
                      spec={}, script="", submitted_at=datetime.now(UTC)))
    r = c.post("/api/jobs", json=SPEC)
    assert r.status_code == 429
    assert r.json()["message"] == "You've submitted 20 jobs in the last hour; the limit is 20."


def test_sbatch_error_leaves_no_row(jobs_env):
    app, agent, _, c = jobs_env
    msg = "sbatch: error: Batch job submission failed: Invalid qos specification"
    agent.errors["job.submit"] = AgentCallError("slurm_failed", msg, 502)
    r = c.post("/api/jobs", json=SPEC)
    assert (r.status_code, r.json()["message"]) == (502, msg)
    assert _jobs(app) == []


def test_cancel_ended_job_message(jobs_env):
    _, agent, _, c = jobs_env
    agent.errors["job.cancel"] = AgentCallError("job_ended", "This job has already ended.", 409)
    r = c.post("/api/jobs/42/cancel")
    assert (r.status_code, r.json()["message"]) == (409, "This job has already ended.")


def test_other_users_job_404(jobs_env):
    _, agent, _, c = jobs_env
    agent.errors["job.show"] = AgentCallError("not_found", "There is no such job.", 404)
    assert c.get("/api/jobs/77").status_code == 404
    assert c.get("/api/jobs/77/rerun").status_code == 404


def test_failed_job_detail_includes_explanation(jobs_env):
    _, agent, _, c = jobs_env
    agent.show = {"owner": "amasha", "state": "OUT_OF_MEMORY"}
    agent.err_log = OOM.encode()
    d = c.get("/api/jobs/518").json()
    assert d["explanation"].startswith("Out of memory")


def test_extend_mails_owner(jobs_env):
    app, _, outbox, _ = jobs_env
    _account(app, "dinuka", role="admin")
    admin = _client(app, "dinuka")
    r = admin.post("/api/jobs/512/extend", json={"hours": 2})
    assert r.status_code == 200
    to, kind, ctx = outbox[-1]
    assert (to, kind, ctx["new_limit"], ctx["hours"]) == ("amasha@x.org", "job_extended",
                                                          "10:00:00", "2")


def test_log_and_cluster_pass_through(jobs_env):
    _, agent, _, c = jobs_env
    agent.err_log = b"hello log"
    r = c.get("/api/jobs/512/log", params={"stream": "out"})
    assert r.text == "hello log" and r.headers["x-sd-size"] == "9"
    assert c.get("/api/cluster/status").json()["pods_total"] == 0
    assert c.get("/api/jobs/defaults").json()["spec"]["time_limit"] == "08:00:00"


def _set(app, key, value):
    from sdweb.models import Setting

    with app.state.sessionmaker() as s, s.begin():
        s.merge(Setting(key=key, value=value))


def test_terminal_refused_when_disabled(jobs_env):
    app, agent, _, c = jobs_env
    _set(app, "terminal_jobs_enabled", False)
    try:
        for url in ("/api/jobs/preview", "/api/jobs"):
            r = c.post(url, json={"intent": "terminal"})
            assert (r.status_code, r.json()["error"]) == (403, "terminal_disabled")
        assert not [v for v, _ in agent.calls if v == "job.submit"]
    finally:
        _set(app, "terminal_jobs_enabled", True)


def test_terminal_submits_when_enabled(jobs_env):
    _, agent, _, c = jobs_env
    assert c.post("/api/jobs", json={"intent": "terminal"}).status_code == 201
    _, payload = next(x for x in agent.calls if x[0] == "job.submit")
    assert "terminals_enabled" in payload["script"]


@pytest.mark.parametrize("logdir", ["/etc", "/shared/users/kasun/runs",
                                    "/shared/users/amasha/../kasun"])
def test_tensorboard_logdir_outside_the_jail_is_422(jobs_env, logdir):
    _, agent, _, c = jobs_env
    r = c.post("/api/jobs", json={"intent": "tensorboard", "data_path": logdir})
    assert r.status_code == 422
    assert not [v for v, _ in agent.calls if v == "job.submit"]


def test_tensorboard_submits_with_the_token_guard(jobs_env):
    _, agent, _, c = jobs_env
    r = c.post("/api/jobs", json={"intent": "tensorboard",
                                  "data_path": "/shared/users/amasha/runs"})
    assert r.status_code == 201, r.text
    _, payload = next(x for x in agent.calls if x[0] == "job.submit")
    assert "def make_server" in payload["extra_files"]["tbguard.py"]
    assert "/shared/users/amasha/runs" in payload["script"]


def test_notebook_detail_returns_open_url_when_ready(jobs_env):
    _, agent, _, c = jobs_env
    assert c.post("/api/jobs", json={"intent": "notebook"}).status_code == 201
    assert c.get("/api/jobs/512").json()["session"] == {
        "kind": "notebook", "ready": False, "open_url": None}
    agent.session = {"state": "RUNNING", "ready": True, "kind": "notebook", "node": "n",
                     "port": 8801, "token": "t"}
    session = c.get("/api/jobs/512").json()["session"]
    assert session["ready"] and session["open_url"].endswith("/notebook/512/lab")
    assert "token" not in session


def test_session_check_failure_is_shown_not_raised(jobs_env):
    _, agent, _, c = jobs_env
    c.post("/api/jobs", json={"intent": "notebook"})
    agent.errors["session.info"] = AgentCallError("session_mismatch", "Wrong node.", 409)
    session = c.get("/api/jobs/512").json()["session"]
    assert (session["ready"], session["error"]) == (False, "Wrong node.")


def test_batch_detail_has_no_session(jobs_env):
    _, _, _, c = jobs_env
    c.post("/api/jobs", json=SPEC)
    assert c.get("/api/jobs/512").json()["session"] is None
