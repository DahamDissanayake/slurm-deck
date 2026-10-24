"""Session resolution: raw token (or the worker's peer UID) -> Caller."""

import os
from datetime import UTC, datetime, timedelta

import pytest

from deckagent.config import load_config
from deckagent.protocol import AgentError, Caller
from deckagent.sessions import SessionRow, hash_token, resolve_caller

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
CONFIG = load_config({"SD_WEB_UID": "1001", "SD_WORKER_UID": "1002"})
WEB, WORKER = 1001, 1002


def _row(username="amasha", role="user", kind="hidden", status="active",
         created=timedelta(hours=1), seen=timedelta(minutes=1), acting_as=None) -> SessionRow:
    return SessionRow(username=username, role=role, linux_kind=kind, uid=20001, status=status,
                      created_at=NOW - created, last_seen_at=NOW - seen,
                      acting_as_username=acting_as)


class FakeStore:
    def __init__(self, sessions: dict[str, SessionRow], accounts: dict[str, SessionRow]):
        self.sessions = {hash_token(k): v for k, v in sessions.items()}
        self.accounts = accounts

    def lookup(self, token_hash: str) -> SessionRow | None:
        return self.sessions.get(token_hash)

    def account(self, username: str) -> SessionRow | None:
        return self.accounts.get(username)


ACCOUNTS = {
    "amasha": _row(),
    "dinuka": _row("dinuka", role="admin"),
    "kasun": _row("kasun", role="admin"),
    "shelly": _row("shelly", kind="shell"),
    "gone": _row("gone", status="disabled"),
}


def _resolve(row: SessionRow | None, *, peer=WEB, token="tok") -> Caller:
    store = FakeStore({"tok": row} if row else {}, ACCOUNTS)
    headers = {"x-sd-session": token} if token else {}
    return resolve_caller(peer, headers, store, CONFIG, now=NOW)


def _status(row: SessionRow | None, **kw) -> int:
    with pytest.raises(AgentError) as e:
        _resolve(row, **kw)
    return e.value.status


def test_active_session_resolves_to_its_account():
    assert _resolve(_row()) == Caller("amasha", "user", "hidden", False, None)


def test_expired_idle_session_refused():
    assert _status(_row(seen=timedelta(minutes=31))) == 401


def test_absolute_cap_refused():
    assert _status(_row(created=timedelta(hours=12, minutes=1))) == 401


def test_disabled_account_refused():
    assert _status(_row(status="disabled")) == 401


def test_missing_or_unknown_token_refused():
    assert _status(_row(), token="") == 401
    assert _status(None) == 401


def test_worker_uid_gets_worker_caller():
    # The session header is ignored for the worker.
    assert _resolve(None, peer=WORKER, token="anything") == Caller(None, "worker", None, True, None)


def test_act_as_requires_admin():
    assert _status(_row(acting_as="amasha")) == 403


@pytest.mark.parametrize("target", ["shelly", "gone", "nobody", "kasun"])
def test_act_as_refuses_shell_inactive_missing_and_admin_targets(target):
    assert _status(_row("dinuka", role="admin", acting_as=target)) == 403


def test_act_as_shell_target_refused():
    assert _status(_row("dinuka", role="admin", acting_as="shelly")) == 403


def test_act_as_resolves_target_and_records_admin():
    c = _resolve(_row("dinuka", role="admin", acting_as="amasha"))
    assert (c.username, c.role, c.acting_admin) == ("amasha", "user", "dinuka")


def test_admin_session_still_checks_its_own_expiry_when_acting_as():
    assert _status(_row("dinuka", role="admin", acting_as="amasha",
                        seen=timedelta(minutes=45))) == 401


def test_hash_token_is_sha256_hex():
    assert hash_token("abc") == ("ba7816bf8f01cfea414140de5dae2223"
                                 "b00361a396177a9cb410ff61f20015ad")


@pytest.mark.pg
def test_pg_store_reads_view():
    import psycopg

    from deckagent.sessions import PgSessionStore

    dsn = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP VIEW IF EXISTS agent_sessions, agent_accounts")
        conn.execute("DROP TABLE IF EXISTS t_sessions, t_accounts")
        conn.execute("""CREATE TABLE t_accounts (username text primary key, role text,
            linux_kind text, uid int, status text, created_at timestamptz,
            last_seen_at timestamptz)""")
        conn.execute("""CREATE TABLE t_sessions (token_hash text primary key, username text,
            created_at timestamptz, last_seen_at timestamptz, acting_as_username text)""")
        conn.execute("""CREATE VIEW agent_accounts AS SELECT username, role, linux_kind, uid,
            status, created_at, last_seen_at FROM t_accounts""")
        conn.execute("""CREATE VIEW agent_sessions AS SELECT s.token_hash, a.username, a.role,
            a.linux_kind, a.uid, a.status, s.created_at, s.last_seen_at, s.acting_as_username
            FROM t_sessions s JOIN t_accounts a USING (username)""")
        conn.execute("INSERT INTO t_accounts VALUES ('amasha','user','hidden',20001,'active',"
                     "%s,%s)", (NOW, NOW))
        conn.execute("INSERT INTO t_sessions VALUES (%s,'amasha',%s,%s,NULL)",
                     (hash_token("tok"), NOW - timedelta(hours=1), NOW))
    try:
        store = PgSessionStore(dsn)
        row = store.lookup(hash_token("tok"))
        assert row is not None and (row.username, row.uid, row.status) == ("amasha", 20001,
                                                                           "active")
        assert row.last_seen_at == NOW and row.acting_as_username is None
        assert store.lookup(hash_token("other")) is None
        acct = store.account("amasha")
        assert acct is not None and acct.linux_kind == "hidden"
        assert store.account("nobody") is None
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("DROP VIEW IF EXISTS agent_sessions, agent_accounts")
            conn.execute("DROP TABLE IF EXISTS t_sessions, t_accounts")
