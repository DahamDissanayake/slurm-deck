"""agent_settings: the admin settings deck-agent reads (the extension cap and
others), through a view only sd_agent_ro may select from.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE VIEW agent_settings AS SELECT key, value FROM settings")
    op.execute("GRANT SELECT ON agent_settings TO sd_agent_ro")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS agent_settings")
