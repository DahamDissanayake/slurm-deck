"""Notify when free: the subscription API and the worker that sends it once."""

from datetime import UTC, datetime

import pytest
from accounts_helpers import _account, _client

pytestmark = pytest.mark.pg

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


class PodsAgent:
    def __init__(self, total=8, used=6):
        self.total, self.used, self.calls = total, used, 0

    def call(self, verb, payload=None, *, session=None):
        assert verb == "cluster.status"
        self.calls += 1
        return {"node": None, "pods_total": self.total, "pods_used": self.used}


@pytest.fixture
def notify_env(env):
    from sqlalchemy import text

    app = env[0]
    with app.state.sessionmaker() as s, s.begin():
        s.execute(text("TRUNCATE notify_subscriptions, outbox"))
    app.state.agent = PodsAgent()
    _account(app, "amasha")
    return app, _client(app, "amasha")


def _run(app):
    from sdweb.worker.notify_task import run_once

    with app.state.sessionmaker() as s, s.begin():
        return run_once(s, app.state.agent, NOW, app.state.settings)


def _outbox(app):
    from sqlalchemy import select

    from sdweb.models import OutboxMessage

    with app.state.sessionmaker() as s:
        return [(m.to_addr, m.kind) for m in s.scalars(select(OutboxMessage))]


def test_subscribe_change_and_unsubscribe(notify_env):
    app, c = notify_env
    assert c.get("/api/notify").json() == {"wanted_pods": None}
    assert c.put("/api/notify", json={"wanted_pods": 3}).json() == {"wanted_pods": 3}
    assert c.put("/api/notify", json={"wanted_pods": 4}).json() == {"wanted_pods": 4}
    assert c.get("/api/notify").json() == {"wanted_pods": 4}
    assert c.delete("/api/notify").status_code == 200
    assert c.get("/api/notify").json() == {"wanted_pods": None}


@pytest.mark.parametrize("wanted", [0, -1, 9])
def test_out_of_range_is_422(notify_env, wanted):
    _, c = notify_env
    r = c.put("/api/notify", json={"wanted_pods": wanted})
    assert r.status_code == 422 and r.json()["error"] == "bad_pods"


def test_sent_once_when_enough_pods_are_free(notify_env):
    app, c = notify_env
    c.put("/api/notify", json={"wanted_pods": 3})
    assert _run(app) == 0 and _outbox(app) == []         # only 2 free
    app.state.agent.used = 4
    assert _run(app) == 1
    assert _run(app) == 0                                # consumed
    assert _outbox(app) == [("amasha@x.org", "pods_free")]
    assert c.get("/api/notify").json() == {"wanted_pods": None}


def test_subscription_consumed_only_with_a_committed_mail_row(notify_env, monkeypatch):
    from sdweb.worker import notify_task

    app, c = notify_env
    c.put("/api/notify", json={"wanted_pods": 1})

    def broken(*a, **kw):
        raise RuntimeError("outbox down")

    monkeypatch.setattr(notify_task, "enqueue", broken)
    with pytest.raises(RuntimeError):
        _run(app)
    assert c.get("/api/notify").json() == {"wanted_pods": 1}


def test_no_subscriptions_means_no_agent_call(notify_env):
    app, _ = notify_env
    assert _run(app) == 0 and app.state.agent.calls == 0
