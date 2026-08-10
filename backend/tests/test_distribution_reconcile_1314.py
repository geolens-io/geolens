"""Reconciling auto-generated distributions when a dataset's modality changes (#1314).

``generate_distributions`` runs once, at dataset creation, and merges rather
than replaces. Everything below is about the write that closes the gap that
leaves: a registered table that later gains a geometry column has to start
advertising the spatial formats, one that loses its geometry has to stop, and
neither direction may take a user's own distribution rows with it.

The preservation policy is stated on ``reconcile_distributions``' docstring.
These tests are what stop it from being only a docstring — including the
limitation it admits to, which is pinned here deliberately so that relaxing it
later fails a test instead of quietly changing behaviour.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import RecordDistribution
from app.modules.catalog.records.service import (
    create_distribution,
    generate_distributions,
    reconcile_distributions,
    update_distribution,
)
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

# What `generate_distributions` emits per modality, as pairs. Spelled out here
# rather than imported from the module under test: a test that derives its
# expectation from the same table the code reads would pass through a change
# to that table, which is the change most worth noticing.
_SPATIAL_PAIRS = {
    ("download", "gpkg"),
    ("download", "geojson"),
    ("download", "shp"),
    ("download", "parquet"),
    ("download", "csv"),
    ("ogc_features", "geojson"),
    ("vector_tiles", "pbf"),
}
_TABULAR_PAIRS = {("download", "csv"), ("ogc_features", "geojson")}


async def _pairs(session: AsyncSession, record_id: uuid.UUID) -> set[tuple[str, str]]:
    rows = (
        await session.execute(
            select(
                RecordDistribution.distribution_type,
                RecordDistribution.format,
            ).where(RecordDistribution.record_id == record_id)
        )
    ).all()
    return {(row[0], row[1]) for row in rows}


async def _row(
    session: AsyncSession, record_id: uuid.UUID, dist_type: str, fmt: str
) -> RecordDistribution | None:
    return (
        await session.execute(
            select(RecordDistribution).where(
                RecordDistribution.record_id == record_id,
                RecordDistribution.distribution_type == dist_type,
                RecordDistribution.format == fmt,
                RecordDistribution.auto_generated.is_(True),
            )
        )
    ).scalar_one_or_none()


async def _tabular_dataset(session: AsyncSession):
    """A dataset carrying the two rows a non-spatial creation generates."""
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=admin_id, geometry_type=None)
    await generate_distributions(
        session, dataset.id, dataset.record_id, dataset.table_name, geometry_type=None
    )
    await session.commit()
    return dataset


async def _spatial_dataset(session: AsyncSession):
    """A dataset carrying the seven rows a spatial creation generates."""
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=admin_id)
    await generate_distributions(
        session,
        dataset.id,
        dataset.record_id,
        dataset.table_name,
        geometry_type="POLYGON",
    )
    await session.commit()
    return dataset


class TestModalityFlip:
    """The two directions the issue is about."""

    async def test_gaining_geometry_advertises_the_full_spatial_set(
        self, test_db_session: AsyncSession
    ) -> None:
        dataset = await _tabular_dataset(test_db_session)
        assert await _pairs(test_db_session, dataset.record_id) == _TABULAR_PAIRS

        created, removed = await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()

        assert removed == []
        assert {(c.distribution_type, c.format) for c in created} == (
            _SPATIAL_PAIRS - _TABULAR_PAIRS
        )
        assert await _pairs(test_db_session, dataset.record_id) == _SPATIAL_PAIRS

    async def test_losing_geometry_stops_advertising_the_spatial_set(
        self, test_db_session: AsyncSession
    ) -> None:
        dataset = await _spatial_dataset(test_db_session)
        assert await _pairs(test_db_session, dataset.record_id) == _SPATIAL_PAIRS

        created, removed = await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type=None,
        )
        await test_db_session.commit()

        assert created == []
        assert set(removed) == _SPATIAL_PAIRS - _TABULAR_PAIRS
        assert await _pairs(test_db_session, dataset.record_id) == _TABULAR_PAIRS

    async def test_reconciling_to_the_same_modality_changes_nothing(
        self, test_db_session: AsyncSession
    ) -> None:
        """Idempotent, so a caller that over-calls it cannot churn the rows."""
        dataset = await _spatial_dataset(test_db_session)

        created, removed = await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()

        assert (created, removed) == ([], [])
        assert await _pairs(test_db_session, dataset.record_id) == _SPATIAL_PAIRS


class TestPreservationPolicy:
    """What survives a demote, and what the model cannot promise to."""

    async def test_a_user_authored_row_survives_both_transitions(
        self, test_db_session: AsyncSession
    ) -> None:
        """``auto_generated=False`` is the whole rule, and it is not a pair filter.

        The colliding row is the sharp case: a user's own GeoPackage entry
        occupies a pair the demote removes, so a reconcile that matched on
        (type, format) alone would delete somebody's hand-written row.
        """
        dataset = await _spatial_dataset(test_db_session)
        mine = await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="gpkg",
            url="https://example.org/mine.gpkg",
            title="My own extract",
        )
        elsewhere = await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="api",
            format="json",
            url="https://example.org/api",
        )
        await test_db_session.commit()

        for geometry_type in (None, "POLYGON", None):
            await reconcile_distributions(
                test_db_session,
                dataset.id,
                dataset.record_id,
                dataset.table_name,
                geometry_type=geometry_type,
            )
        await test_db_session.commit()

        survivors = {
            row.id
            for row in (
                await test_db_session.execute(
                    select(RecordDistribution).where(
                        RecordDistribution.record_id == dataset.record_id,
                        RecordDistribution.auto_generated.is_(False),
                    )
                )
            ).scalars()
        }
        assert survivors == {mine.id, elsewhere.id}
        assert (await test_db_session.get(RecordDistribution, mine.id)).title == (
            "My own extract"
        )

    async def test_a_row_outside_the_generated_set_is_never_removed(
        self, test_db_session: AsyncSession
    ) -> None:
        """The raster and VRT tails write their own ``download`` rows.

        Those are auto-generated in spirit and sometimes in flag, and this
        function does not own them — a demote that swept every auto row would
        delete a COG's only download link.
        """
        dataset = await _spatial_dataset(test_db_session)
        foreign = RecordDistribution(
            record_id=dataset.record_id,
            distribution_type="download",
            format="geotiff",
            url="cogs/abc.tif",
            auto_generated=True,
        )
        test_db_session.add(foreign)
        await test_db_session.commit()

        _created, removed = await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type=None,
        )
        await test_db_session.commit()

        assert ("download", "geotiff") not in removed
        assert await test_db_session.get(RecordDistribution, foreign.id) is not None

    async def test_an_edit_to_an_auto_generated_row_does_not_survive_a_demote(
        self, test_db_session: AsyncSession
    ) -> None:
        """The documented limitation, pinned so relaxing it is a decision.

        ``record_distributions`` has one ``auto_generated`` boolean and no
        per-field provenance, so there is nothing to distinguish an edited
        auto row from a generated one. The demote deletes it either way.
        """
        dataset = await _spatial_dataset(test_db_session)
        gpkg = await _row(test_db_session, dataset.record_id, "download", "gpkg")
        assert gpkg is not None
        gpkg.title = "Edited straight in the database"
        await test_db_session.commit()

        await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type=None,
        )
        await test_db_session.commit()

        assert await test_db_session.get(RecordDistribution, gpkg.id) is None

    async def test_the_api_offers_no_way_to_make_that_edit(
        self, test_db_session: AsyncSession
    ) -> None:
        """Why the limitation above is narrower than it reads.

        The edit the demote cannot preserve is one the service layer refuses
        to make in the first place, so the only way to hold one is a direct
        database write. If this refusal is ever relaxed, the policy on
        ``reconcile_distributions`` needs revisiting — and this test is the
        thing that will say so.
        """
        dataset = await _spatial_dataset(test_db_session)
        gpkg = await _row(test_db_session, dataset.record_id, "download", "gpkg")
        assert gpkg is not None

        with pytest.raises(ValueError, match="auto-generated"):
            await update_distribution(
                test_db_session, gpkg.id, dataset.record_id, title="Nope"
            )


class TestPrimaryFlag:
    """Exactly one generated row is primary, whichever way the modality moved."""

    async def _primary_pairs(
        self, session: AsyncSession, record_id: uuid.UUID
    ) -> set[tuple[str, str]]:
        rows = (
            await session.execute(
                select(RecordDistribution).where(
                    RecordDistribution.record_id == record_id,
                    RecordDistribution.auto_generated.is_(True),
                    RecordDistribution.is_primary.is_(True),
                )
            )
        ).scalars()
        return {(row.distribution_type, row.format) for row in rows}

    async def test_a_promote_moves_primary_from_csv_to_geopackage(
        self, test_db_session: AsyncSession
    ) -> None:
        """Without this the dataset advertises two primary downloads.

        A tabular creation makes CSV primary because GeoPackage is not
        generated at all; the promote generates GeoPackage as primary and the
        merge leaves the CSV row exactly as it was.
        """
        dataset = await _tabular_dataset(test_db_session)
        assert await self._primary_pairs(test_db_session, dataset.record_id) == {
            ("download", "csv")
        }

        await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()

        assert await self._primary_pairs(test_db_session, dataset.record_id) == {
            ("download", "gpkg")
        }

    async def test_a_promote_falls_back_to_csv_when_a_user_row_holds_geopackage(
        self, test_db_session: AsyncSession
    ) -> None:
        """fix(#1314 review round 1): the record must never end up with none.

        ``generate_distributions`` skips any pair a row already occupies, and
        it does not care whether that row is auto-generated. So a promote of a
        dataset whose owner added their own GeoPackage entry generates no
        GeoPackage row — and picking the primary from the modality alone
        cleared the CSV flag to promote a row that was never created.
        """
        dataset = await _tabular_dataset(test_db_session)
        await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="gpkg",
            url="https://example.org/mine.gpkg",
        )
        await test_db_session.commit()

        await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()

        assert await self._primary_pairs(test_db_session, dataset.record_id) == {
            ("download", "csv")
        }

    async def test_a_demote_moves_primary_to_csv(
        self, test_db_session: AsyncSession
    ) -> None:
        """The deleted GeoPackage row takes the only primary flag with it."""
        dataset = await _spatial_dataset(test_db_session)
        assert await self._primary_pairs(test_db_session, dataset.record_id) == {
            ("download", "gpkg")
        }

        await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type=None,
        )
        await test_db_session.commit()

        assert await self._primary_pairs(test_db_session, dataset.record_id) == {
            ("download", "csv")
        }
