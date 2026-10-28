"""jobs and templates tables; accounts.home (a shell account's real home;
null means /home/<username>).

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("accounts", sa.Column("home", sa.Text))
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.Text, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("folder", sa.Text, nullable=False),
        sa.Column("spec", JSONB, nullable=False),
        sa.Column("script", sa.Text, nullable=False),
        sa.Column("submitted_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("time_limit_s", sa.Integer),
        sa.Column("last_state", sa.Text),
        sa.Column("last_seen_at", TS),
        sa.Column("warned_at", TS),
    )
    op.create_index("ix_jobs_account_submitted", "jobs", ["account_id", "submitted_at"])
    op.create_table(
        "templates",
        sa.Column("id", sa.Integer, sa.Identity(), primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("spec", JSONB, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("account_id", "name", name="uq_templates_account_name"),
    )


def downgrade() -> None:
    op.drop_table("templates")
    op.drop_table("jobs")
    op.drop_column("accounts", "home")
