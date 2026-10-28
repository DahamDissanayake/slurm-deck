"""Sign-in, sessions, CSRF, lockout and the password flows, against a real
migrated database through FastAPI's TestClient."""

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.pg

PW = "correct horse battery staple"
EMAIL = "amasha@iit.ac.lk"
T0 = datetime(2026, 10, 24, 6, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


@pytest.fixture
def env(pg_db):
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from sdweb.app import create_app
    from sdweb.config import load_settings
    from sdweb.deps import get_mailer

    app = create_app(load_settings({"SD_DATABASE_URL": pg_db.dsn,
                                    "SD_PUBLIC_HOSTNAME": "deck.x.org"}))
    clock, outbox = Clock(), []
    app.state.clock = clock
    app.dependency_overrides[get_mailer] = lambda: (
        lambda db, *, to, kind, context: outbox.append((to, kind, context)))
    with app.state.sessionmaker() as s, s.begin():
        s.execute(text("TRUNCATE accounts, sessions, password_tokens, login_attempts, "
                       "audit_events RESTART IDENTITY CASCADE"))
    client = TestClient(app, base_url="https://testserver", client=("10.0.0.9", 50000))
    return app, client, clock, outbox


def _add_account(app, email=EMAIL, username="amasha", status="active", pw=PW) -> int:
    from sdweb.models import Account
    from sdweb.security import hash_password

    with app.state.sessionmaker() as s, s.begin():
        a = Account(email=email, full_name=username.title(), username=username, role="user",
                    status=status, password_hash=hash_password(pw) if pw else None)
        s.add(a)
        s.flush()
        return a.id


def _login(client, email=EMAIL, pw=PW):
    return client.post("/api/auth/login", json={"email": email, "password": pw})


def _token(app, account_id, purpose="reset") -> str:
    from sdweb.auth.sessions import issue_password_token
    from sdweb.models import Account

    with app.state.sessionmaker() as s, s.begin():
        return issue_password_token(s, s.get(Account, account_id), purpose,
                                    app.state.settings, app.state.clock())


def test_login_sets_strict_cookie(env):
    app, client, _, _ = env
    _add_account(app)
    r = _login(client, email=" AMASHA@iit.ac.lk ")
    assert r.status_code == 200, r.text
    c = r.headers["set-cookie"]
    assert "sd_session=" in c and "HttpOnly" in c and "SameSite=strict" in c.replace(
        "Strict", "strict") and "Secure" in c and "Path=/" in c
    body = r.json()
    assert body["account"]["username"] == "amasha" and len(body["csrf_token"]) >= 43
    me = client.get("/api/auth/me").json()
    assert me["account"]["email"] == EMAIL and me["acting_as"] is None


def test_unknown_email_and_wrong_password_look_the_same(env):
    app, client, _, _ = env
    _add_account(app)
    _add_account(app, email="off@x.com", username="off", status="disabled")
    replies = [_login(client, email="nobody@x.com"), _login(client, pw="wrong password!!"),
               _login(client, email="off@x.com")]
    assert {(r.status_code, r.text) for r in replies} == {(401, '{"error":"bad_credentials"}')}
    assert "set-cookie" not in replies[0].headers


def test_lockout_after_ten_failures_and_owner_emailed(env):
    app, client, clock, outbox = env
    _add_account(app)
    for _ in range(10):
        assert _login(client, pw="wrong password!!").status_code == 401
        clock.advance(seconds=30)
    r = _login(client)                                  # right password, still locked
    assert r.status_code == 423 and 0 < r.json()["retry_after_s"] <= 15 * 60
    assert [(to, kind) for to, kind, _ in outbox] == [(EMAIL, "lockout")]
    clock.advance(minutes=16)
    assert _login(client).status_code == 200


def test_per_ip_limit(env):
    app, client, _, _ = env
    for i in range(30):
        _login(client, email=f"u{i}@x.com")
    assert _login(client, email="another@x.com").status_code == 429


def test_idle_31_minutes_logs_out(env):
    app, client, clock, _ = env
    _add_account(app)
    _login(client)
    clock.advance(minutes=29)
    assert client.get("/api/auth/me").status_code == 200    # refreshes last_seen_at
    clock.advance(minutes=29)
    assert client.get("/api/auth/me").status_code == 200
    clock.advance(minutes=31)
    assert client.get("/api/auth/me").status_code == 401


def test_absolute_12h_logs_out_even_when_active(env):
    app, client, clock, _ = env
    _add_account(app)
    _login(client)
    for _ in range(12 * 3 + 1):
        clock.advance(minutes=20)
        r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_post_without_csrf_is_403(env):
    app, client, _, _ = env
    _add_account(app)
    csrf = _login(client).json()["csrf_token"]
    r = client.post("/api/auth/logout")
    assert (r.status_code, r.json()) == (403, {"error": "csrf"})
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": "x" * 43}).status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_reset_link_single_use(env):
    app, client, _, _ = env
    token = _token(app, _add_account(app))
    new = "a brand new passphrase"
    r = client.post("/api/auth/password/set", json={"token": token, "password": new})
    assert r.status_code == 200 and "sd_session=" in r.headers["set-cookie"]
    r = client.post("/api/auth/password/set", json={"token": token, "password": new + "2"})
    assert (r.status_code, r.json()) == (400, {"error": "link_used"})
    assert _login(client, pw=new).status_code == 200


def test_reset_link_expires_after_one_hour(env):
    app, client, clock, _ = env
    token = _token(app, _add_account(app))
    clock.advance(minutes=61)
    r = client.post("/api/auth/password/set", json={"token": token, "password": "another pass 99"})
    assert (r.status_code, r.json()) == (400, {"error": "link_expired"})


def test_weak_password_keeps_the_link(env):
    app, client, _, _ = env
    token = _token(app, _add_account(app), purpose="set")
    r = client.post("/api/auth/password/set", json={"token": token, "password": "amasha-1234567"})
    assert r.status_code == 422 and r.json()["problems"] == ["Don't use your email or username."]
    r = client.post("/api/auth/password/set", json={"token": token, "password": "a good long one!"})
    assert r.status_code == 200


def test_set_password_kills_existing_sessions(env):
    from fastapi.testclient import TestClient

    app, client, _, _ = env
    account = _add_account(app)
    other = TestClient(app, base_url="https://testserver", client=("10.0.0.9", 50000))
    _login(other)
    assert other.get("/api/auth/me").status_code == 200
    token = _token(app, account)
    client.post("/api/auth/password/set", json={"token": token, "password": "fresh passphrase"})
    assert other.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").status_code == 200


def test_change_password_kills_other_sessions_and_old_links(env):
    from fastapi.testclient import TestClient

    app, client, _, _ = env
    account = _add_account(app)
    link = _token(app, account)
    other = TestClient(app, base_url="https://testserver", client=("10.0.0.9", 50000))
    _login(other)
    csrf = _login(client).json()["csrf_token"]
    h = {"X-CSRF-Token": csrf}
    bad = client.post("/api/auth/password/change", json={"current": "nope", "new": "x"}, headers=h)
    assert bad.status_code == 400
    r = client.post("/api/auth/password/change", json={"current": PW, "new": "changed passphrase"},
                    headers=h)
    assert r.status_code == 200
    assert other.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").status_code == 200
    r = client.post("/api/auth/password/set", json={"token": link, "password": "sneaky passphrase"})
    assert r.json() == {"error": "link_used"}


def test_forgot_is_always_202_and_mails_active_accounts_only(env):
    app, client, _, outbox = env
    _add_account(app)
    _add_account(app, email="off@x.com", username="off", status="disabled")
    for email in (" Amasha@IIT.ac.lk", "off@x.com", "nobody@x.com"):
        assert client.post("/api/auth/password/forgot", json={"email": email}).status_code == 202
    assert [(to, kind) for to, kind, _ in outbox] == [(EMAIL, "reset_password")]
    link = outbox[0][2]["link"]
    assert link.startswith("https://deck.x.org/reset-password#token=")


def test_disabled_account_cannot_sign_in(env):
    app, client, _, _ = env
    _add_account(app, status="disabled")
    assert _login(client).json() == {"error": "bad_credentials"}


def test_require_admin(env):
    from typing import Annotated

    from fastapi import Depends

    from sdweb.deps import SessionCtx, require_admin

    app, client, _, _ = env

    @app.get("/api/test/admin")
    def _admin_only(ctx: Annotated[SessionCtx, Depends(require_admin)]):
        return {"ok": True}

    _add_account(app)
    _login(client)
    assert client.get("/api/test/admin").status_code == 403
