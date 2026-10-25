"""/api/admin/settings: validated as a set, audited, and read by the live feed."""

import pytest
from accounts_helpers import _account, _client
from sqlalchemy import select, text
from test_live import _until, _ws, live  # noqa: F401  (live is a fixture)

from sdweb.models import AuditEvent, Setting

pytestmark = pytest.mark.pg
URL = "/api/admin/settings"


class SettingsAgent:
    def call(self, verb, payload=None, *, session=None):
        return {"partition_max_s": 86400}


@pytest.fixture(autouse=True)
def keep_the_seeded_settings(env):
    """The settings table isn't reset by the shared fixture: put it back after each test."""
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
    r = admin.put(URL, json={"extension_cap_hours": 25})
    assert r.status_code == 422 and r.json()["error"] == "bad_setting"
    assert admin.get(URL).json()["settings"]["extension_cap_hours"] == 24
    assert admin.put(URL, json={"extension_cap_hours": 12}).status_code == 200


def test_changes_are_audited_with_old_and_new_and_one_bad_value_saves_nothing(adm):
    app, _, admin = adm
    both = {"submit_rate_per_hour": 5, "disk_alert_percent": 85}
    assert admin.put(URL, json=both).status_code == 200
    admin.put(URL, json={"submit_rate_per_hour": 5})   # unchanged: no event
    with app.state.sessionmaker() as s:
        events = {e.target: e.detail for e in s.scalars(
            select(AuditEvent).where(AuditEvent.action == "settings.change"))}
    assert events == {"submit_rate_per_hour": {"old": 20, "new": 5},
                      "disk_alert_percent": {"old": 90, "new": 85}}
    bad = {"disk_alert_percent": 80, "default_time_limit": "99:99"}
    assert admin.put(URL, json=bad).status_code == 422
    assert admin.get(URL).json()["settings"]["disk_alert_percent"] == 85
    for body in ({"default_time_limit": "48:00:00"}, {"disk_alert_percent": 100},
                 {"mail_enabled": "yes"}, {"maintenance_banner": "x" * 501}, {"nonsense": 1}):
        assert admin.put(URL, json=body).status_code == 422, body


def test_only_admins_can_change_settings(adm):
    _, user, _ = adm
    assert user.get(URL).status_code == 403
    assert user.put(URL, json={"mail_enabled": False}).status_code == 403


def test_the_maintenance_banner_reaches_the_live_cluster_message(live):  # noqa: F811
    _account(live, "amasha")
    _account(live, "dinuka", role="admin")
    banner = {"maintenance_banner": "Down for an update at 22:00"}
    assert _client(live, "dinuka").put(URL, json=banner).status_code == 200
    with _ws(_client(live, "amasha")) as ws:
        assert _until(ws, "cluster")["maintenance"] == banner["maintenance_banner"]
