"""static.mount: the built frontend, with index.html for app routes."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sdweb.static import mount


def _app(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("no")
    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict:
        return {"ok": True}

    mount(app, str(tmp_path))
    return TestClient(app)


def test_serves_files_and_index(tmp_path):
    c = _app(tmp_path)
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/").text == "<html>app</html>"


def test_unknown_app_paths_get_index(tmp_path):
    c = _app(tmp_path)
    r = c.get("/admin/users/7")
    assert r.status_code == 200 and r.text == "<html>app</html>"


def test_api_routes_win_and_unknown_api_paths_are_404(tmp_path):
    c = _app(tmp_path)
    assert c.get("/api/ping").json() == {"ok": True}
    assert c.get("/api/nope").status_code == 404
    assert c.get("/api").status_code == 404


def test_app_from_env_wires_the_agent_and_serves_the_frontend(tmp_path):
    from sdweb.agent import AgentClient
    from sdweb.app import create_app_from_env

    (tmp_path / "index.html").write_text("<html>app</html>")
    app = create_app_from_env({"SD_DATABASE_URL": "postgresql://u:p@db/x",
                               "SD_AGENT_SOCKET": "/run/x/agent.sock"}, static_dir=str(tmp_path))
    assert isinstance(app.state.agent, AgentClient)
    assert app.state.agent.socket_path == "/run/x/agent.sock"
    c = TestClient(app)
    assert c.get("/jobs").text == "<html>app</html>"
    assert c.get("/api/nope").status_code == 404


def test_app_from_env_without_a_built_frontend_still_starts(tmp_path):
    from sdweb.app import create_app_from_env

    app = create_app_from_env({"SD_DATABASE_URL": "postgresql://u:p@db/x"},
                              static_dir=str(tmp_path / "missing"))
    assert TestClient(app).get("/jobs").status_code == 404


def test_paths_outside_the_folder_are_not_served(tmp_path):
    c = _app(tmp_path)
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt"):
        assert "no" != c.get(path).text
