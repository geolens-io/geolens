"""One primary distribution per record (#1383).

``is_primary`` is read as "THE primary distribution" — the OGC Record's
``properties.distributions`` emits it per row, and that is what the dataset
detail response and the STAC item's source record carry. Nothing kept it
singular: every dataset is created with a generated primary (GeoPackage when it
has geometry, CSV when it does not), and one
``POST /records/{id}/distributions/`` carrying ``is_primary: true`` added a
second, leaving consumers two answers and no tiebreak.

Two layers, tested as two things, because they fail differently:

- The service layer DEMOTES on write, so ordinary callers get what they asked
  for (last write wins) and never see an error.
- ``uq_record_distribution_primary`` (migration 0042) is the invariant, in the
  database, where a writer that skips the service cannot route around it — and
  it is what repairs the records that were already double at migration time.

The reconcile side is pinned here too: a user-authored primary outranks
``reconcile_distributions``' normalization, which is what keeps that function's
preservation policy ("never writes a user-authored row") true rather than
merely stated.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.catalog.datasets.domain.models import RecordDistribution
from app.modules.catalog.records.router import _distribution_conflict_detail
from app.modules.catalog.records.service import (
    create_distribution,
    delete_distribution,
    generate_distributions,
    reconcile_distributions,
    update_distribution,
)
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_INDEX_NAME = "uq_record_distribution_primary"


def _migration_0042():
    """The migration module, loaded for its SQL.

    The repair test runs the migration's own statements rather than a
    paraphrase: a repair that stopped matching the rows it is meant to fix
    would otherwise still pass a test that re-implements it.
    """
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0042_record_distribution_single_primary.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0042", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _primaries(
    session: AsyncSession, record_id: uuid.UUID
) -> list[RecordDistribution]:
    """Every row on the record currently flagged primary, generated or not."""
    rows = (
        await session.execute(
            sa.select(RecordDistribution)
            .where(
                RecordDistribution.record_id == record_id,
                RecordDistribution.is_primary.is_(True),
            )
            .order_by(RecordDistribution.id)
        )
    ).scalars()
    return list(rows)


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


async def _tabular_dataset(session: AsyncSession):
    """A dataset carrying the two rows a non-spatial creation generates."""
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=admin_id, geometry_type=None)
    await generate_distributions(
        session, dataset.id, dataset.record_id, dataset.table_name, geometry_type=None
    )
    await session.commit()
    return dataset


class TestDemoteOnWrite:
    """The write paths keep the flag singular, so callers never meet the index."""

    async def test_creating_a_primary_demotes_the_generated_incumbent(
        self, test_db_session: AsyncSession
    ) -> None:
        """The reproduction from the issue, at the service layer."""
        dataset = await _spatial_dataset(test_db_session)
        incumbent = await _primaries(test_db_session, dataset.record_id)
        assert [(d.distribution_type, d.format) for d in incumbent] == [
            ("download", "gpkg")
        ]
        assert incumbent[0].auto_generated is True

        mine = await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="gpkg",
            url="https://example.org/mine.gpkg",
            is_primary=True,
        )
        await test_db_session.commit()

        after = await _primaries(test_db_session, dataset.record_id)
        assert [d.id for d in after] == [mine.id]
        assert after[0].auto_generated is False

    async def test_the_post_from_the_issue_leaves_one_primary(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """The exact request the issue reproduces with, over HTTP.

        Through the router, so the 201 and the demote are shown to be the same
        transaction — a demote that only worked when the service was called
        directly would still leave the API able to write the second primary.
        """
        dataset = await _spatial_dataset(test_db_session)

        resp = await client.post(
            f"/records/{dataset.record_id}/distributions/",
            json={
                "distribution_type": "download",
                "format": "gpkg",
                "url": "https://example.org/mine.gpkg",
                "is_primary": True,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["is_primary"] is True

        listed = await client.get(
            f"/records/{dataset.record_id}/distributions/", headers=admin_auth_header
        )
        assert listed.status_code == 200, listed.text
        primaries = [d for d in listed.json()["distributions"] if d["is_primary"]]
        assert [d["id"] for d in primaries] == [resp.json()["id"]]

    async def test_updating_a_row_to_primary_demotes_the_incumbent(
        self, test_db_session: AsyncSession
    ) -> None:
        """Same rule on the update path — it had the same shape as create."""
        dataset = await _spatial_dataset(test_db_session)
        mine = await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="gpkg",
            url="https://example.org/mine.gpkg",
        )
        await test_db_session.commit()
        assert [
            d.auto_generated
            for d in await _primaries(test_db_session, dataset.record_id)
        ] == [True]

        await update_distribution(
            test_db_session, mine.id, dataset.record_id, is_primary=True
        )
        await test_db_session.commit()

        after = await _primaries(test_db_session, dataset.record_id)
        assert [d.id for d in after] == [mine.id]

    async def test_a_write_that_does_not_claim_the_flag_moves_nothing(
        self, test_db_session: AsyncSession
    ) -> None:
        """Only ``is_primary=True`` demotes. Everything else is untouched."""
        dataset = await _spatial_dataset(test_db_session)
        before = await _primaries(test_db_session, dataset.record_id)

        mine = await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="gpkg",
            url="https://example.org/mine.gpkg",
        )
        await update_distribution(
            test_db_session, mine.id, dataset.record_id, title="Renamed"
        )
        await test_db_session.commit()

        after = await _primaries(test_db_session, dataset.record_id)
        assert [d.id for d in after] == [d.id for d in before]

    async def test_clearing_the_flag_promotes_nothing(
        self, test_db_session: AsyncSession
    ) -> None:
        """Pinned because it is a decision, not an accident.

        A caller saying "this is not the primary" is not saying which one is,
        so the record is left with none until the next reconcile. Restoring
        the generated default here would silently overrule a caller who
        cleared the flag on purpose.
        """
        dataset = await _spatial_dataset(test_db_session)
        mine = await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="gpkg",
            url="https://example.org/mine.gpkg",
            is_primary=True,
        )
        await test_db_session.commit()

        await update_distribution(
            test_db_session, mine.id, dataset.record_id, is_primary=False
        )
        await test_db_session.commit()

        assert await _primaries(test_db_session, dataset.record_id) == []


class TestTheConflictMessage:
    """A 409 that names the right conflict.

    Reachable only from two concurrent writes both claiming the flag (the
    service demotes first, so a lone caller never gets here), and the generic
    duplicate message would send that caller looking for a row that does not
    exist.
    """

    def test_the_primary_index_gets_its_own_wording(self) -> None:
        detail = _distribution_conflict_detail(
            IntegrityError(
                "INSERT",
                {},
                Exception(
                    "duplicate key value violates unique constraint "
                    '"uq_record_distribution_primary"'
                ),
            )
        )
        assert "primary" in detail
        assert "retry" in detail

    def test_the_four_column_constraint_keeps_the_old_wording(self) -> None:
        detail = _distribution_conflict_detail(
            IntegrityError(
                "INSERT",
                {},
                Exception(
                    "duplicate key value violates unique constraint "
                    '"uq_record_distribution"'
                ),
            )
        )
        assert detail == "Duplicate distribution (same record, type, and format)"


class TestTheDatabaseInvariant:
    """What the API cannot route around."""

    async def test_the_index_is_partial_on_record_id(
        self, test_db_session: AsyncSession
    ) -> None:
        """Shape pinned: one row per record WHERE is_primary, nothing wider.

        A non-partial unique index on ``record_id`` would allow one
        distribution per record, full stop — the same DDL statement minus four
        words, and a mistake no functional test above would notice, because
        every record they build has one primary anyway.
        """
        rows = (
            await test_db_session.execute(
                sa.text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = 'catalog' "
                    "AND tablename = 'record_distributions' "
                    "AND indexname = :name"
                ),
                {"name": _INDEX_NAME},
            )
        ).fetchall()
        assert rows, f"{_INDEX_NAME} is missing from catalog.record_distributions"
        indexdef = rows[0][0]
        assert "CREATE UNIQUE INDEX" in indexdef, indexdef
        assert "(record_id)" in indexdef, indexdef
        assert "WHERE is_primary" in indexdef, indexdef

    async def test_a_second_primary_written_around_the_service_is_rejected(
        self, test_db_session: AsyncSession
    ) -> None:
        """The service is not the only writer; the index is the backstop."""
        dataset = await _spatial_dataset(test_db_session)

        test_db_session.add(
            RecordDistribution(
                record_id=dataset.record_id,
                distribution_type="download",
                format="gpkg",
                url="https://example.org/second-primary.gpkg",
                is_primary=True,
            )
        )
        with pytest.raises(IntegrityError) as excinfo:
            await test_db_session.flush()
        assert _INDEX_NAME in str(excinfo.value)
        await test_db_session.rollback()

    async def test_two_records_may_each_have_their_own_primary(
        self, test_db_session: AsyncSession
    ) -> None:
        """The index partitions by record — it is not a global singleton."""
        first = await _spatial_dataset(test_db_session)
        second = await _spatial_dataset(test_db_session)

        assert len(await _primaries(test_db_session, first.record_id)) == 1
        assert len(await _primaries(test_db_session, second.record_id)) == 1


class TestDeleteHandsTheFlagBack:
    """Withdrawing the row withdraws the claim (#1383)."""

    async def test_deleting_the_user_primary_restores_the_geopackage(
        self, test_db_session: AsyncSession
    ) -> None:
        dataset = await _spatial_dataset(test_db_session)
        mine = await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="gpkg",
            url="https://example.org/mine.gpkg",
            is_primary=True,
        )
        await test_db_session.commit()

        await delete_distribution(test_db_session, mine.id, dataset.record_id)
        await test_db_session.commit()

        after = await _primaries(test_db_session, dataset.record_id)
        assert [(d.distribution_type, d.format) for d in after] == [
            ("download", "gpkg")
        ]
        assert after[0].auto_generated is True

    async def test_the_restore_follows_the_modality(
        self, test_db_session: AsyncSession
    ) -> None:
        """A tabular record generates no GeoPackage row, so CSV takes it back."""
        dataset = await _tabular_dataset(test_db_session)
        mine = await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="geojson",
            url="https://example.org/mine.geojson",
            is_primary=True,
        )
        await test_db_session.commit()

        await delete_distribution(test_db_session, mine.id, dataset.record_id)
        await test_db_session.commit()

        after = await _primaries(test_db_session, dataset.record_id)
        assert [(d.distribution_type, d.format) for d in after] == [("download", "csv")]

    async def test_deleting_a_row_that_was_not_primary_moves_nothing(
        self, test_db_session: AsyncSession
    ) -> None:
        dataset = await _spatial_dataset(test_db_session)
        before = await _primaries(test_db_session, dataset.record_id)
        mine = await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="gpkg",
            url="https://example.org/mine.gpkg",
        )
        await test_db_session.commit()

        await delete_distribution(test_db_session, mine.id, dataset.record_id)
        await test_db_session.commit()

        after = await _primaries(test_db_session, dataset.record_id)
        assert [d.id for d in after] == [d.id for d in before]


