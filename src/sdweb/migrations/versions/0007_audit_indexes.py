"""Indexes so the admin audit page filters and pages without scanning the table.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_audit_events_ts", "audit_events", ["ts"])
    op.create_index("ix_audit_events_actor_ts", "audit_events", ["actor_id", "ts"])
    op.create_index("ix_audit_events_action_ts", "audit_events", ["action", "ts"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_action_ts", "audit_events")
    op.drop_index("ix_audit_events_actor_ts", "audit_events")
    op.drop_index("ix_audit_events_ts", "audit_events")
