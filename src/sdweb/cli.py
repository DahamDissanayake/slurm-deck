"""Operator commands, run inside the web container:

    python -m sdweb.cli migrate
    python -m sdweb.cli create-admin --email E --full-name N --username U [--force]

create-admin makes the first admin. deck-agent only takes account.create from
an admin session, so the command adds the admin row, opens a session for it
that never leaves this process, calls account.create with it, and then ends
the session. If deck-agent refuses, the row and session are removed again so
the same email and username can be retried. The set-password link is printed,
not mailed.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, TextIO

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from sdcore.names import RESERVED, valid_username
from sdweb import db
from sdweb.agent import AgentCallError, AgentClient
from sdweb.audit import record
from sdweb.auth.sessions import create_session, end_sessions, issue_password_token
from sdweb.config import WebSettings, load_settings
from sdweb.models import Account
from sdweb.security import normalize_email, valid_email


class CliError(Exception):
    pass


def create_admin(maker: sessionmaker[Session], agent: Any, settings: WebSettings, *,
                 email: str, full_name: str, username: str, force: bool = False) -> str:
    """Make an admin account through deck-agent; the set-password link."""
    email, full_name = normalize_email(email), full_name.strip()
    if not valid_email(email) or not full_name:
        raise CliError("Enter a valid email and a full name.")
    if not valid_username(username) or username in RESERVED:
        raise CliError(f"The username {username!r} isn't allowed.")
    now = datetime.now(UTC)

    with maker() as s, s.begin():
        admins = s.scalar(select(func.count()).select_from(Account).where(
            Account.role == "admin", Account.status == "active"))
        if admins and not force:
            raise CliError("An admin already exists. Use the admin pages, or --force.")
        if s.scalar(select(Account.id).where(
                (Account.email == email) | (Account.username == username))) is not None:
            raise CliError("That email or username is already used.")
        uid = int(s.scalar(text("SELECT nextval('web_uid_seq')")) or 0)
        account = Account(email=email, full_name=full_name, username=username, role="admin",
                          status="active", linux_kind="hidden", uid=uid, created_at=now)
        s.add(account)
        s.flush()
        account_id = account.id
        session_token, _ = create_session(s, account, ip=None, user_agent="sdweb.cli",
                                          now=now)
        account.last_login_at = None

    try:
        agent.call("account.create", {"username": username, "uid": uid}, session=session_token)
    except AgentCallError as e:
        with maker() as s, s.begin():
            end_sessions(s, account_id)
            s.execute(delete(Account).where(Account.id == account_id))
        raise CliError(f"deck-agent refused: {e.message}") from None

    with maker() as s, s.begin():
        end_sessions(s, account_id)
        created = s.get(Account, account_id)
        assert created is not None
        raw = issue_password_token(s, created, "set", settings, now)
        record(s, actor_id=account_id, action="account.create", target=username,
               detail={"uid": uid, "linux_kind": "hidden", "role": "admin", "via": "cli",
                       "force": force})
    return f"https://{settings.public_hostname}/set-password#token={raw}"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m sdweb.cli")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="run the database migrations")
    c = sub.add_parser("create-admin", help="create the first admin account")
    c.add_argument("--email", required=True)
    c.add_argument("--full-name", required=True)
    c.add_argument("--username", required=True)
    c.add_argument("--force", action="store_true", help="even if an admin already exists")
    return p


def main(argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None,
         agent: Any = None, out: TextIO | None = None, err: TextIO | None = None) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    env = os.environ if environ is None else environ
    args = _parser().parse_args(argv)
    try:
        settings = load_settings(env)
        if args.command == "migrate":
            db.migrate(settings.database_url,
                       agent_password=env.get("SD_AGENT_DB_PASSWORD", ""))
            print("Database migrated.", file=out)
            return 0
        engine = db.engine(settings)
        try:
            link = create_admin(sessionmaker(engine, expire_on_commit=False),
                                agent or AgentClient(settings.agent_socket), settings,
                                email=args.email, full_name=args.full_name,
                                username=args.username, force=args.force)
        finally:
            engine.dispose()
    except (CliError, ValueError) as e:
        print(f"error: {e}", file=err)
        return 1
    print(f"Created admin {args.username}. Open this link to set the password:", file=out)
    print(link, file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
