"""deck-agent socket server: errors never kill it, slow clients are cut off,
workers are bounded, and only the web and worker UIDs may connect.

A real AgentServer runs on a temp Unix socket. Callers come from a fake
resolver (session resolution is Task 6), and verbs from a private registry.
"""

import json as jsonlib
import os
import socket
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

if sys.platform != "linux":
    pytest.skip("deck-agent needs Linux (AF_UNIX + SO_PEERCRED)", allow_module_level=True)

from deckagent.config import load_config  # noqa: E402
from deckagent.protocol import AgentError, Caller  # noqa: E402
from deckagent.server import AgentServer  # noqa: E402
from deckagent.verbs import VerbRegistry  # noqa: E402

registry = VerbRegistry()


@registry.verb("echo", allow=frozenset({"user", "admin", "worker"}))
def _echo(ctx, payload):
    return payload


@registry.verb("boom", allow=frozenset({"user"}))
def _boom(ctx, payload):
    raise ValueError("handler bug")


@registry.verb("sleep", allow=frozenset({"user"}))
def _sleep(ctx, payload):
    time.sleep(2)
    return "slept"


@registry.verb("admin.only", allow=frozenset({"admin"}))
def _admin_only(ctx, payload):
    return ctx.caller.username


@registry.verb("conflict", allow=frozenset({"user"}))
def _conflict(ctx, payload):
    raise AgentError("busy", "Try again later.", 409)


@registry.verb("granted", allow=frozenset({"user"}), session=False)
def _granted(ctx, payload):
    # A grant-authorised handler names who it acted for once the grant checks out.
    ctx.audit.update(actor="amasha", target="upl-0001-amasha")
    if payload.get("fail"):
        raise AgentError("offset_mismatch", "Wrong offset.", 409)
    return "ok"


def _resolve(peer_uid, headers, store, config):
    token = headers.get("x-sd-session", "")
    if token == "admin":
        return Caller("dinuka", "admin", "web", False, None)
    if token:
        return Caller("amasha", "user", "web", False, None)
    raise AgentError("no_session", "Sign in again.", 401)


@dataclass
class Agent:
    path: str
    server: AgentServer


def _start(tmp_path: Path, **overrides: str) -> Iterator[Agent]:
    env = {"SD_AGENT_SOCKET": str(tmp_path / "agent.sock"), "SD_WEB_UID": str(os.getuid()),
           "SD_WORKER_UID": "1", "SD_REQUEST_DEADLINE_S": "3", "SD_MAX_WORKERS": "4",
           "SD_MAX_JSON_BYTES": "1024", "SD_AUDIT_LOG": str(tmp_path / "audit.jsonl"),
           **overrides}
    server = AgentServer(load_config(env), store=None, resolve=_resolve, verbs=registry)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Agent(env["SD_AGENT_SOCKET"], server)
    finally:
        server.shutdown()
        thread.join(5)


@pytest.fixture
def agent(tmp_path):
    yield from _start(tmp_path)


@pytest.fixture
def agent_with_uids_excluding_me(tmp_path):
    yield from _start(tmp_path, SD_WEB_UID="1", SD_WORKER_UID="2")


@dataclass
class Resp:
    status_code: int
    body: bytes

    def json(self):
        return jsonlib.loads(self.body)


def _connect(agent: Agent) -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect(agent.path)
    return s


def _read_response(s: socket.socket) -> Resp:
    data = b""
    while chunk := s.recv(65536):
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    return Resp(int(head.split()[1]) if head else 0, body)


def post(agent: Agent, verb: str, *, json=None, raw: bytes | None = None,
         session: str = "tok") -> Resp:
    body = raw if raw is not None else jsonlib.dumps(json).encode()
    s = _connect(agent)
    s.sendall(f"POST /v1/{verb} HTTP/1.1\r\nHost: agent\r\nX-SD-Session: {session}\r\n"
              f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
              .encode() + body)
    try:
        return _read_response(s)
    finally:
        s.close()


@pytest.mark.parametrize("body", [b'"x"', b"[1,2]", b"not json", b'{"a": 1'])
def test_non_object_body_is_400_and_server_survives(agent, body):
    r = post(agent, "echo", raw=body)
    assert r.status_code == 400 and r.json()["ok"] is False
    assert post(agent, "echo", json={"a": 1}).json() == {"ok": True, "data": {"a": 1}}


def test_handler_exception_is_500_and_server_survives(agent):
    r = post(agent, "boom", json={})
    assert r.status_code == 500
    assert r.json() == {"ok": False, "error": {"code": "internal",
                                               "message": "Something went wrong."}}
    assert post(agent, "echo", json={"b": 2}).status_code == 200


