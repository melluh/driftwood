"""downloads

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "downloads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("media_type", sa.String(length=8), nullable=False),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("episode", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("indexer", sa.String(length=64), nullable=False),
        sa.Column("guid", sa.String(length=128), nullable=False),
        sa.Column("release_title", sa.String(length=1024), nullable=False),
        sa.Column("infohash", sa.String(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=2048), nullable=True),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["media_files.id"],
            name=op.f("fk_downloads_file_id_media_files"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_downloads_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_downloads")),
    )
    with op.batch_alter_table("downloads", schema=None) as batch_op:
        batch_op.create_index("ix_downloads_infohash", ["infohash"], unique=False)
        batch_op.create_index(
            "ix_downloads_media_type_media_id", ["media_type", "media_id"], unique=False
        )
        batch_op.create_index("ix_downloads_state", ["state"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("downloads", schema=None) as batch_op:
        batch_op.drop_index("ix_downloads_state")
        batch_op.drop_index("ix_downloads_media_type_media_id")
        batch_op.drop_index("ix_downloads_infohash")

    op.drop_table("downloads")
