import asyncio
import logging
import os
from logging.config import fileConfig

from alembic import context
import sqlalchemy as sa
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from pgvector.sqlalchemy import Vector

from app.core.config import settings
from app.core.db import Base

import app.modules.auth.models  # noqa: F401 -- register models for autogenerate
import app.modules.auth.oauth.models  # noqa: F401
import app.modules.audit.models  # noqa: F401
import app.modules.catalog.datasets.domain.models  # noqa: F401
import app.modules.embed_tokens.models  # noqa: F401
import app.platform.jobs.models  # noqa: F401
import app.platform.refresh.models  # noqa: F401
import app.modules.catalog.collections.models  # noqa: F401
import app.modules.catalog.maps.models  # noqa: F401
import app.processing.raster.models  # noqa: F401
import app.modules.catalog.search.saved  # noqa: F401
import app.core.db.models  # noqa: F401
import app.processing.embeddings.models  # noqa: F401
import app.processing.ai.token_usage  # noqa: F401
import app.modules.catalog.sources.models  # noqa: F401
import app.modules.tenancy.models  # noqa: F401 -- register tenancy models

config = context.config
if config.config_file_name is not None:
    # The stdlib default disable_existing_loggers=True sets
    # .disabled on every logger registered before this call and not named in
    # alembic.ini, and nothing in the app or the test suite restores that flag.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

import pathlib  # noqa: E402
from importlib.metadata import entry_points as iter_entry_points  # noqa: E402

_log = logging.getLogger("alembic.env")


def _discover_migration_paths() -> list[str]:
    """Return migration directories from installed plugins.

    An empty entry-point group means no overlay is installed.
    Any installed provider failure must abort migration to prevent a
    successful exit over an incomplete schema.
    """
    paths = []
    for ep in iter_entry_points(group="geolens.migrations"):
        try:
            fn = ep.load()
        except Exception as exc:  # broad: abort on any overlay failure.
            raise RuntimeError(
                f"geolens.migrations entry point {getattr(ep, 'name', ep)!r} is "
                "installed but failed to import; refusing to migrate with an "
                "incomplete version_locations set"
            ) from exc
        try:
            if callable(fn):
                for p in fn():
                    if pathlib.Path(p).is_dir():
                        paths.append(p)
        except Exception as exc:  # broad: abort on any overlay failure.
            raise RuntimeError(
                f"geolens.migrations entry point {getattr(ep, 'name', ep)!r} is "
                "installed but its migration-path provider failed; refusing to "
                "migrate with an incomplete version_locations set"
            ) from exc
    return paths


def _propagate_extra_paths_to_live_script(live_script, extra_paths) -> None:
    """Add overlay paths to the existing ScriptDirectory and rebuild its map.

    The CLI creates this object before env.py runs, so changing Config alone
    leaves the live revision graph unchanged. Preserve the core versions path.

    Propagation failure must abort migration; otherwise the CLI
    can report success while skipping installed overlay revisions.
    """
    try:
        from alembic.script import revision as _alembic_revision

        # An empty version_locations uses the implicit core versions directory.
        existing = list(getattr(live_script, "version_locations", []) or [])
        if not existing:
            existing = [str(pathlib.Path(live_script.dir) / "versions")]
        for p in extra_paths:
            if p not in existing:
                existing.append(p)
        live_script.version_locations = existing
        live_script.revision_map = _alembic_revision.RevisionMap(
            live_script._load_revisions
        )
    except Exception as exc:  # broad: abort on any overlay failure.
        raise RuntimeError(
            "Failed to propagate enterprise version directories onto the "
            "live ScriptDirectory — 'alembic upgrade heads' would silently "
            "skip the enterprise e-chain. This is a configuration error, not "
            "OSS; refusing to migrate with an incomplete version_locations "
            "set on the live ScriptDirectory."
        ) from exc


# Append enterprise migration paths to version_locations
_extra_paths = _discover_migration_paths()

