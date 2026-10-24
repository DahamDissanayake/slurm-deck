"""SQLAlchemy models. The schema itself is owned by the migrations in
src/sdweb/migrations; these mirror it for the app's queries."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TS = DateTime(timezone=True)


ROLE = Enum("user", "admin", name="account_role")
ACCOUNT_STATUS = Enum("active", "disabled", "deleted", name="account_status")
LINUX_KIND = Enum("hidden", "shell", name="linux_kind")
TOKEN_PURPOSE = Enum("set", "reset", name="token_purpose")
APPLICATION_STATUS = Enum("pending", "approved", "rejected", name="application_status")
ALLOW_KIND = Enum("domain", "address", name="allow_kind")
AUDIT_SOURCE = Enum("web", "agent", "worker", name="audit_source")


class Base(DeclarativeBase):
    pass


def _now() -> Mapped[datetime]:
    return mapped_column(TS, server_default=func.now())


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    full_name: Mapped[str] = mapped_column(Text)
    username: Mapped[str] = mapped_column(Text, unique=True)
    role: Mapped[str] = mapped_column(ROLE)
    status: Mapped[str] = mapped_column(ACCOUNT_STATUS, server_default="active")
    linux_kind: Mapped[str] = mapped_column(LINUX_KIND, server_default="hidden")
    uid: Mapped[int | None] = mapped_column(Integer, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    last_login_at: Mapped[datetime | None] = mapped_column(TS)
    home: Mapped[str | None] = mapped_column(Text)   # None: /home/<username>


class WebSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    csrf_token: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = _now()
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    acting_as_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))


class PasswordToken(Base):
    __tablename__ = "password_tokens"
    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(TOKEN_PURPOSE)
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(TS)
    used_at: Mapped[datetime | None] = mapped_column(TS)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_email_at", "email", "at"),
                      Index("ix_login_attempts_ip_at", "ip", "at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT)
    ip: Mapped[str | None] = mapped_column(INET)
    at: Mapped[datetime] = _now()
    success: Mapped[bool] = mapped_column(Boolean)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (Index("ux_applications_pending_email", "email", unique=True,
                            postgresql_where=text("status = 'pending'")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT)
    full_name: Mapped[str] = mapped_column(Text)
    role_title: Mapped[str] = mapped_column(Text)
    organisation: Mapped[str | None] = mapped_column(Text)
    contact_number: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(APPLICATION_STATUS, server_default="pending")
    created_at: Mapped[datetime] = _now()
    ip: Mapped[str | None] = mapped_column(INET)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    note: Mapped[str | None] = mapped_column(Text)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))


class AllowEntry(Base):
    __tablename__ = "allowlist"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(ALLOW_KIND)
    value: Mapped[str] = mapped_column(CITEXT, unique=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    created_at: Mapped[datetime] = _now()


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    updated_at: Mapped[datetime] = _now()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = _now()
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    acting_admin_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    action: Mapped[str] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[Any] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    result: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(AUDIT_SOURCE)


class OutboxMessage(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    to_addr: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    html: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime] = _now()
    sent_at: Mapped[datetime | None] = mapped_column(TS)
    last_error: Mapped[str | None] = mapped_column(Text)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_account_submitted", "account_id", "submitted_at"),)
    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    kind: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    folder: Mapped[str] = mapped_column(Text)
    spec: Mapped[Any] = mapped_column(JSONB)
    script: Mapped[str] = mapped_column(Text)
    submitted_at: Mapped[datetime] = _now()
    time_limit_s: Mapped[int | None] = mapped_column(Integer)
    last_state: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(TS)
    warned_at: Mapped[datetime | None] = mapped_column(TS)


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("account_id", "name", name="uq_templates_account_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    spec: Mapped[Any] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()
