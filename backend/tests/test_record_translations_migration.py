"""Focused regression coverage for migration 0014's online-safe prefix."""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests.repo_paths import repo_root

_REPO_ROOT = repo_root(__file__)
_BACKEND_DIR = _REPO_ROOT / "backend"
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"
_MIGRATION_PATH = _BACKEND_DIR / "alembic/versions/0014_record_translations.py"
_PRE_TRANSLATIONS_REVISION = "0013_backfill_geoparquet_distributions"
_TITLE_PREFIX = "migration-0014-lock-test-"


def _enterprise_migrations_present() -> bool:
    for entry_point in entry_points(group="geolens.migrations"):
        try:
            provider = entry_point.load()
            if callable(provider) and any(Path(path).is_dir() for path in provider()):
                return True
        except Exception:
            pass
    return False


_SKIP_UNDER_OVERLAY = pytest.mark.skipif(
    _enterprise_migrations_present(),
    reason="OSS migration round-trip runs in the no-overlay migration job",
)


def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    import os

    from app.core.config import settings

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(_BACKEND_DIR)
    environment["POSTGRES_DB"] = settings.postgres_db_test
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(_ALEMBIC_INI), *args],
        capture_output=True,
        text=True,
        env=environment,
        cwd=str(_BACKEND_DIR),
    )


async def _fresh_query(query: str, params: dict | None = None):
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    engine = create_async_engine(
        settings.test_database_url,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as connection:
            result = await connection.execute(sa.text(query), params or {})
            return result.fetchall() if result.returns_rows else None
    finally:
        await engine.dispose()


async def _cleanup_test_objects() -> None:
    await _fresh_query(
        "DROP TRIGGER IF EXISTS migration_0014_count_language_updates "
        "ON catalog.records"
    )
    await _fresh_query(
        "DROP FUNCTION IF EXISTS catalog.migration_0014_count_language_updates()"
    )
    await _fresh_query("DROP TABLE IF EXISTS catalog.migration_0014_update_counter")
    await _fresh_query(
        "DELETE FROM catalog.records WHERE title LIKE :p",
        {"p": f"{_TITLE_PREFIX}%"},
    )


def test_upgrade_uses_committed_not_valid_then_targeted_validate() -> None:
    source = _MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade = source[source.index("def upgrade()") : source.index("def downgrade()")]
    not_valid = upgrade.index("NOT VALID")
    targeted_update = upgrade.index("IS DISTINCT FROM")
    validate = upgrade.index("VALIDATE CONSTRAINT")

    assert upgrade.count("autocommit_block()") == 2
    assert not_valid < targeted_update < validate
    assert "op.create_check_constraint" not in upgrade


@_SKIP_UNDER_OVERLAY
async def test_upgrade_normalizes_legacy_values_and_validates_constraint() -> None:
    try:
        result = _run_alembic("downgrade", _PRE_TRANSLATIONS_REVISION)
        assert result.returncode == 0, result.stderr
        await _cleanup_test_objects()
        await _fresh_query(
            "CREATE TABLE catalog.migration_0014_update_counter "
            "(updates integer NOT NULL)"
        )
        await _fresh_query(
            "INSERT INTO catalog.migration_0014_update_counter VALUES (0)"
        )
        await _fresh_query(
            """
            CREATE FUNCTION catalog.migration_0014_count_language_updates()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              IF NEW.title LIKE 'migration-0014-lock-test-%' THEN
                UPDATE catalog.migration_0014_update_counter
                SET updates = updates + 1;
              END IF;
              RETURN NEW;
            END
            $$
            """
        )
        await _fresh_query(
            """
            CREATE TRIGGER migration_0014_count_language_updates
            BEFORE UPDATE ON catalog.records
            FOR EACH ROW
            EXECUTE FUNCTION catalog.migration_0014_count_language_updates()
            """
        )
        # Production-shaped skew: most rows are already canonical and must not
        # be rewritten merely because the migration scans the table.
        await _fresh_query(
            """
            INSERT INTO catalog.records (title, language, visibility, record_status)
            SELECT :p || 'bulk-' || n, 'fr-ca', 'private', 'active'
            FROM generate_series(1, 1000) AS n
            """,
            {"p": _TITLE_PREFIX},
        )
        await _fresh_query(
            """
            INSERT INTO catalog.records (title, language, visibility, record_status)
            VALUES
              (:p || 'upper', 'EN', 'private', 'active'),
              (:p || 'underscore', 'pt_BR', 'private', 'active'),
              (:p || 'blank', '   ', 'private', 'active'),
              (:p || 'freeform', 'bad value', 'private', 'active'),
              (:p || 'canonical', 'fr-ca', 'private', 'active')
            """,
            {"p": _TITLE_PREFIX},
        )

        result = _run_alembic("upgrade", "heads")
        assert result.returncode == 0, result.stderr
        rows = await _fresh_query(
            """
            SELECT title, language
            FROM catalog.records
            WHERE title LIKE :p
              AND title NOT LIKE :bulk
            ORDER BY title
            """,
            {
                "p": f"{_TITLE_PREFIX}%",
                "bulk": f"{_TITLE_PREFIX}bulk-%",
            },
        )
        assert dict(rows) == {
            f"{_TITLE_PREFIX}blank": "en",
            f"{_TITLE_PREFIX}canonical": "fr-ca",
            f"{_TITLE_PREFIX}freeform": "en",
            f"{_TITLE_PREFIX}underscore": "pt-BR",
            f"{_TITLE_PREFIX}upper": "en",
        }
        constraint = await _fresh_query(
            """
            SELECT convalidated
            FROM pg_constraint
            WHERE conrelid = 'catalog.records'::regclass
              AND conname = 'chk_records_language_tag'
            """
        )
        assert constraint == [(True,)]
        update_count = await _fresh_query(
            "SELECT updates FROM catalog.migration_0014_update_counter"
        )
        assert update_count == [(4,)], "only four non-canonical rows should update"
    finally:
        _run_alembic("upgrade", "heads")
        await _cleanup_test_objects()


@_SKIP_UNDER_OVERLAY
async def test_upgrade_retries_after_committed_not_valid_prefix() -> None:
    try:
        result = _run_alembic("downgrade", _PRE_TRANSLATIONS_REVISION)
        assert result.returncode == 0, result.stderr
        await _fresh_query(
            "ALTER TABLE catalog.records ALTER COLUMN language TYPE VARCHAR(35)"
        )
        await _fresh_query(
            "ALTER TABLE catalog.records "
            "ADD CONSTRAINT chk_records_language_tag "
            "CHECK (language IS NULL OR "
            "language ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$') NOT VALID"
        )

        result = _run_alembic("upgrade", "heads")
        assert result.returncode == 0, result.stderr
        constraint = await _fresh_query(
            """
            SELECT convalidated
            FROM pg_constraint
            WHERE conrelid = 'catalog.records'::regclass
              AND conname = 'chk_records_language_tag'
            """
        )
        assert constraint == [(True,)]
    finally:
        _run_alembic("upgrade", "heads")