class TestReconcileYieldsToAUserPrimary:
    """``reconcile_distributions`` still never writes a user-authored row.

    Its normalization promotes a generated row for the new modality. With a
    user's own row holding the flag, promoting would either advertise two
    primaries (before) or violate the index (after) — so it yields, which is
    the boundary its preservation policy now names.
    """

    async def _dataset_with_a_user_primary(self, session: AsyncSession):
        dataset = await _tabular_dataset(session)
        mine = await create_distribution(
            session,
            dataset.record_id,
            distribution_type="download",
            format="geojson",
            url="https://example.org/mine.geojson",
            is_primary=True,
        )
        await session.commit()
        return dataset, mine

    async def test_a_promote_does_not_take_the_flag_back(
        self, test_db_session: AsyncSession
    ) -> None:
        dataset, mine = await self._dataset_with_a_user_primary(test_db_session)

        await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()

        after = await _primaries(test_db_session, dataset.record_id)
        assert [d.id for d in after] == [mine.id]

    async def test_the_generated_geopackage_still_gets_created(
        self, test_db_session: AsyncSession
    ) -> None:
        """Yielding is about the flag only — the promote still adds its rows."""
        dataset, _ = await self._dataset_with_a_user_primary(test_db_session)

        await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()

        rows = (
            await test_db_session.execute(
                sa.select(RecordDistribution).where(
                    RecordDistribution.record_id == dataset.record_id,
                    RecordDistribution.distribution_type == "download",
                    RecordDistribution.format == "gpkg",
                )
            )
        ).scalars()
        gpkg = list(rows)
        assert len(gpkg) == 1
        assert gpkg[0].auto_generated is True
        assert gpkg[0].is_primary is False

    async def test_the_job_transaction_stays_usable(
        self, test_db_session: AsyncSession
    ) -> None:
        """Reconcile runs inside a refresh job's write transaction.

        An IntegrityError raised there aborts the whole job, turning a
        metadata correction into a failed refresh — the same failure mode the
        ON CONFLICT clause in ``generate_distributions`` exists to avoid.
        """
        dataset, _ = await self._dataset_with_a_user_primary(test_db_session)

        await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        # Same transaction, still writable.
        await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="shp",
            url="https://example.org/after.zip",
        )
        await test_db_session.commit()

    async def test_a_demote_still_normalizes_the_generated_rows(
        self, test_db_session: AsyncSession
    ) -> None:
        """With no user primary, the old behaviour is unchanged.

        Spatial to tabular deletes the GeoPackage row that held the flag; CSV
        has to take it, and the demote-before-promote ordering is what lets
        the tabular-to-spatial direction move it back without tripping the
        index.
        """
        dataset = await _spatial_dataset(test_db_session)

        await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type=None,
        )
        await test_db_session.commit()
        assert [
            (d.distribution_type, d.format)
            for d in await _primaries(test_db_session, dataset.record_id)
        ] == [("download", "csv")]

        await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()
        assert [
            (d.distribution_type, d.format)
            for d in await _primaries(test_db_session, dataset.record_id)
        ] == [("download", "gpkg")]


