"""tus uploads at /api/uploads, against a fake deck-agent that keeps the bytes."""

import base64
import tracemalloc
from datetime import timedelta

import pytest
from accounts_helpers import _account, _client

from sdweb.agent import AgentCallError

pytestmark = pytest.mark.pg

MB = 1024 * 1024


class TusAgent:
    """Stores staged bytes per upload id; with count_only it only counts them."""

    def __init__(self, count_only: bool = False) -> None:
        self.staged: dict[str, bytearray] = {}
        self.sizes: dict[str, int] = {}
        self.finalized: dict[str, bytes] = {}
        self.calls: list[str] = []
        self.count_only = count_only

    def call(self, verb, payload=None, *, session=None):
        assert session
        self.calls.append(verb)
        uid = (payload or {}).get("upload_id", "")
        if verb == "fs.free_space":
            return {"free_bytes": 100 * 1024 * MB, "total_bytes": 200 * 1024 * MB}
        if verb in ("fs.upload_begin", "fs.upload_regrant"):
            self.staged.setdefault(uid, bytearray())
            self.sizes.setdefault(uid, 0)
            return {"grant": f"g-{uid}-{len(self.calls)}", "offset": self.sizes[uid]}
        if verb == "fs.upload_finalize":
            self.finalized[payload["filename"]] = bytes(self.staged.pop(uid))
            return {"path": f"{payload['dest_dir']}/{payload['filename']}"}
        if verb == "fs.upload_abort":
            self.staged.pop(uid, None)
            return {}
        raise AssertionError(verb)

    def upload_chunk(self, upload_id, offset, data, *, length, grant):
        assert grant.startswith(f"g-{upload_id}-")
        if offset != self.sizes[upload_id]:
            raise AgentCallError("offset_mismatch", "wrong offset", 409)
        for piece in data:
            if not self.count_only:
                self.staged[upload_id] += piece
            self.sizes[upload_id] += len(piece)
        return self.sizes[upload_id]


def _meta(**kv: str) -> str:
    return ",".join(f"{k} {base64.b64encode(v.encode()).decode()}" for k, v in kv.items())


@pytest.fixture
def tus(env):
    app, _, _ = env
    app.state.agent = TusAgent()
    _account(app, "amasha")
    _account(app, "kasun")
    return app, app.state.agent, _client(app, "amasha")


def _create(c, size, name="data.bin", dest="/shared/users/amasha"):
    r = c.post("/api/uploads", headers={"Tus-Resumable": "1.0.0", "Upload-Length": str(size),
                                         "Upload-Metadata": _meta(filename=name, dest_dir=dest)})
    assert r.status_code == 201, r.text
    return r.headers["Location"]


def _patch(c, url, offset, data, length=None):
    return c.patch(url, content=data, headers={
        "Tus-Resumable": "1.0.0", "Upload-Offset": str(offset),
        "Content-Length": str(len(data) if length is None else length),
        "Content-Type": "application/offset+octet-stream"})


def test_options_advertises_tus(tus):
    _, _, c = tus
    r = c.options("/api/uploads")
    assert r.headers["Tus-Version"] == "1.0.0"
    assert r.headers["Tus-Extension"] == "creation,termination"
    assert int(r.headers["Tus-Max-Size"]) == 99 * 1024 * MB


def test_three_chunk_upload_finalizes(tus):
    _, agent, c = tus
    data = bytes(range(256)) * 1000
    url = _create(c, len(data))
    assert url.startswith("/api/uploads/")
    parts = [data[:100_000], data[100_000:200_000], data[200_000:]]
    offset = 0
    for part in parts:
        r = _patch(c, url, offset, part)
        assert r.status_code == 204, r.text
        offset = int(r.headers["Upload-Offset"])
    assert offset == len(data)
    assert agent.finalized["data.bin"] == data
    assert c.get("/api/uploads?active=1").json()["uploads"] == []


def test_stale_offset_is_409(tus):
    _, _, c = tus
    url = _create(c, 10)
    assert _patch(c, url, 0, b"abcde").status_code == 204
    assert _patch(c, url, 0, b"abcde").status_code == 409


def test_head_reports_offset_and_active_list_offers_resume(tus):
    _, _, c = tus
    url = _create(c, 10)
    _patch(c, url, 0, b"abcd")
    r = c.head(url)
    assert (r.status_code, r.headers["Upload-Offset"], r.headers["Upload-Length"]) == (
        200, "4", "10")
    [up] = c.get("/api/uploads?active=1").json()["uploads"]
    assert (up["filename"], up["offset"], up["size"]) == ("data.bin", 4, 10)


def test_another_accounts_head_is_404(tus):
    app, _, c = tus
    url = _create(c, 10)
    assert _client(app, "kasun").head(url).status_code == 404


@pytest.mark.parametrize("hours, status", [(23, 200), (25, 404)])
def test_resume_window_is_24_hours(tus, hours, status):
    app, _, c = tus
    url = _create(c, 10)
    real = app.state.clock
    app.state.clock = lambda: real() + timedelta(hours=hours)
    try:
        c = _client(app, "amasha")   # a fresh sign-in at the later time
        assert c.head(url).status_code == status
        assert (_patch(c, url, 0, b"ab").status_code == 204) is (status == 200)
    finally:
        app.state.clock = real


def test_delete_aborts(tus):
    _, agent, c = tus
    url = _create(c, 10)
    assert c.delete(url, headers={"Tus-Resumable": "1.0.0"}).status_code == 204
    assert "fs.upload_abort" in agent.calls
    assert c.head(url).status_code == 404


def _asgi_patch(app, c, url, size, pieces):
    """PATCH straight through ASGI, the body arriving in pieces as a server
    would deliver it (TestClient reads the whole body into memory first)."""
    import anyio

    headers = [(b"host", b"testserver"), (b"tus-resumable", b"1.0.0"),
               (b"cookie", f"sd_session={c.cookies.get('sd_session')}".encode()),
               (b"x-csrf-token", c.headers["X-CSRF-Token"].encode()),
               (b"content-type", b"application/offset+octet-stream"),
               (b"upload-offset", b"0"), (b"content-length", str(size).encode())]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "PATCH", "scheme": "https", "path": url, "raw_path": url.encode(),
             "query_string": b"", "root_path": "", "headers": headers,
             "client": ("10.0.0.9", 50000), "server": ("testserver", 443)}
    it = iter(pieces)
    sent: list[dict] = []

    async def receive():
        piece = next(it, None)
        return {"type": "http.request", "body": piece or b"", "more_body": piece is not None}

    async def send(message):
        sent.append(message)

    anyio.run(app, scope, receive, send)
    return sent[0]


def test_patch_streams_64_mb_with_bounded_memory(tus):
    app, _, c = tus
    app.state.agent = TusAgent(count_only=True)
    size = 64 * MB
    url = _create(c, size)
    block = b"\0" * MB

    tracemalloc.start()
    try:
        start = _asgi_patch(app, c, url, size, (block for _ in range(64)))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert start["status"] == 204, start
    assert (b"upload-offset", str(size).encode()) in start["headers"]
    assert peak < 16 * MB