# If this is explicitly an enterprise deployment but no enterprise
# migration paths were discovered, fail loudly rather than silently migrating a
# fresh DB without the e-chain (which dies later on SAML UndefinedColumn).
if (
    os.environ.get("GEOLENS_EDITION", "").lower().strip() == "enterprise"
    and not _extra_paths
):
    raise RuntimeError(
        "GEOLENS_EDITION=enterprise but no enterprise migration paths were "
        "discovered from the 'geolens.migrations' entry point group. The "
        "enterprise overlay is either not installed or failed to load (see "
        "preceding error log). Refusing to migrate without the e-chain — a "
        "fresh DB would migrate without e001/e002 and break SAML login."
    )

# Multi-tenant mode requires migration 0005 for tenant columns and unique indexes.
# Check the packaged file directly to avoid importing application settings here.
_tenancy_mode = os.environ.get("GEOLENS_TENANCY_MODE", "").lower().strip()
if _tenancy_mode == "multi_tenant":
    import pathlib as _pathlib

    _versions_dir = _pathlib.Path(__file__).parent / "versions"
    _tenancy_file = _versions_dir / "0005_dormant_tenancy.py"
    if not _tenancy_file.exists():
        raise RuntimeError(
            "GEOLENS_TENANCY_MODE=multi_tenant but the tenancy migration "
            "'0005_dormant_tenancy' was not found at "
            f"{_tenancy_file}. "
            "Refusing to run migrations — a multi_tenant deploy without "
            "0005 would lack the tenant_id columns and partial-unique indexes. "
            "Install a core package containing 0005_dormant_tenancy or "
            "unset GEOLENS_TENANCY_MODE to use single_tenant mode."
        )

if _extra_paths:
    _base_versions = config.get_main_option("version_locations") or "alembic/versions"
    _all_paths = _base_versions + " " + " ".join(_extra_paths)
    config.set_main_option("version_locations", _all_paths)

    # See _propagate_extra_paths_to_live_script's docstring above.
    # Tolerant of offline / no-active-context (revision command,
    # autogenerate) — those construct their ScriptDirectory from the
    # (now-augmented) Config directly, so there is nothing live to patch.
    try:
        _live_script = context.script  # the EnvironmentContext's ScriptDirectory
    except Exception:  # broad: offline commands may have no active context.
        _live_script = None
    if _live_script is not None:
        _propagate_extra_paths_to_live_script(_live_script, _extra_paths)

target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    """Only include objects in the catalog schema."""
    if type_ == "schema":
        return name == "catalog"
    return True


def include_object(obj, name, type_, reflected, compare_to):
    """Exclude objects managed outside SQLAlchemy from autogenerate.

    Procrastinate creates its objects through raw SQL. The dimension-dependent
    HNSW index is built at runtime. Neither appears in model metadata, so
    comparing them would emit incorrect removal operations.

    SAML columns belong to core migration 0008 and must remain
    visible to drift detection, including on Community deployments.
    """
    if name and name.startswith("procrastinate_"):
        return False
    if type_ == "index" and name == "ix_record_embeddings_hnsw":
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
    # CV-1: the raw COMMIT above persists the preamble DDL at the DB level, but
    # SQLAlchemy's autobegin immediately re-arms an implicit transaction on the
    # connection. If left active, MigrationContext.__init__ (in context.configure
    # below) snapshots _in_external_transaction=True, which makes
    # context.begin_transaction() return a nullcontext and never set
    # ctx._transaction. That breaks the standard
    # `op.get_context().autocommit_block()` pattern (CREATE INDEX CONCURRENTLY in
    # migrations) with `assert self._transaction is not None`. Rolling back here
    # clears SQLAlchemy's empty autobegun transaction (the preamble COMMIT above
    # already persisted the schema + version table, so nothing real is discarded)
    # so begin_transaction() owns a real, committing transaction and
    # autocommit_block() works. Side effect: with _in_external_transaction now
    # False, the whole migration run becomes a single atomic transaction
    # (Alembic's default for transactional-DDL Postgres) -- a mid-chain failure
    # rolls the entire run back instead of leaving a resumable partial state.
    # See backend/alembic/README.md.
    connection.rollback()
    # Register pgvector's column type for reflection so autogenerate / `alembic
    # check` recognise the `vector` type instead of warning "Did not recognize
    # type vector" and reporting phantom drift on record_embeddings.embedding.
    connection.dialect.ischema_names["vector"] = Vector
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema="catalog",
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
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
