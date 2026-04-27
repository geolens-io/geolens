import asyncio
from logging.config import fileConfig

from alembic import context
import sqlalchemy as sa
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.core.db import Base

import app.modules.auth.models  # noqa: F401 -- register models for autogenerate
import app.modules.auth.oauth.models  # noqa: F401
import app.modules.audit.models  # noqa: F401
import app.modules.catalog.datasets.domain.models  # noqa: F401
import app.modules.embed_tokens.models  # noqa: F401
import app.platform.jobs.models  # noqa: F401
import app.modules.catalog.collections.models  # noqa: F401
import app.modules.catalog.maps.models  # noqa: F401
import app.processing.raster.models  # noqa: F401
import app.modules.catalog.search.saved  # noqa: F401
import app.core.db.models  # noqa: F401
import app.processing.embeddings.models  # noqa: F401
import app.processing.ai.token_usage  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

import pathlib  # noqa: E402
from importlib.metadata import entry_points as iter_entry_points  # noqa: E402


def _discover_migration_paths() -> list[str]:
    """Discover additional migration version directories from plugins."""
    paths = []
    for ep in iter_entry_points(group="geolens.migrations"):
        try:
            fn = ep.load()
            if callable(fn):
                for p in fn():
                    if pathlib.Path(p).is_dir():
                        paths.append(p)
        except Exception:
            pass  # Non-fatal: core migrations still run
    return paths


# Append enterprise migration paths to version_locations
_extra_paths = _discover_migration_paths()
if _extra_paths:
    _base_versions = config.get_main_option("version_locations") or "alembic/versions"
    _all_paths = _base_versions + " " + " ".join(_extra_paths)
    config.set_main_option("version_locations", _all_paths)

target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    """Only include objects in the catalog schema."""
    if type_ == "schema":
        return name == "catalog"
    return True


def do_run_migrations(connection):
    # Ensure catalog schema exists before Alembic creates its version table
    connection.execute(sa.text("CREATE SCHEMA IF NOT EXISTS catalog"))
    connection.execute(sa.text("COMMIT"))
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
