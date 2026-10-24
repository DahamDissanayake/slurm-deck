"""The session reverse proxy against a fake deck-agent and a real upstream
(a small uvicorn app on a free port that records what it was sent)."""

import socket
import threading
import time

import pytest
import uvicorn
from accounts_helpers import _account, _client
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from starlette.testclient import WebSocketDenialResponse

from sdweb.agent import AgentCallError
from sdweb.models import AuditEvent, Job

pytestmark = pytest.mark.pg


class Upstream:
    """Stands in for a notebook server: /notebook/42/... over HTTP and a WebSocket echo."""

    def __init__(self) -> None:
        self.last_headers: dict[str, str] = {}
        self.open_sockets = 0
        self.opened = 0
        app = FastAPI()

        @app.get("/notebook/42/redirect")
        def redirect(request: Request):
            return RedirectResponse(f"http://{request.headers['host']}/notebook/42/login")

        @app.get("/notebook/42/bare")
        def bare():
            return RedirectResponse("/login")

        @app.get("/notebook/42/{rest:path}")
        def get(rest: str, request: Request):
            self.last_headers = dict(request.headers)
            return JSONResponse({"rest": rest, "query": request.url.query})

        @app.websocket("/notebook/42/ws")
        async def echo(ws: WebSocket):
            await ws.accept()
            self.open_sockets += 1
            self.opened += 1
            self.last_headers = dict(ws.headers)
            try:
                while True:
                    await ws.send_text(await ws.receive_text())
            except WebSocketDisconnect:
                pass
            finally:
                self.open_sockets -= 1

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port,
                                                    log_level="error", ws="websockets"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        while not self.server.started:
            time.sleep(0.01)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(5)


class SessionAgent:
    """session.info for job 42: allowed per session token, like the real verb."""

    def __init__(self, port: int) -> None:
        self.port, self.allowed = port, set()
        self.state, self.ready, self.node = "RUNNING", True, "127.0.0.1"
        self.calls: list[str] = []

    def call(self, verb, payload=None, *, session=None):
        self.calls.append(verb)
        assert verb == "session.info" and payload == {"job_id": "42"}
        if session not in self.allowed:
            raise AgentCallError("not_found", "No such job.", 404)
        ready = self.state == "RUNNING" and self.ready
        return {"state": self.state, "ready": ready, "kind": "notebook",
                "node": self.node if ready else None, "port": self.port if ready else None,
                "token": "T" if ready else None}


@pytest.fixture
def upstream():
    up = Upstream()
    yield up
    up.stop()


@pytest.fixture
def proxy(env, upstream):
    app, _, _ = env
    agent = app.state.agent = SessionAgent(upstream.port)
    owner_id = _account(app, "amasha")
    _account(app, "dinuka", role="admin")
    _account(app, "kasun")
    with app.state.sessionmaker() as s, s.begin():
        s.add(Job(job_id="42", account_id=owner_id, kind="notebook", name="nb", folder="/f",
                  spec={}, script=""))
    clients = {n: _client(app, n) for n in ("amasha", "dinuka", "kasun")}
    agent.allowed = {clients[n].cookies["sd_session"] for n in ("amasha", "dinuka")}
    return app, agent, clients, upstream


def test_owner_proxied_with_token_and_without_our_cookie(proxy):
    _, _, c, up = proxy
    c["amasha"].cookies.set("other", "keep", domain="testserver.local")
    r = c["amasha"].get("/notebook/42/api/status?x=1")
    assert r.status_code == 200 and r.json() == {"rest": "api/status", "query": "x=1"}
    h = up.last_headers
    assert h["authorization"] == "token T"
    assert "sd_session" not in h.get("cookie", "") and "x-csrf-token" not in h
    assert h["host"] == f"127.0.0.1:{up.port}"


def test_other_user_403(proxy):
    _, _, c, up = proxy
    r = c["kasun"].get("/notebook/42/api/status")
    assert r.status_code == 403 and "This session belongs to someone else." in r.text
    assert up.last_headers == {}


def test_signed_out_goes_to_sign_in(proxy):
    from fastapi.testclient import TestClient

    app, _, _, _ = proxy
    r = TestClient(app, base_url="https://testserver").get(
        "/notebook/42/api/status", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/sign-in?next=")


def test_admin_allowed_and_audited(proxy):
    app, _, c, _ = proxy
    assert c["dinuka"].get("/notebook/42/api/status").status_code == 200
    assert c["dinuka"].get("/notebook/42/api/status").status_code == 200   # once an hour
    with app.state.sessionmaker() as s:
        rows = s.scalars(select(AuditEvent).where(AuditEvent.action == "session_open")).all()
        assert len(rows) == 1 and rows[0].target == "42"
        assert rows[0].actor_id is not None and rows[0].acting_admin_id == rows[0].actor_id
        assert rows[0].detail["owner"] == "amasha"


def test_not_ready_shows_starting_page(proxy):
    _, agent, c, _ = proxy
    agent.ready = False
    r = c["amasha"].get("/notebook/42/")
    assert r.status_code == 200 and "Starting your session…" in r.text
    assert 'http-equiv="refresh"' in r.text


def test_ended_job_shows_ended_page(proxy):
    _, agent, c, _ = proxy
    agent.state = "COMPLETED"
    r = c["amasha"].get("/notebook/42/")
    assert "This session has ended." in r.text and "Back to your jobs" in r.text


def test_upstream_down_shows_not_responding(proxy):
    _, agent, c, up = proxy
    up.stop()
    r = c["amasha"].get("/notebook/42/api/status")
    assert r.status_code == 502
    assert "The session isn't responding. It may still be starting, or it has stopped." in r.text
    assert 'href="/jobs/42"' in r.text


def test_location_rewritten(proxy):
    _, _, c, _ = proxy
    r = c["amasha"].get("/notebook/42/redirect", follow_redirects=False)
    assert r.headers["location"] == "https://deck.x.org/notebook/42/login"
    r = c["amasha"].get("/notebook/42/bare", follow_redirects=False)
    assert r.headers["location"] == "/notebook/42/login"


def test_other_kind_or_bad_job_id_is_refused(proxy):
    _, _, c, _ = proxy
    assert c["amasha"].get("/tensorboard/42/").status_code == 404   # session.info says notebook
    assert c["amasha"].get("/notebook/4x/").status_code == 404


def _ws(client):
    return client.websocket_connect(
        "/notebook/42/ws", headers={"cookie": f"sd_session={client.cookies['sd_session']}"})


def test_websocket_roundtrip_and_no_leak(proxy):
    _, _, c, up = proxy
    with _ws(c["amasha"]) as ws:
        ws.send_text("hello")
        assert ws.receive_text() == "hello"
        assert up.last_headers["authorization"] == "token T"
        assert "sd_session" not in up.last_headers.get("cookie", "")
    for i in range(100):
        with _ws(c["amasha"]) as ws:
            ws.send_text(str(i))
            assert ws.receive_text() == str(i)
    deadline = time.time() + 5
    while up.open_sockets and time.time() < deadline:
        time.sleep(0.05)
    assert up.opened == 101 and up.open_sockets == 0


def test_websocket_for_another_user_is_refused(proxy):
    _, _, c, up = proxy
    with pytest.raises(WebSocketDenialResponse) as e:
        with _ws(c["kasun"]):
            pass
    assert e.value.status_code == 403 and up.opened == 0
