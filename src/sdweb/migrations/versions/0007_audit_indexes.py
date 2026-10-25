"""Indexes so the admin audit page filters and pages without scanning the table.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


INDEXES = {"ix_audit_events_ts": ["ts"], "ix_audit_events_actor_ts": ["actor_id", "ts"],
           "ix_audit_events_action_ts": ["action", "ts"]}


def upgrade() -> None:
    for name, columns in INDEXES.items():
        op.create_index(name, "audit_events", columns)


def downgrade() -> None:
    for name in INDEXES:
        op.drop_index(name, "audit_events")
