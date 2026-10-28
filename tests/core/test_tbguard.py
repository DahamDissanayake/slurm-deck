"""The token guard in front of TensorBoard: no X-SD-Token, no access."""

import http.client
import http.server
import threading
from collections.abc import Iterator

import pytest

from sdcore.tbguard import make_server

TOKEN = "f00d" * 12


class _Upstream(http.server.BaseHTTPRequestHandler):
    seen_headers: list[dict[str, str]] = []

    def do_GET(self) -> None:
        _Upstream.seen_headers.append(dict(self.headers))
        body = b"hello from tensorboard"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        data = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(201)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        pass


def _serve(server: http.server.HTTPServer) -> threading.Thread:
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t


@pytest.fixture
def guard() -> Iterator[int]:
    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    _serve(upstream)
    server = make_server(("127.0.0.1", 0), ("127.0.0.1", upstream.server_address[1]), TOKEN)
    _serve(server)
    yield server.server_address[1]
    server.shutdown()
    upstream.shutdown()


def _get(port: int, headers: dict[str, str], method: str = "GET",
         body: bytes | None = None) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, "/tensorboard/42/data/runs", body=body, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def test_tbguard_rejects_missing_token(guard):
    assert _get(guard, {})[0] == 401


def test_tbguard_rejects_wrong_token(guard):
    assert _get(guard, {"X-SD-Token": "nope"})[0] == 401


def test_tbguard_forwards_with_the_token_and_strips_it(guard):
    _Upstream.seen_headers.clear()
    status, body = _get(guard, {"X-SD-Token": TOKEN})
    assert (status, body) == (200, b"hello from tensorboard")
    assert all("X-SD-Token" not in h for h in _Upstream.seen_headers)


def test_tbguard_forwards_request_bodies(guard):
    status, body = _get(guard, {"X-SD-Token": TOKEN, "Content-Type": "application/json"},
                        method="POST", body=b'{"a": 1}')
    assert (status, body) == (201, b'{"a": 1}')


def test_tbguard_reports_a_dead_upstream():
    server = make_server(("127.0.0.1", 0), ("127.0.0.1", 1), TOKEN)
    _serve(server)
    try:
        assert _get(server.server_address[1], {"X-SD-Token": TOKEN})[0] == 502
    finally:
        server.shutdown()


def test_tbguard_needs_a_token():
    with pytest.raises(ValueError):
        make_server(("127.0.0.1", 0), ("127.0.0.1", 1), "")
