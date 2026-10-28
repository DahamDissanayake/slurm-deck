"""Live updates over /ws/live: session checks, the cluster feed, and each
account seeing only its own jobs."""

from datetime import UTC, datetime, timedelta

import pytest
from accounts_helpers import _account, _client
from starlette.websockets import WebSocketDisconnect

pytestmark = pytest.mark.pg


class LiveAgent:
    """Answers the cluster verbs, and job.list per session token."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.jobs_by_session: dict[str, list[dict]] = {}

    def call(self, verb, payload=None, *, session=None):
        self.calls.append(verb)
        if verb == "job.list":
            return {"jobs": self.jobs_by_session.get(session, [])}
        return {"cluster.status": {"node": {"state": "MIXED"}, "pods_total": 8, "pods_used": 3,
                                   "partition_max_s": 86400},
                "cluster.queue": {"jobs": [{"job_id": "1", "user": "x", "state": "RUNNING"}]},
                "cluster.disk_free": {"total_bytes": 10, "used_bytes": 4, "free_bytes": 6},
                }[verb]


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def live(env):
    app = env[0]
    app.state.agent = LiveAgent()
    app.state.clock = Clock()
    app.state.live_interval_s = 0.1
    return app


def _ws(client):
    """TestClient doesn't send the Secure cookie over its ws:// URL; browsers do over wss://."""
    return client.websocket_connect(
        "/ws/live", headers={"cookie": f"sd_session={client.cookies['sd_session']}"})


def _until(ws, kind: str, limit: int = 50) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == kind:
            return msg
    raise AssertionError(f"no {kind} message")


def test_ws_without_cookie_closes_4401(live):
    from fastapi.testclient import TestClient

    anon = TestClient(live, base_url="https://testserver")
    with pytest.raises(WebSocketDisconnect) as e, anon.websocket_connect("/ws/live") as ws:
        ws.receive_json()
    assert e.value.code == 4401
    assert live.state.agent.calls == []          # nothing is polled for nobody


def test_session_receives_cluster_message(live):
    _account(live, "amasha")
    c = _client(live, "amasha")
    with _ws(c) as ws:
        msg = _until(ws, "cluster")
    assert (msg["pods_total"], msg["pods_used"], msg["node"]["state"]) == (8, 3, "MIXED")
    assert msg["disk"]["free_bytes"] == 6 and msg["maintenance"] is None
    assert msg["queue"][0]["job_id"] == "1"


def test_expiry_closes_the_socket(live):
    _account(live, "amasha")
    c = _client(live, "amasha")
    with pytest.raises(WebSocketDisconnect) as e, _ws(c) as ws:
        _until(ws, "cluster")
        live.state.clock.now += timedelta(minutes=31)
        for _ in range(100):
            ws.receive_json()
    assert e.value.code == 4401


def test_accounts_only_see_their_own_jobs(live):
    _account(live, "amasha")
    _account(live, "hassan")
    a, h = _client(live, "amasha"), _client(live, "hassan")
    agent = live.state.agent
    agent.jobs_by_session[a.cookies["sd_session"]] = [{"job_id": "10", "user": "amasha"}]
    agent.jobs_by_session[h.cookies["sd_session"]] = [{"job_id": "20", "user": "hassan"}]
    with _ws(a) as wa, _ws(h) as wh:
        assert [j["job_id"] for j in _until(wa, "jobs")["jobs"]] == ["10"]
        assert [j["job_id"] for j in _until(wh, "jobs")["jobs"]] == ["20"]


def test_warned_jobs_get_a_banner(live):
    from sdweb.models import Account, Job

    _account(live, "amasha")
    c = _client(live, "amasha")
    with live.state.sessionmaker() as s, s.begin():
        me = s.query(Account).filter_by(username="amasha").one()
        s.add(Job(job_id="10", account_id=me.id, kind="batch", name="j", folder="/f", spec={},
                  script="", warned_at=datetime.now(UTC)))
    live.state.agent.jobs_by_session[c.cookies["sd_session"]] = [
        {"job_id": "10", "state": "RUNNING", "time_left_s": 25 * 60}]
    with _ws(c) as ws:
        assert _until(ws, "banner") == {"type": "banner", "job_id": "10", "minutes_left": 25}


def test_jobs_carry_their_kind(live):
    from sdweb.models import Account, Job

    _account(live, "amasha")
    c = _client(live, "amasha")
    with live.state.sessionmaker() as s, s.begin():
        me = s.query(Account).filter_by(username="amasha").one()
        s.add(Job(job_id="10", account_id=me.id, kind="notebook", name="j", folder="/f",
                  spec={}, script=""))
    live.state.agent.jobs_by_session[c.cookies["sd_session"]] = [
        {"job_id": "10", "state": "RUNNING"}, {"job_id": "11", "state": "RUNNING"}]
    with _ws(c) as ws:
        jobs = _until(ws, "jobs")["jobs"]
    assert [(j["job_id"], j["kind"]) for j in jobs] == [("10", "notebook"), ("11", "batch")]
