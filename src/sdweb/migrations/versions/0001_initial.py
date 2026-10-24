"""Initial schema: accounts, sessions, tokens, applications, allow-list,
settings, audit and outbox; the UID sequence; the sd_agent_ro role and the
two views deck-agent reads.

Revision ID: 0001
Revises:
"""

import os

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
VIEWS = ("agent_sessions", "agent_accounts")
TYPES = ("account_role", "account_status", "linux_kind", "token_purpose",
         "application_status", "allow_kind", "audit_source")

SEED = {
    "default_time_limit": "08:00:00",
    "extension_cap_hours": 24,
    "submit_rate_per_hour": 20,
    "disk_alert_percent": 90,
    "mail_enabled": True,
    "maintenance_banner": None,
    "terminal_jobs_enabled": True,
    "cluster_location": "",
}


def _id() -> sa.Column:
    return sa.Column("id", sa.Integer, sa.Identity(), primary_key=True)


def _now(name: str) -> sa.Column:
    return sa.Column(name, TS, server_default=NOW, nullable=False)


def _fk(name: str, nullable: bool = True, ondelete: str | None = None) -> sa.Column:
    return sa.Column(name, sa.Integer, sa.ForeignKey("accounts.id", ondelete=ondelete),
                     nullable=nullable)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key) or str(default)
    if not raw.isdigit():
        raise ValueError(f"{key} must be an integer, got {raw!r}")
    return int(raw)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "accounts", _id(),
        sa.Column("email", CITEXT, nullable=False, unique=True),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("username", sa.Text, nullable=False, unique=True),
        sa.Column("role", sa.Enum("user", "admin", name="account_role"), nullable=False),
        sa.Column("status", sa.Enum("active", "disabled", "deleted", name="account_status"),
                  nullable=False, server_default="active"),
        sa.Column("linux_kind", sa.Enum("hidden", "shell", name="linux_kind"),
                  nullable=False, server_default="hidden"),
        sa.Column("uid", sa.Integer, unique=True),
        sa.Column("password_hash", sa.Text),
        _now("created_at"),
        _fk("created_by_id"),
        sa.Column("last_login_at", TS),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.Text, primary_key=True),
        _fk("account_id", nullable=False, ondelete="CASCADE"),
        sa.Column("csrf_token", sa.Text, nullable=False),
        _now("created_at"),
        _now("last_seen_at"),
        sa.Column("ip", INET),
        sa.Column("user_agent", sa.Text),
        _fk("acting_as_account_id"),
    )
    op.create_table(
        "password_tokens",
        sa.Column("token_hash", sa.Text, primary_key=True),
        _fk("account_id", nullable=False, ondelete="CASCADE"),
        sa.Column("purpose", sa.Enum("set", "reset", name="token_purpose"), nullable=False),
        _now("created_at"),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS),
    )
    op.create_table(
        "login_attempts", _id(),
        sa.Column("email", CITEXT, nullable=False),
        sa.Column("ip", INET),
        _now("at"),
        sa.Column("success", sa.Boolean, nullable=False),
    )
    op.create_index("ix_login_attempts_email_at", "login_attempts", ["email", "at"])
    op.create_index("ix_login_attempts_ip_at", "login_attempts", ["ip", "at"])
    op.create_table(
        "applications", _id(),
        sa.Column("email", CITEXT, nullable=False),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("role_title", sa.Text, nullable=False),
        sa.Column("organisation", sa.Text),
        sa.Column("contact_number", sa.Text, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("status", sa.Enum("pending", "approved", "rejected",
                                    name="application_status"),
                  nullable=False, server_default="pending"),
        _now("created_at"),
        sa.Column("ip", INET),
        _fk("decided_by_id"),
        sa.Column("decided_at", TS),
        sa.Column("note", sa.Text),
        _fk("account_id"),
    )
    op.create_index("ux_applications_pending_email", "applications", ["email"], unique=True,
                    postgresql_where=sa.text("status = 'pending'"))
    op.create_table(
        "allowlist", _id(),
        sa.Column("kind", sa.Enum("domain", "address", name="allow_kind"), nullable=False),
        sa.Column("value", CITEXT, nullable=False, unique=True),
        _fk("created_by_id"),
        _now("created_at"),
    )
    settings = op.create_table(
        "settings",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", JSONB, nullable=True),
        _fk("updated_by_id"),
        _now("updated_at"),
    )
    op.create_table(
        "audit_events", _id(),
        _now("ts"),
        _fk("actor_id"),
        _fk("acting_admin_id"),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("target", sa.Text),
        sa.Column("detail", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", sa.Text, nullable=False),
        sa.Column("source", sa.Enum("web", "agent", "worker", name="audit_source"),
                  nullable=False),
    )
    op.create_table(
        "outbox", _id(),
        sa.Column("to_addr", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("html", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        _now("created_at"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        _now("next_attempt_at"),
        sa.Column("sent_at", TS),
        sa.Column("last_error", sa.Text),
    )
    op.bulk_insert(settings, [{"key": k, "value": v} for k, v in SEED.items()])

    # New accounts' UIDs: never highest-plus-one, so a deleted account's UID
    # (and its files) are never handed to someone else.
    lo, hi = _env_int("SD_WEB_UID_MIN", 20000), _env_int("SD_WEB_UID_MAX", 59999)
    op.execute(f"CREATE SEQUENCE web_uid_seq START {lo} MINVALUE {lo} MAXVALUE {hi} NO CYCLE")

    op.execute("""
        CREATE VIEW agent_accounts AS
        SELECT username, role::text AS role, linux_kind::text AS linux_kind, uid,
               status::text AS status, created_at,
               COALESCE(last_login_at, created_at) AS last_seen_at
        FROM accounts""")
    op.execute("""
        CREATE VIEW agent_sessions AS
        SELECT s.token_hash, a.username, a.role::text AS role,
               a.linux_kind::text AS linux_kind, a.uid, a.status::text AS status,
               s.created_at, s.last_seen_at, t.username AS acting_as_username
        FROM sessions s
        JOIN accounts a ON a.id = s.account_id
        LEFT JOIN accounts t ON t.id = s.acting_as_account_id""")
    _agent_role()


def _agent_role() -> None:
    """sd_agent_ro may log in and read the two views, nothing else. Roles are
    cluster-wide, so an existing one is reused and its password reset."""
    password = context.config.attributes.get("agent_password", "")
    if not password:
        raise RuntimeError("SD_AGENT_DB_PASSWORD is required to create the sd_agent_ro role")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sd_agent_ro') THEN
                CREATE ROLE sd_agent_ro;
            END IF;
        END $$""")
    # ALTER ROLE takes no bind parameters, so the password goes in as a
    # transaction-local setting and format(%L) quotes it server side.
    op.get_bind().execute(sa.text("SELECT set_config('sdweb.agent_pw', :pw, true)"),
                          {"pw": password})
    op.execute("""
        DO $$ BEGIN
            EXECUTE format('ALTER ROLE sd_agent_ro LOGIN NOSUPERUSER NOCREATEDB '
                           'NOCREATEROLE PASSWORD %L', current_setting('sdweb.agent_pw'));
        END $$""")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM sd_agent_ro")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM sd_agent_ro")
    for view in VIEWS:
        op.execute(f"GRANT SELECT ON {view} TO sd_agent_ro")


def downgrade() -> None:
    # The role is left in place: it is cluster-wide and may serve other databases.
    for view in VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {view}")
    op.execute("DROP SEQUENCE IF EXISTS web_uid_seq")
    for table in ("outbox", "audit_events", "settings", "allowlist", "applications",
                  "login_attempts", "password_tokens", "sessions", "accounts"):
        op.drop_table(table)
    for name in TYPES:
        op.execute(f"DROP TYPE IF EXISTS {name}")
