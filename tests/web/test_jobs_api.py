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

    def call(self, verb, payload=None, *, session=None):
        self.calls.append((verb, payload))
        if verb in self.errors:
            raise self.errors[verb]
        return {"qos.limits": {"max_wall_s": 8 * 3600, "max_pods_per_user": 4},
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
