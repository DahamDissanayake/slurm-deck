"""Shared by the account, allow-list and application tests: a fake deck-agent,
an app on the migrated test database, and helpers to add and sign in accounts.
The fixtures are registered for tests/web through conftest.py."""

import pytest

from sdweb.agent import AgentCallError

PW = "correct horse battery staple"


class FakeAgent:
    def __init__(self, fail_once: bool = False, folder_owner: int | None = None,
                 shell_uid: int | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail_once, self.folder_owner, self.shell_uid = fail_once, folder_owner, shell_uid

    def call(self, verb, payload=None, *, session=None):
        assert session, "admin verbs carry the admin's session"
        self.calls.append((verb, payload))
        if verb == "account.create" and self.fail_once:
            self.fail_once = False
            raise AgentCallError("account_create_failed", "GPU host down; undone.", 502)
        if verb == "account.inspect_folder":
            owner = self.folder_owner
            return {"exists": owner is not None, "owner_uid": owner, "bytes": 10, "mtime": "t",
                    "uid_in_use": False}
        if verb == "account.attach_shell":
            if self.shell_uid is None:
                raise AgentCallError("not_attachable", "No such account.", 403)
            return {"uid": self.shell_uid}
        return {}


@pytest.fixture
def env(pg_db):
    from sqlalchemy import text

    from sdweb.app import create_app
    from sdweb.config import load_settings
    from sdweb.deps import get_mailer

    agent = FakeAgent()
    app = create_app(load_settings({"SD_DATABASE_URL": pg_db.dsn,
                                    "SD_PUBLIC_HOSTNAME": "deck.x.org"}), agent=agent)
    outbox: list = []
    app.dependency_overrides[get_mailer] = lambda: (
        lambda db, *, to, kind, context: outbox.append((to, kind, context)))
    with app.state.sessionmaker() as s, s.begin():
        s.execute(text("TRUNCATE accounts, sessions, password_tokens, login_attempts, "
                       "audit_events RESTART IDENTITY CASCADE"))
        s.execute(text("ALTER SEQUENCE web_uid_seq RESTART WITH 20000"))
    return app, agent, outbox


def _account(app, username, role="user", kind="hidden", status="active") -> int:
    from sdweb.models import Account
    from sdweb.security import hash_password

    with app.state.sessionmaker() as s, s.begin():
        a = Account(email=f"{username}@x.org", full_name=username.title(), username=username,
                    role=role, status=status, linux_kind=kind, password_hash=hash_password(PW))
        s.add(a)
        s.flush()
        return a.id


def _client(app, username):
    from fastapi.testclient import TestClient

    c = TestClient(app, base_url="https://testserver", client=("10.0.0.9", 50000))
    csrf = c.post("/api/auth/login", json={"email": f"{username}@x.org", "password": PW}) \
        .json()["csrf_token"]
    c.headers["X-CSRF-Token"] = csrf
    return c


@pytest.fixture
def admin(env):
    app, agent, outbox = env
    _account(app, "dinuka", role="admin")
    _account(app, "kasun", role="admin")
    return app, agent, outbox, _client(app, "dinuka")


def _rows(app, username):
    from sqlalchemy import select

    from sdweb.models import Account

    with app.state.sessionmaker() as s:
        return s.scalars(select(Account).where(Account.username == username)).all()
