"""env_builds: one row per environment build or prebuilt install job.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "env_builds",
        sa.Column("job_id", sa.Text, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("kind", sa.Text, nullable=False),   # build | install
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("ok", sa.Boolean),                    # null until the result is known
        sa.Column("missing", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", TS),
    )


def downgrade() -> None:
    op.drop_table("env_builds")
