"""The account's email in the views deck-agent reads, so job.submit can check
a script's --mail-user against it. For an admin viewing as a user, the
session row's email is the admin's own; deck-agent takes the target's from
agent_accounts.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

ACCOUNTS = """
    SELECT username, role::text AS role, linux_kind::text AS linux_kind, uid,
           status::text AS status, created_at,
           COALESCE(last_login_at, created_at) AS last_seen_at{email}
    FROM accounts a"""
SESSIONS = """
    SELECT s.token_hash, a.username, a.role::text AS role,
           a.linux_kind::text AS linux_kind, a.uid, a.status::text AS status,
           s.created_at, s.last_seen_at, t.username AS acting_as_username{email}
    FROM sessions s
    JOIN accounts a ON a.id = s.account_id
    LEFT JOIN accounts t ON t.id = s.acting_as_account_id"""
EMAIL = ", a.email::text AS email"


def _views(email: str) -> None:
    """Recreate both views; sd_agent_ro reads them and nothing else."""
    for view, sql in (("agent_accounts", ACCOUNTS), ("agent_sessions", SESSIONS)):
        op.execute(f"DROP VIEW IF EXISTS {view}")
        op.execute(f"CREATE VIEW {view} AS {sql.format(email=email)}")
        op.execute(f"GRANT SELECT ON {view} TO sd_agent_ro")


def upgrade() -> None:
    _views(EMAIL)


def downgrade() -> None:
    _views("")
