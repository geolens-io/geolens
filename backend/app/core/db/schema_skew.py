"""MIG-02 — startup schema-head skew guard.

Refuse to boot when the database's applied migration heads do not match the
heads the running image's migration scripts declare. Booting the API/worker
on a schema-skewed DB silently serves a broken or out-of-date schema; this
guard converts that into a loud, fail-closed ``RuntimeError`` at startup.

Two skew directions are both fatal: DB behind (the image declares revisions
the DB has not applied — the migrate service did not run, or ran an older
image; on a fresh/empty DB ``db_heads == set()`` is the extreme case) and DB
ahead (the DB has revisions the image's scripts lack — the classic
image-rollback case, reverted to a build whose scripts predate them).

Script-head discovery mirrors ``alembic/env.py``: the base
``alembic/versions`` directory plus any extra version directories from
``geolens.migrations`` entry points (the enterprise overlay), so the guard is
correct for both OSS single-head and enterprise two-head graphs without
duplicating env.py's connection/migration logic.
"""

from __future__ import annotations

import pathlib
from importlib.metadata import entry_points as iter_entry_points

import structlog
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.core.config import settings

logger = structlog.stdlib.get_logger(__name__)

#: Matches env.py's ``version_table_schema="catalog"``. The skew read MUST
#: target the same schema or it sees an empty/absent version table and
#: wrongly reports "DB behind".
_VERSION_TABLE_SCHEMA = "catalog"
_VERSION_TABLE = "alembic_version"

#: Resolves the backend root and alembic config/versions dir relative to this
#: file, so the guard does not depend on the process CWD.
_THIS_DIR = pathlib.Path(__file__).resolve().parent
#: backend/ root (…/app/core/db -> up 3).
_BACKEND_DIR = _THIS_DIR.parents[2]
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"
_BASE_VERSIONS = _BACKEND_DIR / "alembic" / "versions"


def _discover_extra_migration_paths() -> list[str]:
    """Discover overlay migration version dirs from ``geolens.migrations``.

    Mirrors ``alembic/env.py``'s ``_discover_migration_paths`` (the enterprise
    e-chain lives in the overlay package, contributed via this entry point
    group). Deliberately tolerant: a missing/uninstallable overlay is the
    normal OSS case and yields no extra paths. env.py itself is never
    imported here, since importing it executes ``run_migrations_online()`` at
    module top level.
    """
    paths: list[str] = []
    for ep in iter_entry_points(group="geolens.migrations"):
        try:
            fn = ep.load()
        except (ModuleNotFoundError, ImportError):
            # Overlay genuinely not installed — normal for OSS deployments.
            continue
        except Exception:  # broad: a third-party/overlay migration entry point can fail to load for arbitrary reasons; warn + skip so the skew guard never crashes app boot
            logger.warning(
                "schema_skew: failed to load migration entry point — its "
                "version dir will be absent from the script-head computation",
                entry_point=getattr(ep, "name", str(ep)),
                exc_info=True,
            )
            continue
        try:
            if callable(fn):
                for p in fn():
                    if pathlib.Path(p).is_dir():
                        paths.append(str(p))
        except Exception:  # broad: an overlay-supplied migration-path provider can raise anything; warn + skip so the skew guard never crashes app boot
            logger.warning(
                "schema_skew: migration-path provider failed — its version "
                "dir will be absent from the script-head computation",
                entry_point=getattr(ep, "name", str(ep)),
                exc_info=True,
            )
    return paths


def _build_alembic_config() -> Config:
    """Build an alembic ``Config`` with overlay version dirs appended.

    Reuses the on-disk ``alembic.ini`` (so ``script_location`` etc. stay the
    single source of truth) and augments ``version_locations`` exactly as
    env.py does, so ``ScriptDirectory.get_heads()`` reflects the full graph
    (OSS + any installed overlay).
    """
    cfg = Config(str(_ALEMBIC_INI))
    # The ini's script_location is relative to backend/; make alembic resolve
    # it regardless of CWD by pinning to the absolute alembic dir.
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))

    extra = _discover_extra_migration_paths()
    if extra:
        base = cfg.get_main_option("version_locations") or str(_BASE_VERSIONS)
        cfg.set_main_option("version_locations", base + " " + " ".join(extra))
    return cfg


def build_alembic_config() -> Config:
    """Supported external entry point building the merged alembic ``Config``
    (OSS base + installed overlay version dirs)."""
    return _build_alembic_config()


def get_script_heads() -> set[str]:
    """Return the set of head revisions the image's migration scripts declare."""
    script = ScriptDirectory.from_config(_build_alembic_config())
    return set(script.get_heads())


def _read_db_heads_sync(connection) -> set[str]:
    """Read the DB's applied heads from the catalog-schema version table."""
    context = MigrationContext.configure(
        connection=connection,
        opts={"version_table_schema": _VERSION_TABLE_SCHEMA},
    )
    return set(context.get_current_heads())


async def get_current_heads() -> set[str]:
    """Return the set of revisions currently applied in the database.

    Empty set means a fresh DB (no ``alembic_version`` rows / table absent in
    the catalog schema).

    Resolves the engine via ``app.core.db`` at call time (not a module-level
    import) so the test ``client`` fixture's monkeypatch of
    ``app.core.db.engine`` to the migrated test engine is honored.
    """
    import app.core.db as db_module

    async with db_module.engine.connect() as conn:
        return await conn.run_sync(_read_db_heads_sync)


async def assert_schema_in_sync() -> None:
    """Fail closed unless DB heads exactly equal the image's script heads.

    Raises ``RuntimeError`` on any mismatch (set inequality covers both the
    DB-behind and DB-ahead directions, plural-head enterprise graphs, and the
    fresh-empty-DB case). On match, logs the agreed heads at INFO and returns.
    """
    script_heads = get_script_heads()
    db_heads = await get_current_heads()

    if db_heads == script_heads:
        logger.info(
            "schema_skew_check_passed",
            heads=sorted(script_heads),
        )
        return

    missing_in_db = sorted(script_heads - db_heads)  # image expects, DB lacks
    extra_in_db = sorted(db_heads - script_heads)  # DB has, image lacks

    direction_hints: list[str] = []
    if missing_in_db:
        direction_hints.append(
            f"DB is BEHIND the image (missing revisions: {missing_in_db}; "
            f"the migrate service must run, or the DB is empty)"
        )
    if extra_in_db:
        direction_hints.append(
            f"DB is AHEAD of the image (revisions {extra_in_db} are applied "
            f"but absent from this image's scripts; the image is older than "
            f"the DB — a rollback)"
        )
    hint = "; ".join(direction_hints) if direction_hints else "heads differ"

    raise RuntimeError(
        f"schema skew: DB at {sorted(db_heads)}, image expects "
        f"{sorted(script_heads)}; {hint}. Run migrations (the dedicated "
        f"migrate service / 'alembic upgrade heads') or deploy an image whose "
        f"migration scripts match the database. Refusing to start. "
        f"(database='{settings.postgres_db}', references MIG-02)"
    )
