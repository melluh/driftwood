from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from alembic import command
from alembic.config import Config
from fastapi import Depends, Request
from sqlalchemy import Connection, event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


class Database:
    def __init__(self, url: str) -> None:
        parsed = make_url(url)
        is_sqlite = parsed.get_backend_name() == "sqlite"
        if is_sqlite and parsed.database and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_async_engine(url)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

        if is_sqlite:

            @event.listens_for(self.engine.sync_engine, "connect")
            def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()

    async def migrate(self) -> None:
        """Bring the schema up to date (`alembic upgrade head`)."""

        def upgrade(connection: Connection) -> None:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        async with self.engine.begin() as connection:
            await connection.run_sync(upgrade)

    async def dispose(self) -> None:
        await self.engine.dispose()


def get_database(request: Request) -> Database:
    return request.app.state.database


async def get_db_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    async with database.sessionmaker() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db_session)]
