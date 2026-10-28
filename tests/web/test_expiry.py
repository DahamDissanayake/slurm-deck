"""The worker's 30-minute expiry warning: once per job, even across restarts."""

from datetime import UTC, datetime

import pytest
from accounts_helpers import _account

pytestmark = pytest.mark.pg

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


class WorkerAgent:
    def __init__(self, jobs):
        self.jobs, self.sessions = jobs, []

    def call(self, verb, payload=None, *, session=None):
        self.sessions.append(session)
        assert verb == "job.time_left_all"
        return {"jobs": self.jobs}


@pytest.fixture
def worker_db(env):
    from sqlalchemy import text

    from sdweb.models import Account, Job

    app = env[0]
    with app.state.sessionmaker() as s, s.begin():
        s.execute(text("TRUNCATE jobs, outbox"))
    _account(app, "amasha")
    with app.state.sessionmaker() as s, s.begin():
        me = s.query(Account).filter_by(username="amasha").one()
        for job_id in ("41", "42", "43"):
            s.add(Job(job_id=job_id, account_id=me.id, kind="batch", name=f"train_{job_id}",
                      folder="/f", spec={}, script=""))
    return app


def _run(app, agent):
    from sdweb.worker.expiry_task import run_once

    with app.state.sessionmaker() as s, s.begin():
        return run_once(s, agent, NOW, app.state.settings)


def _outbox(app):
    from sqlalchemy import select

    from sdweb.models import OutboxMessage

    with app.state.sessionmaker() as s:
        return s.scalars(select(OutboxMessage).order_by(OutboxMessage.id)).all()


def test_warning_sent_once(worker_db):
    app = worker_db
    agent = WorkerAgent([{"job_id": "42", "user": "amasha", "time_left_s": 25 * 60,
                          "state": "RUNNING"}])
    assert _run(app, agent) == 1
    assert _run(app, agent) == 0                 # a second pass (or a restart) sends nothing
    [mail] = _outbox(app)
    assert (mail.to_addr, mail.kind) == ("amasha@x.org", "job_expiring")
    assert "25 minutes" in mail.text and "/jobs/42?extend=1" in mail.text
    assert agent.sessions == [None, None]        # the worker has no session


def test_31_minutes_left_sends_nothing(worker_db):
    app = worker_db
    agent = WorkerAgent([
        {"job_id": "41", "user": "amasha", "time_left_s": 31 * 60, "state": "RUNNING"},
        {"job_id": "43", "user": "amasha", "time_left_s": 10 * 60, "state": "PENDING"},
        {"job_id": "99", "user": "shelly", "time_left_s": 60, "state": "RUNNING"},  # no row
    ])
    assert _run(app, agent) == 0 and _outbox(app) == []


def test_warning_and_mark_commit_together(worker_db, monkeypatch):
    from sdweb.models import Job
    from sdweb.worker import expiry_task

    app = worker_db

    def broken(*a, **kw):
        raise RuntimeError("outbox down")

    monkeypatch.setattr(expiry_task, "enqueue", broken)
    agent = WorkerAgent([{"job_id": "42", "time_left_s": 600, "state": "RUNNING"}])
    with pytest.raises(RuntimeError):
        _run(app, agent)
    with app.state.sessionmaker() as s:
        assert s.get(Job, "42").warned_at is None   # not marked, so it is retried
