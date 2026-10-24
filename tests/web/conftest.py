import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from accounts_helpers import admin, env  # noqa: F401  (fixtures for tests/web)

AGENT_PASSWORD = "agent-ro 'test' 50% pw"   # quote and percent check the quoting


@dataclass(frozen=True)
class PgDb:
    dsn: str           # the migrated database, as the admin user (libpq conninfo)
    agent_dsn: str     # the same database, as sd_agent_ro


@pytest.fixture(scope="module")
def pg_db() -> Iterator[PgDb]:
    """A fresh database per test module, migrated to head."""
    import psycopg
    from psycopg.conninfo import make_conninfo

    from sdweb.db import migrate

    server = os.environ["TEST_DATABASE_URL"]
    name = f"sdweb_{secrets.token_hex(4)}"
    with psycopg.connect(server, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    dsn = make_conninfo(server, dbname=name)
    try:
        migrate(dsn, agent_password=AGENT_PASSWORD)
        yield PgDb(dsn, make_conninfo(dsn, user="sd_agent_ro", password=AGENT_PASSWORD))
    finally:
        with psycopg.connect(server, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
