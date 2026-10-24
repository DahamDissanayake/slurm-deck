"""The files API against a fake deck-agent."""

import anyio
import pytest
from accounts_helpers import _account, _client

pytestmark = pytest.mark.pg

HOME = "/shared/users/amasha"


class FilesAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.files: dict[str, bytes] = {f"{HOME}/a.txt": b"hello",
                                        f"{HOME}/t.csv": b"x,y\n" + b"1,2\n" * 80,
                                        f"{HOME}/p.png": b"\x89PNG....",
                                        f"{HOME}/big.log": b"z" * 100_000}
        self.closed = 0

    def call(self, verb, payload=None, *, session=None):
        assert session
        self.calls.append((verb, payload))
        if verb == "fs.stat":
            path = payload["path"]
            if path in self.files:
                return {"name": path.rsplit("/", 1)[1], "type": "file",
                        "size": len(self.files[path])}
            return {"name": path.rsplit("/", 1)[1], "type": "dir", "size": 0}
        if verb == "fs.list":
            return {"entries": [{"name": "a.txt", "type": "file", "size": 5}]}
        return {}

    def stream_with_headers(self, verb, payload=None, *, session=None):
        self.calls.append((verb, payload))
        data = self.files.get(payload["path"], b"PK zip bytes")
        start = int(payload.get("offset") or 0)
        data = data[start:start + int(payload.get("limit") or len(data))]

        def body():
            try:
                for i in range(0, max(len(data), 1), 4):
                    yield data[i:i + 4]
            finally:
                self.closed += 1
        return {}, body()


@pytest.fixture
def files(env):
    app, _, _ = env
    app.state.agent = FilesAgent()
    _account(app, "amasha")
    _account(app, "dinuka", role="admin")
    return app, app.state.agent, _client(app, "amasha")


def test_download_filename_encoding(files):
    _, _, c = files
    path = f"{HOME}/résumé #1 100%.txt"
    r = c.get("/api/files/download", params={"path": path})
    cd = r.headers["Content-Disposition"]
    assert "filename*=UTF-8''r%C3%A9sum%C3%A9%20%231%20100%25.txt" in cd
    assert cd.startswith("attachment; ") and 'filename="r_sum_ #1 100_.txt"' in cd


def test_folder_downloads_as_zip(files):
    _, agent, c = files
    r = c.get("/api/files/download", params={"path": f"{HOME}/runs"})
    assert "filename*=UTF-8''runs.zip" in r.headers["Content-Disposition"]
    assert ("fs.download_stream", {"path": f"{HOME}/runs", "as_admin": False}) in agent.calls


def test_client_disconnect_stops_the_agent_stream(files):
    app, agent, c = files
    agent.files[f"{HOME}/huge.bin"] = b"x" * 4000
    url = f"/api/files/download?path={HOME}/huge.bin"
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "GET", "scheme": "https", "path": "/api/files/download",
             "raw_path": b"/api/files/download", "root_path": "",
             "query_string": url.split("?", 1)[1].encode(),
             "headers": [(b"host", b"testserver"),
                         (b"cookie", f"sd_session={c.cookies.get('sd_session')}".encode())],
             "client": ("10.0.0.9", 50000), "server": ("testserver", 443)}
    got_body = anyio.Event()
    pieces = 0

    async def receive():
        await got_body.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        nonlocal pieces
        if message["type"] == "http.response.body":
            pieces += 1
            got_body.set()
            if pieces > 1:
                raise OSError("client went away")

    async def run():
        with anyio.move_on_after(5):
            try:
                await app(scope, receive, send)
            except OSError:
                pass
    anyio.run(run)
    assert pieces < 1000 and agent.closed == 1


def test_non_admin_user_param_is_403(files):
    _, agent, c = files
    for url in ("/api/files", "/api/files/stat", "/api/files/download", "/api/files/roots"):
        assert c.get(url, params={"path": "/shared/users/kasun", "user": "kasun"}) \
            .status_code == 403
    assert not [v for v, _ in agent.calls if v.startswith("fs.")]


def test_admin_user_param_runs_as_admin(files):
    app, agent, _ = files
    admin = _client(app, "dinuka")
    r = admin.get("/api/files", params={"path": "/shared/users/kasun", "user": "kasun"})
    assert r.status_code == 200
    assert ("fs.list", {"path": "/shared/users/kasun", "as_admin": True}) in agent.calls
    roots = admin.get("/api/files/roots", params={"user": "kasun"}).json()["roots"]
    assert roots[0]["path"].endswith("/users/kasun")


def test_roots(files):
    _, _, c = files
    roots = {r["label"]: r for r in c.get("/api/files/roots").json()["roots"]}
    assert roots["My files"]["path"] == HOME and roots["My files"]["writable"]
    assert roots["My job outputs"]["path"] == "/shared/jobs/amasha"
    assert not roots["Shared datasets"]["writable"]


def test_text_put_over_1_mib_is_413(files):
    _, agent, c = files
    r = c.put("/api/files/text", params={"path": f"{HOME}/a.txt"},
              content=b"x" * (1024 * 1024 + 1), headers={"Content-Type": "text/plain"})
    assert r.status_code == 413
    assert not [v for v, _ in agent.calls if v == "fs.write"]


def test_text_get_and_put(files):
    _, agent, c = files
    assert c.get("/api/files/text", params={"path": f"{HOME}/a.txt"}).json() == {"text": "hello"}
    r = c.put("/api/files/text", params={"path": f"{HOME}/a.txt"}, content="hi ✓".encode(),
              headers={"Content-Type": "text/plain"})
    assert r.status_code == 200
    assert ("fs.write", {"path": f"{HOME}/a.txt", "text": "hi ✓"}) in agent.calls


def test_previews(files):
    _, _, c = files
    table = c.get("/api/files/preview", params={"path": f"{HOME}/t.csv"}).json()
    assert table["kind"] == "table" and len(table["rows"]) == 50 and table["rows"][0] == ["x", "y"]
    text = c.get("/api/files/preview", params={"path": f"{HOME}/big.log"}).json()
    assert text["kind"] == "text" and len(text["text"]) == 64 * 1024 and text["truncated"]
    img = c.get("/api/files/preview", params={"path": f"{HOME}/p.png"})
    assert img.headers["content-type"] == "image/png" and img.content == b"\x89PNG...."


def test_writes_need_csrf_and_pass_through(files):
    app, agent, c = files
    body = {"src": f"{HOME}/a.txt", "dst": f"{HOME}/b.txt"}
    assert c.post("/api/files/rename", json=body).status_code == 200
    assert ("fs.rename", body) in agent.calls
    c.post("/api/files/mkdir", json={"path": f"{HOME}/new"})
    c.post("/api/files/delete", json={"path": f"{HOME}/new", "recursive": True})
    c.post("/api/files/extract", json={"archive": f"{HOME}/x.zip", "dest_dir": HOME})
    verbs = [v for v, _ in agent.calls]
    assert {"fs.mkdir", "fs.delete", "fs.extract"} <= set(verbs)
    del c.headers["X-CSRF-Token"]
    assert c.post("/api/files/mkdir", json={"path": f"{HOME}/x"}).status_code == 403