def test_agent_error_keeps_its_status_and_code(agent):
    r = post(agent, "conflict", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "busy"


def test_unknown_verb_404(agent):
    r = post(agent, "nope", json={})
    assert r.status_code == 404 and r.json()["error"]["code"] == "unknown_verb"


def test_wrong_role_is_403_and_no_session_is_401(agent):
    assert post(agent, "admin.only", json={}).status_code == 403
    assert post(agent, "admin.only", json={}, session="admin").json()["data"] == "dinuka"
    assert post(agent, "echo", json={}, session="").status_code == 401


def test_oversized_body_is_413(agent):
    assert post(agent, "echo", json={"x": "y" * 2000}).status_code == 413


@pytest.mark.parametrize("request_text", [
    "GET /v1/echo HTTP/1.1\r\n\r\n",                         # wrong method
    "POST /other HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}",   # wrong path
    "POST /v1/echo HTTP/1.1\r\n\r\n",                        # no Content-Length
    "garbage\r\n\r\n",
])
def test_malformed_requests_are_4xx(agent, request_text):
    s = _connect(agent)
    s.sendall(request_text.encode())
    status = _read_response(s).status_code
    s.close()
    assert 400 <= status < 500
    assert post(agent, "echo", json={}).status_code == 200


def test_slow_client_is_cut_off(agent):
    s = _connect(agent)
    start = time.monotonic()
    s.sendall(b"POST /v1/echo HTTP/1.1\r\nContent-Length: 100\r\n\r\n")
    try:
        while time.monotonic() - start < 10:
            time.sleep(2)
            s.sendall(b"x")              # one byte every 2 s keeps each read alive
    except OSError:
        pass                              # the server hung up on us
    elapsed = time.monotonic() - start
    s.close()
    assert elapsed < 6
    assert post(agent, "echo", json={}).status_code == 200


def test_slow_request_does_not_block_fast_one(agent):
    slow = threading.Thread(target=post, args=(agent, "sleep"), kwargs={"json": {}})
    slow.start()
    time.sleep(0.2)
    start = time.monotonic()
    assert post(agent, "echo", json={}).status_code == 200
    assert time.monotonic() - start < 0.5
    slow.join()


def test_wrong_peer_uid_refused(agent_with_uids_excluding_me):
    r = post(agent_with_uids_excluding_me, "echo", json={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "peer_not_allowed"


def test_socket_file_is_0660(agent):
    assert os.stat(agent.path).st_mode & 0o777 == 0o660


def test_config_defaults_and_required_uids():
    c = load_config({"SD_WEB_UID": "1001", "SD_WORKER_UID": "1002"})
    assert (c.nfs_root, c.ops_user, c.max_workers, c.request_deadline_s) == (
        "/shared", "sd-ops", 8, 30)
    assert c.stats_file == "/shared/.gpu_stats.json" and c.max_json_bytes == 1024 * 1024
    assert replace(c, partition="x").partition == "x"
    with pytest.raises(ValueError):
        load_config({"SD_WEB_UID": "1001"})
    with pytest.raises(ValueError):
        load_config({"SD_WEB_UID": "abc", "SD_WORKER_UID": "1002"})


def _audit_lines(agent: Agent) -> list[dict]:
    path = Path(agent.server.config.audit_log)
    return [jsonlib.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def test_server_audits_each_verb(agent):
    post(agent, "echo", json={"a": 1})
    post(agent, "admin.only", json={})
    post(agent, "conflict", json={}, session="admin")
    post(agent, "no.such", json={})
    got = [(x["verb"], x["actor"], x["result"]) for x in _audit_lines(agent)]
    assert got == [("echo", "amasha", "ok"), ("admin.only", "amasha", "not_allowed"),
                   ("conflict", "dinuka", "not_allowed"), ("no.such", None, "unknown_verb")]


def test_session_free_handler_reports_its_actor(agent):
    post(agent, "granted", json={}, session="")
    post(agent, "granted", json={"fail": True}, session="")
    got = [(x["verb"], x["actor"], x["target"], x["detail"]["role"], x["result"])
           for x in _audit_lines(agent)]
    assert got == [("granted", "amasha", "upl-0001-amasha", "grant", "ok"),
                   ("granted", "amasha", "upl-0001-amasha", "grant", "offset_mismatch")]


def test_refused_peer_is_audited(agent_with_uids_excluding_me):
    post(agent_with_uids_excluding_me, "echo", json={})
    [line] = _audit_lines(agent_with_uids_excluding_me)
    assert (line["verb"], line["result"], line["detail"]["peer_uid"]) == ("", "peer_not_allowed",
                                                                          os.getuid())
