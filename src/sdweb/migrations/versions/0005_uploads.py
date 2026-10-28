"""uploads: one row per tus upload, for resume and ownership.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("dest_dir", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("replace", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("offset", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("finished_at", TS),
        sa.Column("aborted_at", TS),
        sa.Column("grant", sa.Text, nullable=False),
        sa.Column("grant_expires_at", TS, nullable=False),
    )
    op.create_index("ix_uploads_account", "uploads", ["account_id"])


def downgrade() -> None:
    op.drop_table("uploads")
