"""Alembic environment.

At runtime `Database.migrate()` passes its own connection in. From the CLI
(`uv run alembic revision --autogenerate -m "..."`) the URL comes from settings.
"""

import asyncio
from typing import Any, Literal

from alembic import context
from sqlalchemy import Connection

from driftwood.db.models import Base, UTCDateTime

target_metadata = Base.metadata


def render_item(type_: str, obj: Any, autogen_context: Any) -> str | Literal[False]:
    # UTCDateTime only converts in Python; the column itself is a plain DATETIME.
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime()"
    return False


def run_with_connection(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite can't ALTER most things in place
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_from_settings() -> None:
    from driftwood.config import get_settings
    from driftwood.db import Database

    # Through Database so the SQLite directory exists and pragmas match runtime.
    database = Database(get_settings().database.url)
    try:
        async with database.engine.connect() as connection:
            await connection.run_sync(run_with_connection)
            await connection.commit()
    finally:
        await database.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported")

connection = context.config.attributes.get("connection")
if connection is not None:
    run_with_connection(connection)
else:
    asyncio.run(run_from_settings())
