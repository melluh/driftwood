from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes, stored naive (SQLite has no timezone support)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; use timezone-aware UTC datetimes")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    # Stable constraint names, so Alembic can alter them (SQLite batch mode needs this).
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class User(Base):
    """A person who signed in through the OIDC provider, keyed by (issuer, subject)."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class UserSession(Base):
    """A signed-in browser. Only a hash of the cookie token is stored."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)

    user: Mapped[User] = relationship(lazy="joined")


class MediaFileState(StrEnum):
    present = "present"
    missing = "missing"


class MediaFile(Base):
    __tablename__ = "media_files"
    __table_args__ = (
        UniqueConstraint("root", "path"),
        Index("ix_media_files_state", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    root: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(String(4096))
    size: Mapped[int] = mapped_column(BigInteger)
    mtime_ns: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(16))
    missing_since: Mapped[datetime | None] = mapped_column(UTCDateTime)
    attributes: Mapped[dict[str, object]] = mapped_column(JSON)
    probe: Mapped[dict[str, object] | None] = mapped_column(JSON)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    links: Mapped[list["MediaFileLink"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", passive_deletes=True
    )


class MediaFileLink(Base):
    __tablename__ = "media_file_links"
    __table_args__ = (
        UniqueConstraint("file_id", "media_type", "media_id", "season", "episode"),
        Index("ix_media_file_links_media_type_media_id", "media_type", "media_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("media_files.id", ondelete="CASCADE"))
    media_type: Mapped[str] = mapped_column(String(8))
    media_id: Mapped[int]
    season: Mapped[int | None]
    episode: Mapped[int | None]

    file: Mapped[MediaFile] = relationship(back_populates="links")


class DownloadState(StrEnum):
    downloading = "downloading"
    importing = "importing"
    """Complete in qBittorrent; being linked into the library."""
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


ACTIVE_DOWNLOAD_STATES = (DownloadState.downloading.value, DownloadState.importing.value)


class Download(Base):
    """A torrent Driftwood handed to qBittorrent to watch a title (or episode)."""

    __tablename__ = "downloads"
    __table_args__ = (
        Index("ix_downloads_state", "state"),
        Index("ix_downloads_media_type_media_id", "media_type", "media_id"),
        Index("ix_downloads_infohash", "infohash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    media_type: Mapped[str] = mapped_column(String(8))
    media_id: Mapped[int]
    season: Mapped[int | None]
    episode: Mapped[int | None]
    title: Mapped[str] = mapped_column(String(512))
    """The TMDB title, used to name the imported files."""
    year: Mapped[int | None]
    indexer: Mapped[str] = mapped_column(String(64))
    guid: Mapped[str] = mapped_column(String(128))
    release_title: Mapped[str] = mapped_column(String(1024))
    infohash: Mapped[str] = mapped_column(String(64))
    size: Mapped[int | None] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(String(2048))
    file_id: Mapped[int | None] = mapped_column(ForeignKey("media_files.id", ondelete="SET NULL"))
    """The imported library file, once completed."""
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class MyListItem(Base):
    """A title a user saved to "My list".

    TMDB stays the source of truth for display data; the title, year and poster
    are a snapshot so the list still renders when TMDB can't be reached.
    """

    __tablename__ = "my_list_items"
    __table_args__ = (
        UniqueConstraint("user_id", "media_type", "media_id"),
        Index("ix_my_list_items_user_id_added_at", "user_id", "added_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    media_type: Mapped[str] = mapped_column(String(8))
    media_id: Mapped[int]
    title: Mapped[str] = mapped_column(String(512))
    year: Mapped[int | None]
    poster_path: Mapped[str | None] = mapped_column(String(255))
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class WatchProgress(Base):
    """How far a user got into a movie, or into one episode of a series.

    Movies have no season / episode; each series episode gets its own row.
    `completed` is sticky: it stays set when the user goes back to rewatch.
    """

    __tablename__ = "watch_progress"
    __table_args__ = (
        # NULLs never collide in a unique constraint, so movies get their own (partial) index.
        Index(
            "uq_watch_progress_episode",
            "user_id",
            "media_type",
            "media_id",
            "season",
            "episode",
            unique=True,
            sqlite_where=text("season IS NOT NULL"),
            postgresql_where=text("season IS NOT NULL"),
        ),
        Index(
            "uq_watch_progress_title",
            "user_id",
            "media_type",
            "media_id",
            unique=True,
            sqlite_where=text("season IS NULL"),
            postgresql_where=text("season IS NULL"),
        ),
        Index("ix_watch_progress_user_id_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    media_type: Mapped[str] = mapped_column(String(8))
    media_id: Mapped[int]
    season: Mapped[int | None]
    episode: Mapped[int | None]
    position: Mapped[float]
    """Seconds."""
    duration: Mapped[float]
    """Seconds."""
    completed: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