class TestMigrationRepair:
    """Migration 0042 fixes the records that were already double.

    The whole test runs in ONE transaction that is rolled back, on its own
    connection: reaching the pre-migration state means dropping the index, and
    postgres DDL is transactional, so nothing here is ever visible to another
    test or left behind. It deliberately does not take ``test_db_session`` —
    ``DROP INDEX`` needs the table's ACCESS EXCLUSIVE lock, which a second
    open transaction on the same table would hold.
    """

    async def test_the_repair_keeps_one_primary_and_the_index_then_builds(
        self,
    ) -> None:
        from app.core.config import settings

        migration = _migration_0042()
        engine = create_async_engine(settings.test_database_url)
        try:
            async with engine.connect() as conn:
                trans = await conn.begin()
                try:
                    await conn.execute(sa.text("SET LOCAL lock_timeout = '10s'"))
                    record_id = (
                        await conn.execute(
                            sa.text(
                                "INSERT INTO catalog.records "
                                "(title, visibility, record_status) "
                                "VALUES ('1383 repair', 'public', 'published') "
                                "RETURNING id"
                            )
                        )
                    ).scalar_one()

                    await conn.execute(
                        sa.text(f"DROP INDEX catalog.{migration._INDEX_NAME}")
                    )

                    # The state the bug produced: the generated GeoPackage row
                    # the platform wrote at dataset creation, and the user's
                    # own row that claimed the flag beside it.
                    await conn.execute(
                        sa.text(
                            "INSERT INTO catalog.record_distributions "
                            "(record_id, distribution_type, format, url, "
                            " is_primary, auto_generated) VALUES "
                            "(:rid, 'download', 'gpkg', '/generated.gpkg', "
                            " true, true), "
                            "(:rid, 'download', 'gpkg', "
                            " 'https://example.org/mine.gpkg', true, false), "
                            "(:rid, 'download', 'csv', '/generated.csv', "
                            " false, true)"
                        ),
                        {"rid": record_id},
                    )
                    assert await self._primary_count(conn, record_id) == 2

                    await conn.execute(sa.text(migration._REPAIR_SQL))

                    rows = (
                        await conn.execute(
                            sa.text(
                                "SELECT url, auto_generated FROM "
                                "catalog.record_distributions "
                                "WHERE record_id = :rid AND is_primary"
                            ),
                            {"rid": record_id},
                        )
                    ).fetchall()
                    assert len(rows) == 1, rows
                    # The user-authored row wins — the same precedence the
                    # service layer applies from now on.
                    assert rows[0][0] == "https://example.org/mine.gpkg"
                    assert rows[0][1] is False

                    # Nothing was deleted: a demoted distribution is still a
                    # distribution.
                    total = (
                        await conn.execute(
                            sa.text(
                                "SELECT count(*) FROM "
                                "catalog.record_distributions "
                                "WHERE record_id = :rid"
                            ),
                            {"rid": record_id},
                        )
                    ).scalar_one()
                    assert total == 3

                    # Would raise if the repair had left any record double.
                    await conn.execute(sa.text(migration._CREATE_INDEX_SQL))
                finally:
                    await trans.rollback()
        finally:
            await engine.dispose()

    async def test_the_repair_is_deterministic_across_generated_rows_only(
        self,
    ) -> None:
        """No user row among the primaries: the preference order decides.

        ``record_distributions`` has no timestamps, so "keep the most recent"
        is not available — the rule is user-authored first, then the pair a
        fresh ``generate_distributions`` would have made primary, then ``id``.
        """
        from app.core.config import settings

        migration = _migration_0042()
        engine = create_async_engine(settings.test_database_url)
        try:
            async with engine.connect() as conn:
                trans = await conn.begin()
                try:
                    await conn.execute(sa.text("SET LOCAL lock_timeout = '10s'"))
                    record_id = (
                        await conn.execute(
                            sa.text(
                                "INSERT INTO catalog.records "
                                "(title, visibility, record_status) "
                                "VALUES ('1383 repair generated', 'public', "
                                "'published') RETURNING id"
                            )
                        )
                    ).scalar_one()

                    await conn.execute(
                        sa.text(f"DROP INDEX catalog.{migration._INDEX_NAME}")
                    )
                    await conn.execute(
                        sa.text(
                            "INSERT INTO catalog.record_distributions "
                            "(record_id, distribution_type, format, url, "
                            " is_primary, auto_generated) VALUES "
                            "(:rid, 'download', 'csv', '/generated.csv', "
                            " true, true), "
                            "(:rid, 'download', 'geojson', "
                            " '/generated.geojson', true, true), "
                            "(:rid, 'download', 'gpkg', '/generated.gpkg', "
                            " true, true)"
                        ),
                        {"rid": record_id},
                    )

                    await conn.execute(sa.text(migration._REPAIR_SQL))

                    rows = (
                        await conn.execute(
                            sa.text(
                                "SELECT format FROM catalog.record_distributions "
                                "WHERE record_id = :rid AND is_primary"
                            ),
                            {"rid": record_id},
                        )
                    ).fetchall()
                    assert [r[0] for r in rows] == ["gpkg"]

                    await conn.execute(sa.text(migration._CREATE_INDEX_SQL))
                finally:
                    await trans.rollback()
        finally:
            await engine.dispose()

    @staticmethod
    async def _primary_count(conn, record_id) -> int:
        return (
            await conn.execute(
                sa.text(
                    "SELECT count(*) FROM catalog.record_distributions "
                    "WHERE record_id = :rid AND is_primary"
                ),
                {"rid": record_id},
            )
        ).scalar_one()
