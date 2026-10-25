"""/api/usage and the admin reports pass the caller's session to deck-agent."""

import pytest
from accounts_helpers import _account, _client

from sdweb.agent import AgentCallError

pytestmark = pytest.mark.pg


class UsageAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []

    def call(self, verb, payload=None, *, session=None):
        self.calls.append((verb, payload, session))
        if verb == "usage.personal" and payload["days"] not in (7, 30, 90):
            raise AgentCallError("bad_days", "Choose 7, 30 or 90 days.", 422)
        return {"usage.personal": {"days": payload.get("days"), "gpu_hours": 1.5},
                "usage.cluster": {"users": [], "total": {}},
                "admin.disk_usage": {"users": [], "total_bytes": 0}}[verb]


@pytest.fixture
def usage(env):
    app, _, _ = env
    app.state.agent = UsageAgent()
    _account(app, "amasha")
    _account(app, "dinuka", role="admin")
    return app.state.agent, _client(app, "amasha"), _client(app, "dinuka")


def test_personal_usage_goes_to_the_agent_with_the_session(usage):
    agent, user, _ = usage
    r = user.get("/api/usage?days=7")
    assert r.status_code == 200 and r.json()["gpu_hours"] == 1.5
    assert agent.calls[0] == ("usage.personal", {"days": 7}, user.cookies["sd_session"])


def test_a_bad_window_is_the_agents_422(usage):
    _, user, _ = usage
    r = user.get("/api/usage?days=10")
    assert r.status_code == 422 and r.json()["error"] == "bad_days"


def test_cluster_usage_and_disk_usage_are_admin_only(usage):
    agent, user, admin = usage
    for path in ("/api/admin/usage?days=30", "/api/admin/disk-usage"):
        assert user.get(path).status_code == 403
        assert admin.get(path).status_code == 200
    assert [c[0] for c in agent.calls] == ["usage.cluster", "admin.disk_usage"]
