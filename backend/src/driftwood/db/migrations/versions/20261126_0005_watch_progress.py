"""watch progress

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "watch_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=8), nullable=False),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("episode", sa.Integer(), nullable=True),
        sa.Column("position", sa.Float(), nullable=False),
        sa.Column("duration", sa.Float(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_watch_progress_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watch_progress")),
    )
    with op.batch_alter_table("watch_progress", schema=None) as batch_op:
        batch_op.create_index(
            "uq_watch_progress_episode",
            ["user_id", "media_type", "media_id", "season", "episode"],
            unique=True,
            sqlite_where=sa.text("season IS NOT NULL"),
            postgresql_where=sa.text("season IS NOT NULL"),
        )
        batch_op.create_index(
            "uq_watch_progress_title",
            ["user_id", "media_type", "media_id"],
            unique=True,
            sqlite_where=sa.text("season IS NULL"),
            postgresql_where=sa.text("season IS NULL"),
        )
        batch_op.create_index(
            "ix_watch_progress_user_id_updated_at", ["user_id", "updated_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("watch_progress", schema=None) as batch_op:
        batch_op.drop_index("ix_watch_progress_user_id_updated_at")
        batch_op.drop_index("uq_watch_progress_title")
        batch_op.drop_index("uq_watch_progress_episode")

    op.drop_table("watch_progress")
