"""my list

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-24 22:51:39.710729
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "my_list_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=8), nullable=False),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("poster_path", sa.String(length=255), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_my_list_items_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_my_list_items")),
        sa.UniqueConstraint(
            "user_id",
            "media_type",
            "media_id",
            name=op.f("uq_my_list_items_user_id_media_type_media_id"),
        ),
    )
    with op.batch_alter_table("my_list_items", schema=None) as batch_op:
        batch_op.create_index(
            "ix_my_list_items_user_id_added_at", ["user_id", "added_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("my_list_items", schema=None) as batch_op:
        batch_op.drop_index("ix_my_list_items_user_id_added_at")

    op.drop_table("my_list_items")
