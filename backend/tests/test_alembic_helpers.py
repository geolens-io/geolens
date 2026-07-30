"""Tests for the shared alembic runner (fix(#933)).

Proves the seam-extent normalization does its one job: a committed
antimeridian-crossing (MULTIPOLYGON) ``spatial_extent`` no longer makes a
downgrade past ``0030_records_spatial_extent_type`` fail for whichever
unrelated migration test happens to share the xdist worker.
"""

from __future__ import annotations

import uuid
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.alembic_helpers import run_alembic
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


def _enterprise_migrations_present() -> bool:
    """Mirror the migration files' overlay skip: multi-head alembic cannot
    disambiguate head / -1, so roundtrips run in the no-overlay job only."""
    for entry_point in entry_points(group="geolens.migrations"):
        try:
            provider = entry_point.load()
            if callable(provider) and any(Path(path).is_dir() for path in provider()):
                return True
        except Exception:
            pass
    return False


@pytest.mark.skipif(
    _enterprise_migrations_present(),
    reason="OSS migration round-trip runs in the no-overlay migration job",
)
async def test_seam_extent_no_longer_breaks_downgrade_past_0030(test_db_session):
    """The exact #924/#933 failure, reproduced then absorbed by the runner.

    A two-ring seam extent is committed, then a downgrade crossing 0030 runs
    via ``run_alembic`` — which normalizes first, so the refuse-to-coerce
    guard never fires. Without the normalization this downgrade exits 1 with
    ``RuntimeError: 1 catalog.records row(s) hold a MULTIPOLYGON``.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"Seam Extent {uuid.uuid4().hex[:8]}",
    )
    # A Fiji-style extent split at the antimeridian: two rings, one on each
    # side — exactly what 0030's downgrade refuses to coerce.
    await test_db_session.execute(
        text(
            """
            UPDATE catalog.records SET spatial_extent = ST_GeomFromText(
              'MULTIPOLYGON(((177 -20, 180 -20, 180 -16, 177 -16, 177 -20)),
                            ((-180 -20, -178 -20, -178 -16, -180 -16, -180 -20)))',
              4326)
            WHERE id = :rid
            """
        ),
        {"rid": str(ds.record_id)},
    )
    await test_db_session.commit()

    try:
        down = run_alembic("downgrade", "0029_api_key_hardening")
        assert down.returncode == 0, (
            "downgrade past 0030 failed despite seam-extent normalization:\n"
            f"stdout:\n{down.stdout}\nstderr:\n{down.stderr}"
        )
    finally:
        # Leave the worker DB at head for sibling tests even on failure.
        up = run_alembic("upgrade", "head")
        assert up.returncode == 0, (
            f"re-upgrade to head failed:\nstdout:\n{up.stdout}\nstderr:\n{up.stderr}"
        )
    # The seeded row survives with its extent collapsed to the envelope —
    # acceptable loss in a test database, which is the helper's whole premise.
