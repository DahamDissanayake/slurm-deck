"""/api/admin/settings: validated as a set, audited, and read by the live feed."""

import pytest
from accounts_helpers import _account, _client
from sqlalchemy import select, text
from test_live import _until, _ws, live  # noqa: F401  (live is a fixture)

from sdweb.models import AuditEvent, Setting

pytestmark = pytest.mark.pg


class SettingsAgent:
    def call(self, verb, payload=None, *, session=None):
        return {"partition_max_s": 86400}


@pytest.fixture(autouse=True)
def keep_the_seeded_settings(env):
    """Settings live in a table the shared fixture doesn't reset: put it back after each test."""
    app = env[0]
    with app.state.sessionmaker() as s:
        saved = [(k, v) for k, v in s.execute(text("SELECT key, value FROM settings"))]
    yield
    with app.state.sessionmaker() as s, s.begin():
        s.execute(text("DELETE FROM settings"))
        s.add_all([Setting(key=k, value=v) for k, v in saved])


@pytest.fixture
def adm(env):
    app, _, _ = env
    app.state.agent = SettingsAgent()
    _account(app, "amasha")
    _account(app, "dinuka", role="admin")
    return app, _client(app, "amasha"), _client(app, "dinuka")


def test_the_extension_cap_cannot_pass_the_partition_maximum(adm):
    _, _, admin = adm
    r = admin.put("/api/admin/settings", json={"extension_cap_hours": 25})
    assert r.status_code == 422 and r.json()["error"] == "bad_setting"
    assert admin.get("/api/admin/settings").json()["settings"]["extension_cap_hours"] == 24
    assert admin.put("/api/admin/settings", json={"extension_cap_hours": 12}).status_code == 200


def test_changes_are_saved_and_audited_with_old_and_new_values(adm):
    app, _, admin = adm
    r = admin.put("/api/admin/settings", json={"submit_rate_per_hour": 5, "disk_alert_percent": 85})
    assert r.json()["settings"]["submit_rate_per_hour"] == 5
    with app.state.sessionmaker() as s:
        events = {e.target: e.detail for e in s.scalars(
            select(AuditEvent).where(AuditEvent.action == "settings.change"))}
    assert events == {"submit_rate_per_hour": {"old": 20, "new": 5},
                      "disk_alert_percent": {"old": 90, "new": 85}}
    admin.put("/api/admin/settings", json={"submit_rate_per_hour": 5})   # no change, no event
    with app.state.sessionmaker() as s:
        changes = s.scalars(select(AuditEvent).where(AuditEvent.action == "settings.change"))
        assert len(changes.all()) == 2


def test_one_bad_value_saves_nothing(adm):
    _, _, admin = adm
    bad = {"disk_alert_percent": 80, "default_time_limit": "99:99"}
    r = admin.put("/api/admin/settings", json=bad)
    assert r.status_code == 422 and "default_time_limit" in r.json()["problems"]
    assert admin.get("/api/admin/settings").json()["settings"]["disk_alert_percent"] == 90


@pytest.mark.parametrize("body", [{"default_time_limit": "48:00:00"}, {"disk_alert_percent": 100},
                                  {"mail_enabled": "yes"}, {"maintenance_banner": "x" * 501},
                                  {"nonsense": 1}, {"submit_rate_per_hour": -1}])
def test_invalid_values_are_422(adm, body):
    assert adm[2].put("/api/admin/settings", json=body).status_code == 422


def test_only_admins_with_csrf_can_change_settings(adm):
    _, user, admin = adm
    assert user.get("/api/admin/settings").status_code == 403
    assert user.put("/api/admin/settings", json={"mail_enabled": False}).status_code == 403
    del admin.headers["X-CSRF-Token"]
    assert admin.put("/api/admin/settings", json={"mail_enabled": False}).status_code == 403


def test_the_maintenance_banner_reaches_the_live_cluster_message(live):  # noqa: F811
    _account(live, "amasha")
    _account(live, "dinuka", role="admin")
    admin = _client(live, "dinuka")
    assert admin.put("/api/admin/settings",
                     json={"maintenance_banner": "Down for an update at 22:00"}).status_code == 200
    with _ws(_client(live, "amasha")) as ws:
        assert _until(ws, "cluster")["maintenance"] == "Down for an update at 22:00"
