"""/api/admin audit, agent log, mail log and services."""

import time

import pytest
from accounts_helpers import _account, _client
from sqlalchemy import text

from sdweb.mail import MAIL_DISABLED
from sdweb.models import AuditEvent, OutboxMessage

pytestmark = pytest.mark.pg


class MonitorAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call(self, verb, payload=None, *, session=None):
        self.calls.append((verb, payload))
        return {"admin.audit_tail": {"events": [{"ts": "2026-10-25T10:00:00+00:00", "verb": "x"}]},
                "admin.service_status": {"login": {"munge": "active"}, "gpu": {}, "gpu_error": ""},
                }[verb]


@pytest.fixture
def mon(env):
    app, _, _ = env
    with app.state.sessionmaker() as s, s.begin():
        s.execute(text("TRUNCATE outbox"))
    app.state.agent = MonitorAgent()
    _account(app, "amasha")
    _account(app, "dinuka", role="admin")
    return app, app.state.agent, _client(app, "amasha"), _client(app, "dinuka")


def _audit(app, *rows):
    with app.state.sessionmaker() as s, s.begin():
        for actor, action in rows:
            from sdweb.models import Account
            who = s.query(Account).filter_by(username=actor).one().id if actor else None
            s.add(AuditEvent(actor_id=who, action=action, target="t", result="ok", source="web"))


def test_the_audit_trail_filters_by_actor_and_action_and_pages(mon):
    app, _, _, admin = mon
    _audit(app, ("amasha", "job.cancel"), ("amasha", "file.delete"), ("dinuka", "job.cancel"),
           ("dinuka", "settings.change"))
    ev = admin.get("/api/admin/audit?actor=amasha&action=job").json()["events"]
    assert [(e["action"], e["actor"]) for e in ev] == [("job.cancel", "amasha")]
    assert len(admin.get("/api/admin/audit?action=job").json()["events"]) == 2
    first = admin.get("/api/admin/audit?action=job&page_size=1").json()
    assert len(first["events"]) == 1 and first["has_more"]
    last = admin.get("/api/admin/audit?action=job&page_size=1&page=2").json()
    assert len(last["events"]) == 1 and not last["has_more"]
    assert admin.get("/api/admin/audit?from=not-a-date").status_code == 422


def test_the_first_page_of_100000_audit_rows_comes_back_in_under_a_second(mon):
    app, _, _, admin = mon
    with app.state.sessionmaker() as s, s.begin():
        s.execute(text("INSERT INTO audit_events (ts, action, result, source) "
                       "SELECT now() - make_interval(secs => g), 'job.' || (g % 7), 'ok', 'web' "
                       "FROM generate_series(1, 100000) g"))
        s.execute(text("ANALYZE audit_events"))
    start = time.perf_counter()
    r = admin.get("/api/admin/audit?page_size=50")
    assert r.status_code == 200 and len(r.json()["events"]) == 50
    assert time.perf_counter() - start < 1.0
    assert admin.get("/api/admin/audit?action=job.3&page_size=50").json()["has_more"]


def test_the_mail_log_shows_each_state(mon):
    app, _, _, admin = mon
    from datetime import UTC, datetime
    with app.state.sessionmaker() as s, s.begin():
        for subject, sent, err in (("a", datetime.now(UTC), None), ("b", None, None),
                                   ("c", None, "smtp refused"), ("d", None, MAIL_DISABLED)):
            s.add(OutboxMessage(to_addr="x@x.org", subject=subject, html="", text="", kind="k",
                                sent_at=sent, last_error=err))
    seen = {m["subject"]: m["status"] for m in admin.get("/api/admin/mail-log").json()["mail"]}
    assert seen == {"a": "sent", "b": "pending", "c": "failed", "d": "disabled"}
    only = admin.get("/api/admin/mail-log?status=failed").json()["mail"]
    assert [m["subject"] for m in only] == ["c"]
    assert admin.get("/api/admin/mail-log?status=nope").status_code == 422


def test_the_agent_log_and_services_come_from_deck_agent_and_only_admins_see_them(mon):
    _, agent, user, admin = mon
    r = admin.get("/api/admin/agent-audit?since=2026-10-25T00:00:00&limit=20").json()
    assert r["events"][0]["verb"] == "x"
    assert agent.calls[0] == ("admin.audit_tail", {"since_ts": "2026-10-25T00:00:00", "limit": 20})
    assert admin.get("/api/admin/services").json()["login"] == {"munge": "active"}
    for path in ("/audit", "/agent-audit", "/mail-log", "/services"):
        assert user.get(f"/api/admin{path}").status_code == 403
