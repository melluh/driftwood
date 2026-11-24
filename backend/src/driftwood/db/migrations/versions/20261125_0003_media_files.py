"""media files

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("root", sa.String(length=64), nullable=False),
        sa.Column("path", sa.String(length=4096), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("mtime_ns", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("missing_since", sa.DateTime(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("probe", sa.JSON(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_files")),
        sa.UniqueConstraint("root", "path", name=op.f("uq_media_files_root_path")),
    )
    with op.batch_alter_table("media_files", schema=None) as batch_op:
        batch_op.create_index("ix_media_files_state", ["state"], unique=False)

    op.create_table(
        "media_file_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=8), nullable=False),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("episode", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["media_files.id"],
            name=op.f("fk_media_file_links_file_id_media_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_file_links")),
        sa.UniqueConstraint(
            "file_id",
            "media_type",
            "media_id",
            "season",
            "episode",
            name=op.f("uq_media_file_links_file_id_media_type_media_id_season_episode"),
        ),
    )
    with op.batch_alter_table("media_file_links", schema=None) as batch_op:
        batch_op.create_index(
            "ix_media_file_links_media_type_media_id",
            ["media_type", "media_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("media_file_links", schema=None) as batch_op:
        batch_op.drop_index("ix_media_file_links_media_type_media_id")
    op.drop_table("media_file_links")

    with op.batch_alter_table("media_files", schema=None) as batch_op:
        batch_op.drop_index("ix_media_files_state")
    op.drop_table("media_files")
