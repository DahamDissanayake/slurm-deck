"""Database engine, sessions and migrations."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from sdweb.config import WebSettings, load_settings

MIGRATIONS = Path(__file__).resolve().parent / "migrations"

_factory: sessionmaker[Session] | None = None


def sa_url(dsn: str) -> URL:
    """A SQLAlchemy URL (psycopg 3 driver) for a libpq URL or key=value string."""
    from psycopg.conninfo import conninfo_to_dict

    d = conninfo_to_dict(dsn)
    port = d.get("port")
    return URL.create("postgresql+psycopg", username=_str(d.get("user")),
                      password=_str(d.get("password")), host=_str(d.get("host")),
                      port=int(port) if port else None, database=_str(d.get("dbname")))


def _str(v: object) -> str | None:
    return None if v is None else str(v)


def engine(settings: WebSettings) -> Engine:
    return create_engine(sa_url(settings.database_url), pool_pre_ping=True)


def configure(settings: WebSettings) -> None:
    global _factory
    _factory = sessionmaker(engine(settings), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """One transaction: committed on success, rolled back on any error."""
    if _factory is None:
        configure(load_settings(os.environ))
    assert _factory is not None
    with _factory() as session, session.begin():
        yield session


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session


def migrate(dsn: str, *, agent_password: str, revision: str = "head") -> None:
    """Run the Alembic migrations against dsn.

    agent_password becomes the sd_agent_ro role's password (SD_AGENT_DB_PASSWORD).
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["url"] = sa_url(dsn)
    cfg.attributes["agent_password"] = agent_password
    command.upgrade(cfg, revision)
