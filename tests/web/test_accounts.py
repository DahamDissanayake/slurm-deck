"""Admin account management and View as user, with a fake deck-agent."""

import pytest

from sdweb.agent import AgentCallError

pytestmark = pytest.mark.pg

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


NEW = {"email": " Nimal@X.org ", "full_name": "Nimal", "username": "nimal", "role": "user"}


def _rows(app, username):
    from sqlalchemy import select

    from sdweb.models import Account

    with app.state.sessionmaker() as s:
        return s.scalars(select(Account).where(Account.username == username)).all()


def test_create_calls_agent_then_inserts_and_mails(admin):
    app, agent, outbox, c = admin
    r = c.post("/api/admin/accounts", json=NEW)
    assert r.status_code == 200, r.text
    assert agent.calls == [("account.create", {"username": "nimal", "uid": 20000})]
    [row] = _rows(app, "nimal")
    assert (row.email, row.uid, row.linux_kind, row.password_hash) == ("nimal@x.org", 20000,
                                                                      "hidden", None)
    kinds = sorted((to, kind) for to, kind, _ in outbox)
    assert kinds == [("kasun@x.org", "account_created_admin_notice"),
                     ("nimal@x.org", "set_password")]
    link = next(ctx["link"] for to, kind, ctx in outbox if kind == "set_password")
    assert link.startswith("https://deck.x.org/set-password#token=")
    assert c.post("/api/admin/accounts", json=NEW).status_code == 409    # taken now


def test_agent_failure_leaves_no_row_and_retry_works(admin):
    app, agent, outbox, c = admin
    agent.fail_once = True
    r = c.post("/api/admin/accounts", json=NEW)
    assert (r.status_code, r.json()["error"]) == (502, "account_create_failed")
    assert _rows(app, "nimal") == [] and outbox == []
    assert c.post("/api/admin/accounts", json=NEW).status_code == 200
    assert len(_rows(app, "nimal")) == 1


def test_reconnect_uses_folder_owner_uid(admin):
    app, agent, _, c = admin
    agent.folder_owner = 2014
    r = c.post("/api/admin/accounts", json={**NEW, "reconnect_folder": True})
    assert r.status_code == 200, r.text
    assert ("account.create", {"username": "nimal", "uid": 2014, "link_existing": True}) \
        in agent.calls
    assert _rows(app, "nimal")[0].uid == 2014


def test_attach_shell_sets_kind_and_uid(admin):
    app, agent, _, c = admin
    agent.shell_uid = 1800
    assert c.post("/api/admin/accounts", json={**NEW, "attach_shell": True}).status_code == 200
    row = _rows(app, "nimal")[0]
    assert (row.uid, row.linux_kind) == (1800, "shell")
    assert all(verb != "account.create" for verb, _ in agent.calls)


def test_preview(admin):
    app, agent, _, c = admin
    agent.folder_owner = 2014
    p = c.post("/api/admin/accounts/preview", json={"email": "Dinuka@x.org"}).json()
    assert p["suggested_username"] == "dinuka-2" and p["email_valid"] is True
    assert p["existing_folder"]["owner_uid"] == 2014 and p["shell_account"] is None
    p = c.post("/api/admin/accounts/preview", json={"email": "x", "username": "root"}).json()
    assert (p["email_valid"], p["username_valid"]) == (False, False)


def test_last_admin_cannot_be_disabled_deleted_or_demoted(env):
    app, _, _ = env
    me = _account(app, "dinuka", role="admin")
    c = _client(app, "dinuka")
    for r in (c.post(f"/api/admin/accounts/{me}/disable"),
              c.delete(f"/api/admin/accounts/{me}"),
              c.patch(f"/api/admin/accounts/{me}", json={"role": "user"})):
        assert r.status_code == 409 and r.json() == {
            "error": "last_admin", "message": "There must always be at least one active admin."}


def test_admin_cannot_disable_themselves(admin):
    app, _, _, c = admin
    me = _rows(app, "dinuka")[0].id
    assert c.post(f"/api/admin/accounts/{me}/disable").json()["error"] == "self"


def test_disable_enable_reset_and_edit(admin):
    app, _, outbox, c = admin
    uid = _account(app, "amasha")
    other = _client(app, "amasha")
    assert c.post(f"/api/admin/accounts/{uid}/disable").status_code == 200
    assert other.get("/api/auth/me").status_code == 401           # sessions ended
    assert c.post(f"/api/admin/accounts/{uid}/enable").status_code == 200
    assert c.post(f"/api/admin/accounts/{uid}/reset-password").status_code == 200
    assert outbox[-1][:2] == ("amasha@x.org", "reset_password")
    r = c.patch(f"/api/admin/accounts/{uid}", json={"email": "New@X.org", "role": "admin"})
    assert r.status_code == 200 and (r.json()["email"], r.json()["role"]) == ("new@x.org",
                                                                             "admin")
    assert c.patch(f"/api/admin/accounts/{uid}", json={"email": "kasun@x.org"}).status_code \
        == 409
    listed = c.get("/api/admin/accounts", params={"q": "new@"}).json()["accounts"]
    assert [a["username"] for a in listed] == ["amasha"]


def test_purge_requires_typed_username(admin):
    app, agent, _, c = admin
    uid = _account(app, "amasha")
    r = c.request("DELETE", f"/api/admin/accounts/{uid}", params={"purge": "true"},
                  json={"confirm": "amasha2"})
    assert r.status_code == 400 and agent.calls == []
    r = c.request("DELETE", f"/api/admin/accounts/{uid}", params={"purge": "true"},
                  json={"confirm": "amasha"})
    assert r.status_code == 200
    assert agent.calls == [("account.delete", {"username": "amasha", "purge": True})]
    assert _rows(app, "amasha")[0].status == "deleted"


def test_view_as_sets_session_column_and_me_reports_it(admin):
    app, _, _, c = admin
    uid = _account(app, "amasha")
    shell = _account(app, "kamal", kind="shell")
    kasun = _rows(app, "kasun")[0].id
    assert c.post(f"/api/admin/view-as/{uid}").status_code == 200
    me = c.get("/api/auth/me").json()
    assert me["account"]["username"] == "dinuka" and me["acting_as"]["username"] == "amasha"
    assert c.delete("/api/admin/view-as").status_code == 200
    assert c.get("/api/auth/me").json()["acting_as"] is None
    assert c.post(f"/api/admin/view-as/{shell}").status_code == 403
    assert c.post(f"/api/admin/view-as/{kasun}").status_code == 403


def test_non_admin_gets_403_everywhere(env):
    app, agent, _ = env
    uid = _account(app, "amasha")
    c = _client(app, "amasha")
    for method, url in (("GET", "/api/admin/accounts"), ("POST", "/api/admin/accounts"),
                        ("POST", "/api/admin/accounts/preview"),
                        ("POST", f"/api/admin/accounts/{uid}/disable"),
                        ("PATCH", f"/api/admin/accounts/{uid}"),
                        ("DELETE", f"/api/admin/accounts/{uid}"),
                        ("POST", f"/api/admin/view-as/{uid}"), ("DELETE", "/api/admin/view-as")):
        assert c.request(method, url, json={}).status_code == 403, url
    assert agent.calls == []
