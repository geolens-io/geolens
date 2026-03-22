import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.database import Base

import app.auth.models  # noqa: F401 -- register models for autogenerate
import app.datasets.models  # noqa: F401
import app.jobs.models  # noqa: F401
import app.collections.models  # noqa: F401
import app.search.saved  # noqa: F401
import app.maps.models  # noqa: F401
import app.embeddings.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    """Only include objects in the catalog schema."""
    if type_ == "schema":
        return name == "catalog"
    return True


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema="catalog",
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    url = config.get_main_option("sqlalchemy.url") or settings.database_url
    # Pass SSL connect_args when using the app settings URL (not alembic.ini override)
    connect_args = {}
    if not config.get_main_option("sqlalchemy.url"):
        connect_args = settings.database_connect_args
    connectable = async_engine_from_config(
        {"sqlalchemy.url": url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


run_migrations_online()
