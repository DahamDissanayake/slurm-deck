"""python -m sdweb.cli create-admin: the first admin, made through deck-agent."""

import io

import pytest
from accounts_helpers import FakeAgent, _account, _rows

pytestmark = pytest.mark.pg

ARGS = ["create-admin", "--email", "Nimal@X.org", "--full-name", "Nimal Perera",
        "--username", "nimal"]


class SessionCheckingAgent(FakeAgent):
    """Also checks that the session it is given is a live admin session."""

    def __init__(self, app, **kw) -> None:
        super().__init__(**kw)
        self.app = app

    def call(self, verb, payload=None, *, session=None):
        from sdweb.auth.sessions import peek_session

        with self.app.state.sessionmaker() as s:
            found = peek_session(s, session or "", self.app.state.settings,
                                 self.app.state.clock())
        assert found and found[1].role == "admin" and found[1].username == "nimal"
        return super().call(verb, payload, session=session)


def _run(env, args=ARGS):
    from sdweb.cli import main

    app, _, _ = env
    agent = SessionCheckingAgent(app)
    out, err = io.StringIO(), io.StringIO()
    code = main(args, environ={"SD_DATABASE_URL": app.state.settings.database_url,
                               "SD_PUBLIC_HOSTNAME": "deck.x.org"},
                agent=agent, out=out, err=err)
    return code, agent, out.getvalue(), err.getvalue()


def _sessions(app):
    from sqlalchemy import func, select

    from sdweb.models import WebSession

    with app.state.sessionmaker() as s:
        return s.scalar(select(func.count()).select_from(WebSession))


def test_create_admin_refuses_when_admin_exists(env):
    app, _, _ = env
    _account(app, "dinuka", role="admin")
    code, agent, out, err = _run(env)
    assert code != 0 and "already" in err and out == ""
    assert agent.calls == [] and _rows(app, "nimal") == []


def test_create_admin_force_adds_another_admin(env):
    app, _, _ = env
    _account(app, "dinuka", role="admin")
    code, _, out, _ = _run(env, ARGS + ["--force"])
    assert code == 0 and "/set-password#token=" in out
    assert _rows(app, "nimal")[0].role == "admin"


def test_create_admin_calls_agent_and_prints_set_password_link(env):
    app, _, outbox = env
    code, agent, out, _ = _run(env)
    assert code == 0
    assert agent.calls == [("account.create", {"username": "nimal", "uid": 20000})]
    [row] = _rows(app, "nimal")
    assert (row.email, row.role, row.status, row.linux_kind, row.uid) == (
        "nimal@x.org", "admin", "active", "hidden", 20000)
    assert row.password_hash is None and row.last_login_at is None
    link = out.strip().splitlines()[-1]
    assert link.startswith("https://deck.x.org/set-password#token=")
    assert outbox == []                       # printed, never mailed
    assert _sessions(app) == 0                # the bootstrap session is gone


def test_create_admin_link_sets_the_password(env):
    from fastapi.testclient import TestClient

    app, _, _ = env
    _, _, out, _ = _run(env)
    token = out.strip().splitlines()[-1].split("#token=")[1]
    c = TestClient(app, base_url="https://testserver")
    r = c.post("/api/auth/password/set",
               json={"token": token, "password": "a long enough passphrase 42"})
    assert r.status_code == 200, r.text


def test_create_admin_agent_failure_leaves_nothing(env):
    from sdweb.cli import main

    app, _, _ = env
    agent = SessionCheckingAgent(app, fail_once=True)
    err = io.StringIO()
    code = main(ARGS, environ={"SD_DATABASE_URL": app.state.settings.database_url},
                agent=agent, out=io.StringIO(), err=err)
    assert code != 0 and "GPU host down" in err.getvalue()
    assert _rows(app, "nimal") == [] and _sessions(app) == 0
    assert _run(env)[0] == 0                  # and a retry works


@pytest.mark.parametrize("args", [
    ["create-admin", "--email", "not-an-email", "--full-name", "N", "--username", "nimal"],
    ["create-admin", "--email", "n@x.org", "--full-name", "N", "--username", "root"],
    ["create-admin", "--email", "n@x.org", "--full-name", " ", "--username", "nimal"],
])
def test_create_admin_rejects_bad_input(env, args):
    code, agent, _, err = _run(env, args)
    assert code != 0 and err and agent.calls == []
