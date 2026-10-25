"""/api/admin passes the admin's session and body to deck-agent, and only admins get in."""

import pytest
from accounts_helpers import _account, _client

from sdweb.agent import AgentCallError

pytestmark = pytest.mark.pg


class AdminAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []

    def call(self, verb, payload=None, *, session=None):
        self.calls.append((verb, payload, session))
        if verb == "admin.drain" and not payload.get("reason"):
            raise AgentCallError("reason_required", "Give a reason.", 422)
        if verb == "admin.publish_shared":
            raise AgentCallError("exists", "A file with that name already exists there.", 409)
        return {"ok": True}


@pytest.fixture
def adm(env):
    app, _, _ = env
    app.state.agent = AdminAgent()
    _account(app, "amasha")
    _account(app, "dinuka", role="admin")
    return app.state.agent, _client(app, "amasha"), _client(app, "dinuka")


def test_only_admins_can_use_the_admin_api(adm):
    agent, user, admin = adm
    for path in ("/api/admin/qos", "/api/admin/pods", "/api/admin/service-status"):
        assert user.get(path).status_code == 403
        assert admin.get(path).status_code == 200
    drain = {"node": "gpu1", "reason": "x"}
    assert user.post("/api/admin/node/drain", json=drain).status_code == 403
    assert [c[0] for c in agent.calls] == ["admin.qos_list", "admin.pods", "admin.service_status"]


def test_writes_need_the_csrf_token(adm):
    _, _, admin = adm
    del admin.headers["X-CSRF-Token"]
    assert admin.post("/api/admin/node/resume", json={"node": "gpu1"}).status_code == 403


def test_the_body_and_session_reach_the_agent_and_its_errors_come_back(adm):
    agent, _, admin = adm
    body = {"node": "gpu1", "reason": "update", "cancel_running": False}
    assert admin.post("/api/admin/node/drain", json=body).status_code == 200
    assert agent.calls[-1] == ("admin.drain", body, admin.cookies["sd_session"])
    r = admin.post("/api/admin/node/drain", json={"node": "gpu1"})
    assert (r.status_code, r.json()["error"]) == (422, "reason_required")
    assert admin.post("/api/admin/shared/publish", json={"src": "/x"}).status_code == 409
