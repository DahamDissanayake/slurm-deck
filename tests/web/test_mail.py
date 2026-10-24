"""Mail: escaped templates, the outbox, the worker's retries and the senders."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from sdweb.config import load_settings
from sdweb.mail import templates
from sdweb.mail.senders import NullSender, ResendSender, SmtpSender, sender_for

SETTINGS = load_settings({"SD_DATABASE_URL": "postgresql://db/sd", "SD_CLUSTER_NAME": "IIT GPU",
                          "SD_CLUSTER_TZ": "Asia/Colombo", "SD_MAIL_FROM": "deck@x.org",
                          "SD_PUBLIC_HOSTNAME": "deck.x.org"})
NOW = datetime(2026, 10, 24, 6, 0, tzinfo=UTC)
LINK = "https://deck.x.org/set-password?token=abc&x=1"


def test_values_are_escaped():
    app = {"full_name": "<script>x</script>", "email": "a@x.com", "role_title": "Student",
           "organisation": "IIT", "contact_number": "077", "reason": "Train <b>models</b>"}
    subject, html, text = templates.render("application_received_admin",
                                           {"application": app}, SETTINGS)
    assert "<script>" not in html and "&lt;script&gt;x&lt;/script&gt;" in html
    assert "&lt;b&gt;models&lt;/b&gt;" in html
    assert "<script>x</script>" in text          # plain text stays as typed
    assert "\n" not in subject and "IIT GPU" in subject


def test_link_is_escaped_in_html_and_plain_in_text():
    _, html, text = templates.render("set_password", {"link": LINK}, SETTINGS)
    assert 'href="https://deck.x.org/set-password?token=abc&amp;x=1"' in html
    assert LINK in text


@pytest.mark.parametrize("kind", ["set_password", "reset_password", "application_approved"])
def test_set_and_reset_mails_carry_the_link_and_no_password(kind):
    subject, html, text = templates.render(kind, {"link": LINK}, SETTINGS)
    assert LINK in text and "token=abc&amp;x=1" in html
    with pytest.raises(ValueError, match="password"):
        templates.render(kind, {"link": LINK, "password": "hunter2hunter2"}, SETTINGS)


def test_times_use_the_cluster_timezone():
    _, html, text = templates.render("lockout", {"until": NOW + timedelta(minutes=15)}, SETTINGS)
    assert "2026-10-24 11:45 +0530" in text and "2026-10-24 11:45 +0530" in html


def test_every_kind_renders_and_unknown_kind_refused():
    contexts = {"set_password": {"link": LINK}, "reset_password": {"link": LINK},
                "lockout": {"until": NOW}, "application_approved": {"link": LINK},
                "application_rejected": {"note": "Use your <university> email"},
                "application_received_admin": {"application": {"email": "a@x.com"}},
                "account_created_admin_notice": {"username": "amasha", "created_by": "dinuka"}}
    for kind, ctx in contexts.items():
        subject, html, text = templates.render(kind, ctx, SETTINGS)
        assert subject and html.startswith("<!doctype html>") and text
    _, html, _ = templates.render("application_rejected", {"note": ""}, SETTINGS)
    assert "Note from the admin" not in html
    with pytest.raises(KeyError):
        templates.render("no_such_kind", {}, SETTINGS)


def test_register_adds_a_kind():
    templates.register("test_kind", lambda c: f"Hello {c['name']}",
                       lambda c: [f"Hi {c['name']}", templates.Button("Open", c["url"])])
    subject, html, text = templates.render("test_kind", {"name": "<i>", "url": "https://x"},
                                           SETTINGS)
    assert subject == "Hello <i>" and "Hi &lt;i&gt;" in html and "Open: https://x" in text
    with pytest.raises(ValueError):
        templates.register("test_kind", lambda c: "", lambda c: [])


def test_resend_sender_posts_the_message():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url, request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json={"id": "1"})

    sender = ResendSender("key", "deck@x.org", transport=httpx.MockTransport(handler))
    sender.send("a@x.com", "Subj", "<p>h</p>", "t")
    url, auth, body = seen[0]
    assert str(url) == "https://api.resend.com/emails" and auth == "Bearer key"
    assert body == {"from": "deck@x.org", "to": ["a@x.com"], "subject": "Subj",
                    "html": "<p>h</p>", "text": "t"}
    failing = ResendSender("key", "deck@x.org",
                           transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        failing.send("a@x.com", "s", "h", "t")


def test_smtp_sender_builds_a_two_part_message(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent.append(("starttls",))

        def login(self, user, pw):
            sent.append(("login", user))

        def send_message(self, msg):
            sent.append(("send", msg["To"], msg["From"], msg.get_content_type()))

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    SmtpSender("smtp.x.org", 587, "u", "p", True, "deck@x.org").send("a@x.com", "S", "<p>h</p>",
                                                                    "t")
    assert sent == [("connect", "smtp.x.org", 587), ("starttls",), ("login", "u"),
                    ("send", "a@x.com", "deck@x.org", "multipart/alternative")]


def test_sender_for_provider():
    assert isinstance(sender_for(SETTINGS), NullSender)
    smtp = load_settings({"SD_DATABASE_URL": "postgresql://db/sd", "SD_MAIL_PROVIDER": "smtp"})
    assert isinstance(sender_for(smtp), SmtpSender)
    resend = load_settings({"SD_DATABASE_URL": "postgresql://db/sd",
                            "SD_MAIL_PROVIDER": "resend", "SD_RESEND_API_KEY": "k"})
    assert isinstance(sender_for(resend), ResendSender)


class FlakySender:
    def __init__(self, fail: bool):
        self.fail = fail
        self.sent: list[str] = []

    def send(self, to, subject, html, text):
        if self.fail:
            raise OSError("provider down")
        self.sent.append(to)


@pytest.fixture
def mail_db(pg_db):
    from sqlalchemy import text

    from sdweb import db

    db.configure(load_settings({"SD_DATABASE_URL": pg_db.dsn}))
    with db.session_scope() as s:
        s.execute(text("DELETE FROM outbox"))
        s.execute(text("UPDATE settings SET value = 'true' WHERE key = 'mail_enabled'"))
    return db


def _outbox(db):
    from sqlalchemy import select

    from sdweb.models import OutboxMessage

    with db.session_scope() as s:
        return s.scalars(select(OutboxMessage).order_by(OutboxMessage.id)).all()


@pytest.mark.pg
def test_drain_sends_due_mail_once(mail_db):
    from sdweb.mail import enqueue
    from sdweb.worker.mail_task import drain

    with mail_db.session_scope() as s:
        enqueue(s, to="a@x.com", kind="set_password", context={"link": LINK}, settings=SETTINGS,
                now=NOW)
    sender = FlakySender(fail=False)
    for _ in range(2):
        with mail_db.session_scope() as s:
            drain(s, sender, NOW)
    [row] = _outbox(mail_db)
    assert sender.sent == ["a@x.com"] and row.sent_at == NOW and row.last_error is None


@pytest.mark.pg
def test_mail_disabled_sends_nothing(mail_db):
    from sqlalchemy import text

    from sdweb.mail import enqueue
    from sdweb.worker.mail_task import drain

    with mail_db.session_scope() as s:
        enqueue(s, to="queued@x.com", kind="lockout", context={"until": NOW},
                settings=SETTINGS, now=NOW)
        s.execute(text("UPDATE settings SET value = 'false' WHERE key = 'mail_enabled'"))
        enqueue(s, to="off@x.com", kind="lockout", context={"until": NOW},
                settings=SETTINGS, now=NOW)
    sender = FlakySender(fail=False)
    with mail_db.session_scope() as s:
        drain(s, sender, NOW + timedelta(hours=1))
    assert sender.sent == []
    rows = _outbox(mail_db)
    assert [(r.to_addr, r.last_error) for r in rows] == [("queued@x.com", None),
                                                         ("off@x.com", "mail disabled")]
    with mail_db.session_scope() as s:   # turned back on: the queued one goes, never the other
        s.execute(text("UPDATE settings SET value = 'true' WHERE key = 'mail_enabled'"))
        drain(s, sender, NOW + timedelta(hours=1))
    assert sender.sent == ["queued@x.com"]


@pytest.mark.pg
def test_failures_retry_at_2_then_4_minutes_and_give_up_after_8(mail_db):
    from sdweb.mail import enqueue
    from sdweb.worker.mail_task import MAX_ATTEMPTS, drain

    with mail_db.session_scope() as s:
        enqueue(s, to="a@x.com", kind="set_password", context={"link": LINK}, settings=SETTINGS,
                now=NOW)
    down = FlakySender(fail=True)
    with mail_db.session_scope() as s:
        drain(s, down, NOW)
    [row] = _outbox(mail_db)
    assert (row.attempts, row.next_attempt_at) == (1, NOW + timedelta(minutes=2))
    assert row.last_error == "provider down"
    with mail_db.session_scope() as s:
        drain(s, down, NOW + timedelta(minutes=1))          # not due yet
        drain(s, down, NOW + timedelta(minutes=2))
    [row] = _outbox(mail_db)
    assert (row.attempts, row.next_attempt_at) == (2, NOW + timedelta(minutes=6))
    later = NOW
    for _ in range(MAX_ATTEMPTS + 2):
        later += timedelta(hours=7)
        with mail_db.session_scope() as s:
            drain(s, down, later)
    [row] = _outbox(mail_db)
    assert row.attempts == MAX_ATTEMPTS == 8 and row.sent_at is None
