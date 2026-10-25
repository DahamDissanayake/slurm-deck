"""The session reverse proxy against a fake deck-agent and a real upstream
(a small uvicorn app on a free port that records what it was sent).

The app origin (https://testserver here) checks the session and ownership and
hands the browser to the session origin (SD_SESSION_HOSTNAME, by default
sessions.<public hostname>) with a one-time code. Only the session origin
serves the job's pages, so they never share an origin with the app."""

import socket
import threading
import time
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest
import uvicorn
from accounts_helpers import _account, _client
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect as Disconnect

from sdweb.agent import AgentCallError
from sdweb.models import AuditEvent, Job

pytestmark = pytest.mark.pg

APP = "https://deck.x.org"                 # SD_PUBLIC_HOSTNAME in the test settings
S = "https://sessions.deck.x.org"          # the default session hostname
PROXY_COOKIE = "sd_proxy"


class Upstream:
    """Stands in for a notebook server: /notebook/42/... over HTTP and a WebSocket echo,
    plus the two terminal endpoints the app's own terminal page uses."""

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

        @app.get("/notebook/42/hostile")
        def hostile():
            # What a user's own job could send back to whoever opens it (SLURM-49 finding 1).
            r = JSONResponse({"ok": True})
            r.set_cookie("sd_session", "attacker-token", path="/")
            r.headers["Service-Worker-Allowed"] = "/"
            r.headers["Clear-Site-Data"] = '"cookies"'
            return r

        @app.get("/notebook/42/{rest:path}")
        def get(rest: str, request: Request):
            self.last_headers = dict(request.headers)
            return JSONResponse({"rest": rest, "query": request.url.query})

        @app.post("/terminal/42/api/terminals")
        def new_terminal(request: Request):
            self.last_headers = dict(request.headers)
            r = HTMLResponse('{"name": "1"}')   # served as HTML: the app must not pass that on
            r.set_cookie("sd_session", "attacker-token", path="/")
            return r

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

        app.add_api_websocket_route("/notebook/42/ws", echo)
        app.add_api_websocket_route("/terminal/42/terminals/websocket/{name}", echo)

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
        self.state, self.ready, self.node, self.kind = "RUNNING", True, "127.0.0.1", "notebook"
        self.calls: list[str] = []

    def call(self, verb, payload=None, *, session=None):
        self.calls.append(verb)
        assert verb == "session.info" and payload == {"job_id": "42"}
        if session not in self.allowed:
            raise AgentCallError("not_found", "No such job.", 404)
        ready = self.state == "RUNNING" and self.ready
        return {"state": self.state, "ready": ready, "kind": self.kind,
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


def _ticket(client, kind="notebook"):
    return client.cookies.get(PROXY_COOKIE, domain="sessions.deck.x.org", path=f"/{kind}/42/")


# --- the hand-over from the app origin to the session origin -----------------------------

def test_owner_is_handed_to_the_session_origin_and_proxied(proxy):
    _, _, c, up = proxy
    r = c["amasha"].get("/notebook/42/api/status?x=1")
    assert r.status_code == 200 and r.json() == {"rest": "api/status", "query": "x=1"}
    assert str(r.url) == f"{S}/notebook/42/api/status?x=1"
    first = r.history[0]
    assert first.status_code == 302 and first.headers["location"].startswith(f"{S}/_sd/enter?")
    h = up.last_headers
    assert h["authorization"] == "token T"
    assert "sd_session" not in h.get("cookie", "") and PROXY_COOKIE not in h.get("cookie", "")
    assert "x-csrf-token" not in h and h["host"] == f"127.0.0.1:{up.port}"
    assert h["origin"] == S


def test_ticket_cookie_is_scoped_to_the_job_on_the_session_origin(proxy):
    _, _, c, _ = proxy
    r = c["amasha"].get("/notebook/42/api/status", follow_redirects=False)
    r = c["amasha"].get(r.headers["location"], follow_redirects=False)
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{PROXY_COOKIE}=") and "Path=/notebook/42/" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert "Domain" not in cookie
    assert r.headers["location"] == "/notebook/42/api/status"


def test_platform_cookie_never_reaches_the_session_origin(proxy):
    _, _, c, up = proxy
    c["amasha"].get("/notebook/42/api/status")
    jar = {(k.domain, k.name) for k in c["amasha"].cookies.jar}
    assert ("sessions.deck.x.org", "sd_session") not in jar
    assert all(not (d.endswith("deck.x.org") and n == "sd_session") for d, n in jar)


def test_session_origin_serves_only_sessions(proxy):
    _, _, c, _ = proxy
    c["amasha"].get("/notebook/42/api/status")
    for path in ("/api/auth/me", "/", "/jobs", "/api/jobs", "/ws/live"):
        assert c["amasha"].get(f"{S}{path}", follow_redirects=False).status_code == 404


def test_api_on_the_session_origin_never_answers_even_with_the_app_cookie(proxy):
    """Job pages can't read /api/auth/me: there is no app API on their origin at all."""
    _, _, c, _ = proxy
    raw = c["dinuka"].cookies["sd_session"]
    r = c["dinuka"].get(f"{S}/api/auth/me", headers={"cookie": f"sd_session={raw}"})
    assert r.status_code == 404 and "csrf_token" not in r.text


def test_code_is_single_use_and_must_match_its_job(proxy):
    _, _, c, _ = proxy
    enter = c["amasha"].get("/notebook/42/", follow_redirects=False).headers["location"]
    code = parse_qs(urlsplit(enter).query)["code"][0]
    wrong = f"{S}/_sd/enter?code={code}&next=/notebook/43/"
    assert c["amasha"].get(wrong, follow_redirects=False).status_code == 400
    enter = c["amasha"].get("/notebook/42/", follow_redirects=False).headers["location"]
    assert c["amasha"].get(enter, follow_redirects=False).status_code == 302
    r = c["amasha"].get(enter, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{APP}/notebook/42/"


def test_no_ticket_goes_back_to_the_app(proxy):
    _, _, c, up = proxy
    r = c["kasun"].get(f"{S}/notebook/42/api/x?y=1", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{APP}/notebook/42/api/x?y=1"
    assert c["kasun"].post(f"{S}/notebook/42/api/x").status_code == 403
    assert up.last_headers == {}


def test_ticket_ends_with_the_platform_session(proxy):
    _, _, c, _ = proxy
    assert c["amasha"].get("/notebook/42/api/status").status_code == 200
    assert c["amasha"].post("/api/auth/logout").status_code == 200
    r = c["amasha"].get(f"{S}/notebook/42/api/status", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith(APP)


def test_ticket_is_only_good_for_its_own_job(proxy):
    _, _, c, _ = proxy
    c["amasha"].get("/notebook/42/api/status")
    ticket = _ticket(c["amasha"])
    r = c["amasha"].get(f"{S}/tensorboard/42/", headers={"cookie": f"{PROXY_COOKIE}={ticket}"},
                        follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{APP}/tensorboard/42/"


# --- ownership and pages on the app origin ------------------------------------------------

def test_other_user_403_and_gets_no_ticket(proxy):
    _, _, c, up = proxy
    r = c["kasun"].get("/notebook/42/api/status", follow_redirects=False)
    assert r.status_code == 403 and "This session belongs to someone else." in unescape(r.text)
    assert up.last_headers == {} and _ticket(c["kasun"]) is None


def test_signed_out_goes_to_sign_in(proxy):
    from fastapi.testclient import TestClient

    app, _, _, _ = proxy
    r = TestClient(app, base_url="https://testserver").get(
        "/notebook/42/api/status", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/sign-in?next=")


def test_admin_allowed_and_audited(proxy):
    app, _, c, _ = proxy
    assert c["dinuka"].get("/notebook/42/api/status").status_code == 200
    assert c["dinuka"].get(f"{S}/notebook/42/api/status").status_code == 200   # once an hour
    with app.state.sessionmaker() as s:
        rows = s.scalars(select(AuditEvent).where(AuditEvent.action == "session_open")).all()
        assert len(rows) == 1 and rows[0].target == "42"
        assert rows[0].actor_id is not None and rows[0].acting_admin_id == rows[0].actor_id
        assert rows[0].detail["owner"] == "amasha"


def test_not_ready_shows_starting_page(proxy):
    _, agent, c, _ = proxy
    agent.ready = False
    r = c["amasha"].get("/notebook/42/", follow_redirects=False)
    assert r.status_code == 200 and "Starting your session…" in r.text
    assert 'http-equiv="refresh"' in r.text and _ticket(c["amasha"]) is None


def test_ended_job_shows_ended_page(proxy):
    _, agent, c, _ = proxy
    agent.state = "COMPLETED"
    r = c["amasha"].get("/notebook/42/")
    assert "This session has ended." in unescape(r.text) and "Back to your jobs" in r.text


def test_other_kind_or_bad_job_id_is_refused(proxy):
    _, _, c, _ = proxy
    assert c["amasha"].get("/tensorboard/42/").status_code == 404   # session.info says notebook
    assert c["amasha"].get("/notebook/4x/").status_code == 404


def test_app_origin_never_serves_job_pages(proxy):
    """Only GET hands over; any other method on the app origin is refused before
    the job sees it (the terminal page's two API calls are the exception, below)."""
    _, _, c, up = proxy
    assert c["amasha"].post("/notebook/42/api/contents").status_code == 404
    assert c["amasha"].put("/notebook/42/api/contents/x").status_code == 404
    assert up.last_headers == {}


# --- what the job sends back ---------------------------------------------------------------

def test_job_cannot_set_platform_cookie_or_service_worker_scope(proxy):
    """An admin opening a user's session must not get the job's cookies or
    origin-wide headers (SLURM-49 finding 1)."""
    _, _, c, _ = proxy
    admin = c["dinuka"]
    own_token = admin.cookies["sd_session"]
    r = admin.get("/notebook/42/hostile")
    assert r.status_code == 200 and str(r.url).startswith(S)
    assert "sd_session" not in r.headers.get("set-cookie", "")
    assert "service-worker-allowed" not in r.headers
    assert "clear-site-data" not in r.headers
    assert admin.cookies["sd_session"] == own_token


def test_upstream_down_shows_not_responding(proxy):
    _, _, c, up = proxy
    c["amasha"].get("/notebook/42/api/status")
    up.stop()
    r = c["amasha"].get(f"{S}/notebook/42/api/status")
    assert r.status_code == 502
    msg = "The session isn\'t responding. It may still be starting, or it has stopped."
    assert msg in unescape(r.text)
    assert f'href="{APP}/jobs/42"' in r.text


def test_location_rewritten(proxy):
    _, _, c, _ = proxy
    c["amasha"].get("/notebook/42/api/status")
    r = c["amasha"].get(f"{S}/notebook/42/redirect", follow_redirects=False)
    assert r.headers["location"] == f"{S}/notebook/42/login"
    r = c["amasha"].get(f"{S}/notebook/42/bare", follow_redirects=False)
    assert r.headers["location"] == "/notebook/42/login"


# --- the app's own terminal page (app origin, API only) ---------------------------------

def test_terminal_page_api_is_passed_through_as_json_only(proxy):
    _, agent, c, up = proxy
    agent.kind = "terminal"
    r = c["amasha"].post("/terminal/42/api/terminals")
    assert r.status_code == 200 and r.json() == {"name": "1"}
    assert r.headers["content-type"] == "application/json"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in r.headers["content-security-policy"]
    assert "set-cookie" not in r.headers
    assert up.last_headers["authorization"] == "token T" and up.last_headers["origin"] == S


def test_terminal_api_is_terminal_jobs_only(proxy):
    _, _, c, up = proxy   # job 42 is a notebook
    assert c["amasha"].post("/terminal/42/api/terminals").status_code == 404
    assert up.last_headers == {}


def test_terminal_page_websocket_on_the_app_origin(proxy):
    _, agent, c, up = proxy
    agent.kind = "terminal"
    raw = c["amasha"].cookies["sd_session"]
    with c["amasha"].websocket_connect("/terminal/42/terminals/websocket/1",
                                       headers={"cookie": f"sd_session={raw}"}) as ws:
        ws.send_text('["stdin", "ls"]')
        assert ws.receive_text() == '["stdin", "ls"]'
        assert up.last_headers["origin"] == S and up.last_headers["authorization"] == "token T"


# --- WebSockets on the session origin -------------------------------------------------------

def _ws(client, ticket):
    return client.websocket_connect(f"{S.replace('https', 'wss')}/notebook/42/ws",
                                    headers={"cookie": f"{PROXY_COOKIE}={ticket}"})


def test_websocket_roundtrip_and_no_leak(proxy):
    _, _, c, up = proxy
    c["amasha"].get("/notebook/42/api/status")
    ticket = _ticket(c["amasha"])
    with _ws(c["amasha"], ticket) as ws:
        ws.send_text("hello")
        assert ws.receive_text() == "hello"
        assert up.last_headers["authorization"] == "token T"
        assert PROXY_COOKIE not in up.last_headers.get("cookie", "")
    for i in range(100):
        with _ws(c["amasha"], ticket) as ws:
            ws.send_text(str(i))
            assert ws.receive_text() == str(i)
    deadline = time.time() + 5
    while up.open_sockets and time.time() < deadline:
        time.sleep(0.05)
    assert up.opened == 101 and up.open_sockets == 0


def test_websocket_without_a_ticket_is_refused(proxy):
    _, _, c, up = proxy
    with pytest.raises(Disconnect) as e:   # closed before accept: a real server answers 403
        with _ws(c["kasun"], "forged"):
            pass
    assert e.value.code == 1008 and up.opened == 0


def test_notebook_websocket_on_the_app_origin_is_refused(proxy):
    _, _, c, up = proxy
    raw = c["amasha"].cookies["sd_session"]
    with pytest.raises(Disconnect) as e:
        with c["amasha"].websocket_connect("/notebook/42/ws",
                                           headers={"cookie": f"sd_session={raw}"}):
            pass
    assert e.value.code == 1008 and up.opened == 0
