"""Migration 0055's backfill of the PMTiles download distribution.

``_DISTRIBUTION_TEMPLATES`` (records/service.py) now generates a
``pmtiles`` download row at dataset creation, mirroring 0013's GeoParquet
and 0054's FlatGeobuf precedents — but that table is only consulted by
``generate_distributions()``, so a spatial dataset that existed before this
migration's deploy never gets the row until an unrelated geometry-mode
flip happens to run reconcile. This covers the migration that closes that
gap for datasets already in the database.

The round trip is real — ``alembic downgrade`` to 0055's own predecessor
(0055's downgrade deletes exactly the auto-generated ``pmtiles`` download
rows, which is also what a dataset created via ``generate_distributions``
already holds) followed by ``alembic upgrade head`` re-runs the backfill
over rows this test committed first, through the same alembic.ini/env.py
stack CI uses.

Run with: cd backend && set -a && source ../.env.test && set +a &&
          uv run pytest tests/test_pmtiles_distribution_backfill.py -x -q
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.catalog.records.service import create_distribution
from tests.alembic_helpers import (
    enterprise_migrations_present,
    fresh_query as _fresh_query,
    run_alembic as _run_alembic,
)
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


_SKIP_UNDER_OVERLAY = pytest.mark.skipif(
    enterprise_migrations_present(),
    reason=(
        "OSS migration round trip; multi-head under the enterprise overlay — "
        "runs in the no-overlay Pytest Parallel Isolation job instead."
    ),
)


def _migration_0055():
    """The migration module this file is about, loaded for its own constants.

    Copying the down_revision out by hand would let the two drift silently.
    """
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0055_backfill_pmtiles_distributions.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0055", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _revision_below_0055() -> str:
    """The revision 0055 sits on, read from 0055's own ``down_revision``.

    fix(#1383 precedent): a bare ``downgrade -1`` reverts whatever the
    CURRENT head is, so it silently steps over 0055 the moment a later
    migration lands on top. Naming the target keeps this test about its own
    migration whatever else is stacked above it.
    """
    return _migration_0055().down_revision


@_SKIP_UNDER_OVERLAY
class TestPmtilesDistributionBackfill:
    async def test_a_spatial_dataset_missing_the_row_is_backfilled(
        self, test_db_session
    ) -> None:
        """The case the migration exists for.

        ``tests.factories.create_dataset`` inserts the Record/Dataset pair
        directly — no ``generate_distributions`` call — so this dataset
        starts with zero distribution rows, exactly the shape of a dataset
        that predates the pmtiles template entry entirely.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"pmtiles backfill spatial {uuid.uuid4().hex[:8]}",
            geometry_type="MultiPolygon",
        )
        await test_db_session.commit()

        try:
            target = _revision_below_0055()
            down = _run_alembic("downgrade", target)
            assert down.returncode == 0, (
                f"alembic downgrade {target} failed (rc={down.returncode}):\n"
                f"stdout: {down.stdout}\nstderr: {down.stderr}"
            )
            up = _run_alembic("upgrade", "head")
            assert up.returncode == 0, (
                f"alembic upgrade head failed (rc={up.returncode}):\n"
                f"stdout: {up.stdout}\nstderr: {up.stderr}"
            )

            rows = await _fresh_query(
                "SELECT format, url, title, protocol, media_type, is_primary, "
                "auto_generated FROM catalog.record_distributions "
                "WHERE record_id = :record_id AND distribution_type = 'download' "
                "AND format = 'pmtiles'",
                {"record_id": dataset.record_id},
            )
            assert len(rows) == 1, (
                f"expected exactly one backfilled pmtiles row, got {len(rows)}"
            )
            row = rows[0]
            assert row.url == f"/datasets/{dataset.id}/export?format=pmtiles"
            assert row.media_type == "application/vnd.pmtiles"
            assert row.auto_generated is True
            assert row.is_primary is False
        finally:
            await _fresh_query(
                "DELETE FROM catalog.record_distributions WHERE record_id = :r",
                {"r": dataset.record_id},
            )
            await _fresh_query(
                "DELETE FROM catalog.datasets WHERE id = :d", {"d": dataset.id}
            )
            await _fresh_query(
                "DELETE FROM catalog.records WHERE id = :r",
                {"r": dataset.record_id},
            )

    async def test_a_non_spatial_dataset_is_left_alone(self, test_db_session) -> None:
        """The predicate excludes geometry_type IS NULL, like generate_distributions."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"pmtiles backfill nonspatial {uuid.uuid4().hex[:8]}",
            geometry_type=None,
        )
        await test_db_session.commit()

        try:
            target = _revision_below_0055()
            down = _run_alembic("downgrade", target)
            assert down.returncode == 0
            up = _run_alembic("upgrade", "head")
            assert up.returncode == 0

            rows = await _fresh_query(
                "SELECT id FROM catalog.record_distributions "
                "WHERE record_id = :record_id AND distribution_type = 'download' "
                "AND format = 'pmtiles'",
                {"record_id": dataset.record_id},
            )
            assert len(rows) == 0, (
                "a non-spatial dataset must never get a pmtiles download row"
            )
        finally:
            await _fresh_query(
                "DELETE FROM catalog.record_distributions WHERE record_id = :r",
                {"r": dataset.record_id},
            )
            await _fresh_query(
                "DELETE FROM catalog.datasets WHERE id = :d", {"d": dataset.id}
            )
            await _fresh_query(
                "DELETE FROM catalog.records WHERE id = :r",
                {"r": dataset.record_id},
            )

    async def test_rerunning_the_backfill_is_a_no_op(self, test_db_session) -> None:
        """Idempotent: NOT EXISTS plus the unique constraint make a second run inert."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"pmtiles backfill idempotent {uuid.uuid4().hex[:8]}",
            geometry_type="MultiPolygon",
        )
        await test_db_session.commit()

        try:
            target = _revision_below_0055()
            assert _run_alembic("downgrade", target).returncode == 0
            assert _run_alembic("upgrade", "head").returncode == 0
            assert _run_alembic("upgrade", "head").returncode == 0

            rows = await _fresh_query(
                "SELECT id FROM catalog.record_distributions "
                "WHERE record_id = :record_id AND distribution_type = 'download' "
                "AND format = 'pmtiles'",
                {"record_id": dataset.record_id},
            )
            assert len(rows) == 1, (
                "running the backfill twice must not duplicate the row"
            )
        finally:
            await _fresh_query(
                "DELETE FROM catalog.record_distributions WHERE record_id = :r",
                {"r": dataset.record_id},
            )
            await _fresh_query(
                "DELETE FROM catalog.datasets WHERE id = :d", {"d": dataset.id}
            )
            await _fresh_query(
                "DELETE FROM catalog.records WHERE id = :r",
                {"r": dataset.record_id},
            )

    async def test_a_users_own_pmtiles_row_does_not_suppress_the_platform_row(
        self, test_db_session
    ) -> None:
        """The NOT EXISTS guard must read auto_generated only (0054's lesson, applied here).

        ``generate_distributions`` deliberately probes only auto-generated
        rows (fix(#1370)) so a user's own download/pmtiles entry at some
        other URL never blocks the platform's own export row — both are
        meant to coexist. A migration that checked ANY row would leave this
        dataset permanently missing the platform row after an upgrade.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"pmtiles backfill user-row {uuid.uuid4().hex[:8]}",
            geometry_type="MultiPolygon",
        )
        await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="pmtiles",
            url="https://example.org/mine.pmtiles",
        )
        await test_db_session.commit()

        try:
            target = _revision_below_0055()
            assert _run_alembic("downgrade", target).returncode == 0
            up = _run_alembic("upgrade", "head")
            assert up.returncode == 0, (
                f"alembic upgrade head failed (rc={up.returncode}):\n"
                f"stdout: {up.stdout}\nstderr: {up.stderr}"
            )

            rows = await _fresh_query(
                "SELECT url, auto_generated FROM catalog.record_distributions "
                "WHERE record_id = :record_id AND distribution_type = 'download' "
                "AND format = 'pmtiles'",
                {"record_id": dataset.record_id},
            )
            by_url = {row.url: row.auto_generated for row in rows}
            assert by_url.get("https://example.org/mine.pmtiles") is False, (
                "the user's own row must survive untouched"
            )
            assert (
                by_url.get(f"/datasets/{dataset.id}/export?format=pmtiles") is True
            ), "the platform row must still be backfilled alongside it"
            assert len(rows) == 2
        finally:
            await _fresh_query(
                "DELETE FROM catalog.record_distributions WHERE record_id = :r",
                {"r": dataset.record_id},
            )
            await _fresh_query(
                "DELETE FROM catalog.datasets WHERE id = :d", {"d": dataset.id}
            )
            await _fresh_query(
                "DELETE FROM catalog.records WHERE id = :r",
                {"r": dataset.record_id},
            )

    async def test_a_user_row_at_the_template_url_does_not_raise(
        self, test_db_session
    ) -> None:
        """The collision the narrowed guard reopens (0054's lesson, applied here).

        A user row at the exact guessable URL the INSERT targets collides on
        ``uq_record_distribution`` once the existence check no longer treats
        it as "the pair is taken". ``ON CONFLICT DO NOTHING`` resolves it the
        same way ``reconcile_distributions`` does at runtime (see
        ``TestATemplateUrlCollisionDoesNotRaise`` in
        test_distribution_reconcile_1314.py) — the migration must not raise,
        and must not leave two rows fighting over one URL.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"pmtiles backfill url-collision {uuid.uuid4().hex[:8]}",
            geometry_type="MultiPolygon",
        )
        await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="pmtiles",
            url=f"/datasets/{dataset.id}/export?format=pmtiles",
        )
        await test_db_session.commit()

        try:
            target = _revision_below_0055()
            assert _run_alembic("downgrade", target).returncode == 0
            up = _run_alembic("upgrade", "head")
            assert up.returncode == 0, (
                f"alembic upgrade head failed (rc={up.returncode}):\n"
                f"stdout: {up.stdout}\nstderr: {up.stderr}"
            )

            rows = await _fresh_query(
                "SELECT url, auto_generated FROM catalog.record_distributions "
                "WHERE record_id = :record_id AND distribution_type = 'download' "
                "AND format = 'pmtiles'",
                {"record_id": dataset.record_id},
            )
            assert len(rows) == 1, (
                f"expected the user's row to be the only survivor, got {rows}"
            )
            assert rows[0].auto_generated is False, (
                "the user's row at the template URL must not be overwritten"
            )
        finally:
            await _fresh_query(
                "DELETE FROM catalog.record_distributions WHERE record_id = :r",
                {"r": dataset.record_id},
            )
            await _fresh_query(
                "DELETE FROM catalog.datasets WHERE id = :d", {"d": dataset.id}
            )
            await _fresh_query(
                "DELETE FROM catalog.records WHERE id = :r",
                {"r": dataset.record_id},
            )
