"""Shared alembic subprocess runner for migration tests.

fix(#933): seven test files each carried their own ``_run_alembic`` copy, and
none of them knew that migration ``0030_records_spatial_extent_type``
deliberately REFUSES to downgrade while any ``catalog.records`` row holds a
MULTIPOLYGON ``spatial_extent``. Any test that committed a seam-crossing
extent therefore broke every migration test that later downgraded past 0030
in the same xdist worker — and the failure surfaced in an unrelated file,
reproducible only when both tests share a worker (each worker owns its own
database, so a single-file run never shows it).

This module is the one place that knows about refuse-to-coerce downgrades:

- ``0030``: normalized automatically before every downgrade (see below).
- ``0010_oauth_github_provider_type``: refuses while GitHub OAuth providers
  exist. Not auto-cleaned — deleting provider rows is semantic test state,
  and the only test that creates them (test_oauth_github_migration) manages
  its own cleanup.
- ``0005_dormant_tenancy``: refuses while tenant-scoped data exists. Same
  reasoning; no current test trips it.

If a future migration gains a refuse-to-coerce downgrade, teach this module
about it rather than adding cleanup to individual test files.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy

_BACKEND_DIR = Path(__file__).parent.parent.resolve()
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"

# The remediation SQL that 0030's own error message prescribes. Collapsing a
# two-ring seam extent to its envelope LOSES the antimeridian-crossing shape
# (the envelope is -180..180) — that loss is acceptable ONLY in a test
# database, where extents are fixture noise. Never lift this into
# application code: in production the refusal is the feature (#892/#901).
#
# Guarded so it is a no-op when the schema is already below the revisions
# that shaped catalog.records (e.g. a second downgrade step from an already
# downgraded state).
_SEAM_EXTENT_NORMALIZATION = """
DO $$
BEGIN
    IF to_regclass('catalog.records') IS NOT NULL AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'catalog'
          AND table_name = 'records'
          AND column_name = 'spatial_extent'
    ) THEN
        UPDATE catalog.records
        SET spatial_extent = ST_Envelope(spatial_extent)
        WHERE GeometryType(spatial_extent) = 'MULTIPOLYGON';
    END IF;
END
$$;
"""


def normalize_seam_extents() -> None:
    """Collapse MULTIPOLYGON spatial_extents so downgrades can cross 0030."""
    from app.core.config import settings

    engine = sqlalchemy.create_engine(
        settings.test_database_url_sync, isolation_level="AUTOCOMMIT"
    )
    try:
        with engine.connect() as conn:
            conn.execute(sqlalchemy.text(_SEAM_EXTENT_NORMALIZATION))
    finally:
        engine.dispose()


def run_alembic(
    *args: str, extra_env: dict | None = None
) -> subprocess.CompletedProcess:
    """Run an alembic command via subprocess against the per-worker TEST DB.

    Uses the backend .venv python so the env matches what pytest runs with.
    PYTHONPATH is set so env.py can ``from app.core.config import settings``.
    POSTGRES_DB targets the per-worker test DB (isolated + conftest-migrated
    to head) so destructive downgrade/upgrade roundtrips never mutate the
    SHARED main DB (``postgres`` on CI), which would corrupt sibling workers
    and the drift check.

    Every ``downgrade`` is preceded by ``normalize_seam_extents()`` — with the
    current head at/above 0030, even a plain ``downgrade -1`` crosses the
    refuse-to-coerce guard on its first step, so the normalization runs
    unconditionally rather than parsing the revision graph (it is idempotent
    and free when no seam extents exist).
    """
    from app.core.config import settings

    if args and args[0] == "downgrade":
        normalize_seam_extents()

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_BACKEND_DIR)
    env["POSTGRES_DB"] = settings.postgres_db_test
    # fix(#933): stripped for determinism — migration 0012's dims fallback
    # reads these from the subprocess env, and every caller should see exactly
    # what its test injects via extra_env, never ambient shell state.
    env.pop("EMBEDDING_DIMS", None)
    env.pop("ENV_ONLY_CONFIG", None)
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(_ALEMBIC_INI), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_BACKEND_DIR),
    )
