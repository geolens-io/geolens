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


# H-21: SAML columns live in the OAuthProvider model so a single
# ``OAuthProvider`` class serves both OSS and enterprise deployments
# (deferred-load pattern, see ``modules/auth/oauth/models.py``). The
# enterprise overlay's migration ``e002_add_saml_columns`` actually adds
# the columns to the database. On OSS-only deployments these columns
# exist in the model but not in the schema, so ``alembic check`` /
# autogenerate always produced 4 false-positive ``add_column`` ops —
# which made ``alembic check`` useless as a CI drift gate (real drift
# would be lost in the noise). We skip those columns from autogenerate
# diff when running OSS-only (no enterprise overlay discovered).
_SAML_COLUMNS = frozenset(
    {"idp_entity_id", "idp_sso_url", "idp_certificate", "sp_entity_id"}
)
_OAUTH_PROVIDERS_TABLE = "oauth_providers"


def include_object(obj, name, type_, reflected, compare_to):
    """Skip procrastinate-managed objects + SAML columns (when OSS-only).

    Procrastinate's tables, types, indexes, sequences, and triggers are created
    via raw SQL in ``0002_procrastinate.py`` and are not declared as SQLAlchemy
    models. Without this filter, ``alembic check`` and autogenerate diff produce
    false-positive ``remove_table`` / ``remove_index`` ops because the metadata
    lacks them.

    SAML columns on ``oauth_providers`` are declared in the model union but
    only created by ``e002_add_saml_columns`` when the enterprise overlay is
    installed. When no overlay is present, those columns are intentional
    schema/model drift and would be reported by ``alembic check`` on every
    OSS deployment — see migration-audit H-21.
    """
    if name and name.startswith("procrastinate_"):
        return False
    if (
        type_ == "column"
        and not _extra_paths
        and name in _SAML_COLUMNS
        and getattr(getattr(obj, "table", None), "name", None) == _OAUTH_PROVIDERS_TABLE
    ):
        # OSS-only deployment: hide the enterprise-overlay-managed SAML
        # columns from autogenerate so 'alembic check' surfaces only real
        # drift.
        return False
    return True


def do_run_migrations(connection):
    # Ensure catalog schema exists before Alembic creates its version table
    connection.execute(sa.text("CREATE SCHEMA IF NOT EXISTS catalog"))
    # Pre-create alembic_version with VARCHAR(255) so descriptive migration
    # names (e.g. `0013_partial_indexes_embed_tokens_ingest_jobs`, 41 chars)
    # don't fail with StringDataRightTruncationError on UPDATE. Alembic's
    # auto-create defaults to VARCHAR(32). Idempotent — the ALTER widens the
    # column on databases where the 32-char form was already created.
    connection.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS catalog.alembic_version ("
            "  version_num VARCHAR(255) NOT NULL, "
            "  CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
            ")"
        )
    )
    connection.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM information_schema.columns "
            "  WHERE table_schema = 'catalog' "
            "    AND table_name = 'alembic_version' "
            "    AND column_name = 'version_num' "
            "    AND character_maximum_length < 255) THEN "
            "  ALTER TABLE catalog.alembic_version "
            "  ALTER COLUMN version_num TYPE VARCHAR(255); "
            "END IF; END $$"
        )
    )
    connection.execute(sa.text("COMMIT"))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema="catalog",
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
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
