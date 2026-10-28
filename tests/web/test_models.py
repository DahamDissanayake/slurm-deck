"""The first migration: tables, constraints, the UID sequence and the agent views."""

from datetime import UTC, datetime, timedelta

import pytest

from sdweb.config import load_settings

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def test_settings_defaults_and_required_url():
    s = load_settings({"SD_DATABASE_URL": "postgresql://u:p@db/sd"})
    assert (s.public_hostname, s.cluster_tz, s.mail_provider) == ("slurmdeck.local", "UTC",
                                                                  "none")
    assert s.secure_cookies is True and s.session_idle_minutes == 30
    assert s.session_max_hours == 12 and s.password_min_len == 12
    with pytest.raises(ValueError, match="SD_DATABASE_URL"):
        load_settings({})


@pytest.mark.parametrize("env, match", [
    ({"SD_CLUSTER_TZ": "Mars/Olympus"}, "SD_CLUSTER_TZ"),
    ({"SD_MAIL_PROVIDER": "pigeon"}, "SD_MAIL_PROVIDER"),
    ({"SD_SECURE_COOKIES": "maybe"}, "SD_SECURE_COOKIES"),
    ({"SD_SMTP_PORT": "x"}, "SD_SMTP_PORT"),
])
def test_settings_refuse_bad_values(env, match):
    with pytest.raises(ValueError, match=match):
        load_settings({"SD_DATABASE_URL": "postgresql://db/sd", **env})


def test_settings_read_site_values():
    s = load_settings({"SD_DATABASE_URL": "postgresql://db/sd", "SD_CLUSTER_TZ": "Asia/Colombo",
                       "SD_PUBLIC_HOSTNAME": "deck.example.org", "SD_SECURE_COOKIES": "false",
                       "SD_MAIL_PROVIDER": "smtp", "SD_SMTP_PORT": "2525"})
    assert (s.cluster_tz, s.public_hostname, s.secure_cookies) == ("Asia/Colombo",
                                                                   "deck.example.org", False)
    assert (s.mail_provider, s.smtp_port) == ("smtp", 2525)
    assert s.session_hostname == "sessions.deck.example.org"


def test_session_hostname_is_its_own_name():
    s = load_settings({"SD_DATABASE_URL": "postgresql://db/sd",
                       "SD_SESSION_HOSTNAME": "Jobs.Example.Org"})
    assert s.session_hostname == "jobs.example.org"
    with pytest.raises(ValueError, match="SD_SESSION_HOSTNAME"):
        load_settings({"SD_DATABASE_URL": "postgresql://db/sd",
                       "SD_PUBLIC_HOSTNAME": "deck.x.org", "SD_SESSION_HOSTNAME": "deck.x.org"})


def _admin(pg_db):
    import psycopg

    return psycopg.connect(pg_db.dsn, autocommit=True)


def _account(conn, email: str, username: str, **kw) -> int:
    cols = {"email": email, "full_name": username.title(), "username": username,
            "role": "user", "status": "active", "linux_kind": "hidden", **kw}
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    row = conn.execute(f"INSERT INTO accounts ({names}) VALUES ({marks}) RETURNING id",
                       list(cols.values())).fetchone()
    return row[0]


@pytest.mark.pg
def test_agent_role_reads_views_only(pg_db):
    import psycopg

    with psycopg.connect(pg_db.agent_dsn, autocommit=True) as conn:
        conn.execute("SELECT * FROM agent_sessions").fetchall()
        conn.execute("SELECT * FROM agent_accounts").fetchall()
        for table in ("accounts", "sessions", "password_tokens", "settings"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"SELECT * FROM {table}")


@pytest.mark.pg
def test_emails_unique_case_insensitively(pg_db):
    import psycopg

    with _admin(pg_db) as conn:
        _account(conn, "A@x.com", "case-a")
        with pytest.raises(psycopg.errors.UniqueViolation):
            _account(conn, "a@x.com", "case-b")


@pytest.mark.pg
def test_one_pending_application_per_email(pg_db):
    import psycopg

    sql = ("INSERT INTO applications (email, full_name, role_title, contact_number, status, ip) "
           "VALUES (%s, 'Amasha', 'Student', '0771234567', %s, '10.0.0.1')")
    with _admin(pg_db) as conn:
        conn.execute(sql, ("apply@x.com", "rejected"))
        conn.execute(sql, ("apply@x.com", "pending"))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(sql, ("APPLY@x.com", "pending"))


@pytest.mark.pg
def test_uid_sequence_and_seeded_settings(pg_db):
    with _admin(pg_db) as conn:
        assert conn.execute("SELECT nextval('web_uid_seq')").fetchone()[0] == 20000
        assert conn.execute("SELECT max_value, cycle FROM pg_sequences "
                            "WHERE sequencename = 'web_uid_seq'").fetchone() == (59999, False)
        rows = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    assert rows["default_time_limit"] == "08:00:00" and rows["extension_cap_hours"] == 24
    assert rows["maintenance_banner"] is None and rows["mail_enabled"] is True


@pytest.mark.pg
def test_pg_session_store_reads_the_real_view(pg_db):
    from deckagent.sessions import PgSessionStore, hash_token

    with _admin(pg_db) as conn:
        admin_id = _account(conn, "dinuka@x.com", "dinuka", role="admin", uid=20010,
                            last_login_at=NOW)
        user_id = _account(conn, "amasha@x.com", "amasha", uid=20011)
        conn.execute("INSERT INTO sessions (token_hash, account_id, csrf_token, created_at, "
                     "last_seen_at, ip, user_agent, acting_as_account_id) "
                     "VALUES (%s, %s, 'csrf', %s, %s, '10.0.0.2', 'test', %s)",
                     (hash_token("tok"), admin_id, NOW - timedelta(hours=1), NOW, user_id))

    store = PgSessionStore(pg_db.agent_dsn)
    row = store.lookup(hash_token("tok"))
    assert row is not None
    assert (row.username, row.role, row.uid, row.status) == ("dinuka", "admin", 20010, "active")
    assert row.last_seen_at == NOW and row.acting_as_username == "amasha"
    acct = store.account("amasha")
    assert acct is not None and (acct.linux_kind, acct.uid) == ("hidden", 20011)
    assert store.lookup(hash_token("other")) is None and store.account("nobody") is None


@pytest.mark.pg
def test_models_match_the_migration(pg_db):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from sdweb.db import sa_url
    from sdweb.models import Base

    eng = create_engine(sa_url(pg_db.dsn))
    try:
        with eng.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        eng.dispose()
    assert diff == []


@pytest.mark.pg
def test_session_scope_commits_and_rolls_back(pg_db):
    from sqlalchemy import select

    from sdweb import db
    from sdweb.models import Account

    db.configure(load_settings({"SD_DATABASE_URL": pg_db.dsn}))
    with db.session_scope() as s:
        s.add(Account(email="orm@x.com", full_name="Orm", username="orm", role="user"))
    with pytest.raises(RuntimeError), db.session_scope() as s:
        s.add(Account(email="gone@x.com", full_name="Gone", username="gone", role="user"))
        s.flush()
        raise RuntimeError
    with db.session_scope() as s:
        names = set(s.scalars(select(Account.username).where(
            Account.username.in_(["orm", "gone"]))))
    assert names == {"orm"}


@pytest.mark.pg
def test_agent_reads_settings_through_its_view(pg_db):
    from deckagent.sessions import PgSessionStore

    store = PgSessionStore(pg_db.agent_dsn)
    assert store.setting("extension_cap_hours") == 24
    assert store.setting("maintenance_banner") is None and store.setting("nope") is None
