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

fix(#1370) extends the file to the other half of "merges rather than replaces":
whose rows the merge is allowed to see. A row the user authored is no longer a
reason to withhold the platform's own export link for that format, so a record
can carry two rows for one format — see ``TestUserRowsDoNotSuppressGenerated``
and ``TestTwoRowsForOneFormat``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordDistribution,
)
from app.modules.catalog.records.service import (
    _DISTRIBUTION_UNIQUE_CONSTRAINT,
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
    ("download", "fgb"),
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


async def _reload_for_serialization(session: AsyncSession, dataset_id: uuid.UUID):
    """Re-fetch a dataset with everything the DCAT/OGC serializers read.

    They walk record relationships directly, and a lazy load on an async
    session raises rather than emitting SQL.
    """
    result = await session.execute(
        select(Dataset)
        .where(Dataset.id == dataset_id)
        .options(
            selectinload(Dataset.record).selectinload(Record.distributions),
            selectinload(Dataset.record).selectinload(Record.contacts),
            selectinload(Dataset.record).selectinload(Record.keywords),
            selectinload(Dataset.record).selectinload(Record.translations),
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


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

    async def test_a_promote_falls_back_to_csv_when_a_user_row_holds_the_template_url(
        self, test_db_session: AsyncSession
    ) -> None:
        """fix(#1314 review round 1): the record must never end up with none.

        Picking the primary from the modality alone cleared the CSV flag to
        promote a row that was never created. fix(#1370) narrowed the way in —
        a user's own GeoPackage entry at their own url now gets the generated
        row beside it — but left this one: a user row sitting at the exact url
        the template would insert makes the insert a no-op, so there is again
        no generated GeoPackage row for the preferred pair to name.
        """
        dataset = await _tabular_dataset(test_db_session)
        await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="gpkg",
            url=f"/datasets/{dataset.id}/export?format=gpkg",
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


class TestTheConstraintTheInsertTargets:
    """``generate_distributions`` names ``uq_record_distribution`` by string.

    A conflict clause aimed at a constraint that has been renamed or narrowed
    is not a compile error, so the coupling is pinned here: the name and the
    exact four columns, from the model the migration built.
    """

    def test_the_unique_constraint_is_the_four_column_one(self) -> None:
        from sqlalchemy import UniqueConstraint

        constraints = {
            c.name: c
            for c in RecordDistribution.__table__.constraints
            if isinstance(c, UniqueConstraint)
        }
        assert _DISTRIBUTION_UNIQUE_CONSTRAINT in constraints
        assert [
            c.name for c in constraints[_DISTRIBUTION_UNIQUE_CONSTRAINT].columns
        ] == [
            "record_id",
            "distribution_type",
            "format",
            "url",
        ]


class TestUserRowsDoNotSuppressGenerated:
    """fix(#1370): the existence probe reads only the rows this module owns.

    The probe used to match on ``(distribution_type, format)`` across every
    row, so one ``POST /records/{id}/distributions/`` for ``download``/``gpkg``
    retired the built-in ``/datasets/{id}/export?format=gpkg`` row for the life
    of the record. Nothing recreated it: not a later ``generate_distributions``
    call, not the ``reconcile_distributions`` promote. The export endpoint went
    on working while the catalog record, the DCAT feeds and the STAC assets
    stopped naming it.
    """

    async def _rows(
        self, session: AsyncSession, record_id: uuid.UUID, dist_type: str, fmt: str
    ) -> list[RecordDistribution]:
        return list(
            (
                await session.execute(
                    select(RecordDistribution).where(
                        RecordDistribution.record_id == record_id,
                        RecordDistribution.distribution_type == dist_type,
                        RecordDistribution.format == fmt,
                    )
                )
            ).scalars()
        )

    async def test_generate_still_creates_the_builtin_export_beside_a_user_row(
        self, test_db_session: AsyncSession
    ) -> None:
        """The issue's headline case, at the call site the create path uses."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=admin_id)
        await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="gpkg",
            url="https://example.org/mine.gpkg",
            title="My own extract",
        )
        await test_db_session.commit()

        await generate_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()

        rows = await self._rows(test_db_session, dataset.record_id, "download", "gpkg")
        assert {(row.auto_generated, row.url) for row in rows} == {
            (False, "https://example.org/mine.gpkg"),
            (True, f"/datasets/{dataset.id}/export?format=gpkg"),
        }

    async def test_a_promote_creates_the_builtin_export_beside_a_user_row(
        self, test_db_session: AsyncSession
    ) -> None:
        """The path #1369 added, which inherited the same probe."""
        dataset = await _tabular_dataset(test_db_session)
        await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="download",
            format="gpkg",
            url="https://example.org/mine.gpkg",
        )
        await test_db_session.commit()

        created, _removed = await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()

        assert ("download", "gpkg") in {
            (c.distribution_type, c.format) for c in created
        }
        rows = await self._rows(test_db_session, dataset.record_id, "download", "gpkg")
        assert len(rows) == 2
        # The generated row is the one that can be reconciled, so it takes the
        # primary flag back from CSV — the promote no longer has to fall back.
        generated = [row for row in rows if row.auto_generated]
        assert [row.is_primary for row in generated] == [True]
        assert await _pairs(test_db_session, dataset.record_id) == _SPATIAL_PAIRS


class TestATemplateUrlCollisionDoesNotRaise:
    """The reason a changed probe alone was not safe (#1370).

    ``uq_record_distribution`` is ``(record_id, distribution_type, format,
    url)``. A user row at ``/datasets/{id}/export?format=gpkg`` — a guessable
    thing to type — no longer hides the pair, so the generated insert lands on
    the constraint. It resolves in the statement rather than raising, because
    the reconcile caller runs inside the write transaction of a
    registered-PostGIS refresh or a reupload swap, where an IntegrityError
    aborts every write the job has already made.
    """

    async def _user_row_at_the_template_url(
        self, session: AsyncSession, dataset
    ) -> None:
        await create_distribution(
            session,
            dataset.record_id,
            distribution_type="download",
            format="gpkg",
            url=f"/datasets/{dataset.id}/export?format=gpkg",
        )
        await session.commit()

    async def test_generate_does_not_raise_and_writes_no_duplicate(
        self, test_db_session: AsyncSession
    ) -> None:
        """Also the create path: ``create_dataset_from_ingest`` reaches the
        same statement through this function (``service_create.py``), on a
        Record it has just created — so the collision is unreachable there and
        the guarantee is this one."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=admin_id)
        await self._user_row_at_the_template_url(test_db_session, dataset)

        created = await generate_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()

        assert ("download", "gpkg") not in {
            (row.distribution_type, row.format) for row in created
        }
        rows = (
            await test_db_session.execute(
                select(RecordDistribution).where(
                    RecordDistribution.record_id == dataset.record_id,
                    RecordDistribution.distribution_type == "download",
                    RecordDistribution.format == "gpkg",
                )
            )
        ).scalars()
        assert [row.auto_generated for row in rows] == [False]

    async def test_reconcile_does_not_raise_and_leaves_the_job_transaction_usable(
        self, test_db_session: AsyncSession
    ) -> None:
        dataset = await _tabular_dataset(test_db_session)
        await self._user_row_at_the_template_url(test_db_session, dataset)

        await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        # The transaction the caller's job is holding is still writable: an
        # IntegrityError above would have poisoned it, and this write is what
        # says so.
        await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="api",
            format="json",
            url="https://example.org/after",
        )
        await test_db_session.commit()

        assert await _pairs(test_db_session, dataset.record_id) == _SPATIAL_PAIRS | {
            ("api", "json")
        }

    async def test_the_fallback_primary_lands_on_a_row_the_insert_returned(
        self, test_db_session: AsyncSession
    ) -> None:
        """The normalization has to be able to WRITE to a just-inserted row.

        Every other promote flips a survivor's flag or accepts the one the
        template already inserted as primary, so nothing else exercises this:
        the fallback is only reached when the preferred pair was skipped, and
        the CSV that takes it is a row this call created. Those rows come back
        from ``INSERT ... RETURNING`` rather than from ``session.add``, and one
        that was not session-persistent would take ``is_primary = True``
        silently and never emit the UPDATE.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=admin_id)
        await self._user_row_at_the_template_url(test_db_session, dataset)

        created, _removed = await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()

        # CSV was created with is_primary=False (the template marks GeoPackage
        # primary), and GeoPackage is the row the conflict skipped.
        assert ("download", "csv") in {(c.distribution_type, c.format) for c in created}
        primaries = (
            await test_db_session.execute(
                select(
                    RecordDistribution.distribution_type, RecordDistribution.format
                ).where(
                    RecordDistribution.record_id == dataset.record_id,
                    RecordDistribution.auto_generated.is_(True),
                    RecordDistribution.is_primary.is_(True),
                )
            )
        ).all()
        assert [(row[0], row[1]) for row in primaries] == [("download", "csv")]

    async def test_repeated_reconciles_stay_idempotent_over_the_collision(
        self, test_db_session: AsyncSession
    ) -> None:
        """The skipped insert is retried every call; it must stay a no-op."""
        dataset = await _tabular_dataset(test_db_session)
        await self._user_row_at_the_template_url(test_db_session, dataset)

        for _ in range(3):
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
                select(RecordDistribution).where(
                    RecordDistribution.record_id == dataset.record_id,
                    RecordDistribution.distribution_type == "download",
                    RecordDistribution.format == "gpkg",
                )
            )
        ).scalars()
        assert [row.auto_generated for row in rows] == [False]


class TestTwoRowsForOneFormat:
    """What the state #1370 creates looks like to the standards feeds.

    Two distributions advertising one format is legal DCAT — ``dcat:
    distribution`` is a set of Distribution nodes, and these two differ by
    ``accessURL``. STAC is the one worth checking rather than assuming, since
    its assets ARE a keyed object; the check below is what says the keys do not
    come from ``record_distributions`` at all.
    """

    async def _record_with_two_gpkg_rows(self, session: AsyncSession):
        admin_id = await get_user_id(session, "admin")
        dataset = await create_dataset(session, created_by=admin_id)
        await create_distribution(
            session,
            dataset.record_id,
            distribution_type="download",
            format="gpkg",
            url="https://example.org/mine.gpkg",
            title="My own extract",
        )
        await generate_distributions(
            session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await session.commit()
        return await _reload_for_serialization(session, dataset.id)

    async def test_exactly_one_generated_row_is_primary(
        self, test_db_session: AsyncSession
    ) -> None:
        """The user's row defaults to non-primary, so the record advertises one.

        ``is_primary`` normalization spans the generated rows; a user who
        explicitly flags their own row primary keeps that flag, which is #1383
        and predates this change.
        """
        dataset = await self._record_with_two_gpkg_rows(test_db_session)
        primaries = [d for d in dataset.record.distributions if d.is_primary]
        assert [(d.distribution_type, d.format) for d in primaries] == [
            ("download", "gpkg")
        ]
        assert primaries[0].auto_generated is True

    async def test_dcat_carries_both_rows(self, test_db_session: AsyncSession) -> None:
        from app.standards.dcat.service import record_to_dcat

        dataset = await self._record_with_two_gpkg_rows(test_db_session)
        doc = record_to_dcat(
            dataset, "https://example.test", app_base_url="https://app.example.test"
        )

        gpkg = [
            d for d in doc["dcat:distribution"] if d.get("dcterms:format") == "gpkg"
        ]
        assert {d["dcat:accessURL"] for d in gpkg} == {
            "https://example.org/mine.gpkg",
            f"https://example.test/datasets/{dataset.id}/export?format=gpkg",
        }

    async def test_the_ogc_record_and_its_stac_item_drop_neither_row(
        self, test_db_session: AsyncSession
    ) -> None:
        """STAC asset keys are derived from the dataset, not from these rows.

        ``build_assets`` builds ``download_<fmt>`` from the dataset id and the
        modality; ``ogc_record_to_stac_item`` copies that dict through
        untouched and never reads ``properties.distributions``. So two rows for
        one format cannot collide on an asset key — there is no key to collide
        on — and neither row is dropped: both survive in the OGC Record
        properties, which is the representation that carries them.
        """
        from app.modules.catalog.search.service import dataset_to_ogc_record
        from app.standards.stac.serializer import ogc_record_to_stac_item

        dataset = await self._record_with_two_gpkg_rows(test_db_session)
        ogc_record = dataset_to_ogc_record(dataset, "https://example.test")

        gpkg = [
            d
            for d in ogc_record["properties"]["distributions"]
            if d["format"] == "gpkg"
        ]
        assert {d["url"] for d in gpkg} == {
            "https://example.org/mine.gpkg",
            f"https://example.test/datasets/{dataset.id}/export?format=gpkg",
        }

        item = ogc_record_to_stac_item(
            ogc_record, stac_api_url="https://example.test/stac"
        )
        assert item["assets"]["download_gpkg"]["href"] == (
            f"https://example.test/datasets/{dataset.id}/export?format=gpkg"
        )
        assert not any(
            key for key in item["assets"] if "mine.gpkg" in str(item["assets"][key])
        )


class TestTheStaleProtocolRepair:
    """fix(#1463, codex round 2): the pair-existence skip can strand a bad row.

    Migration 0048 relabels the auto-generated vector-tile rows from
    ``OGC:WMTS`` to ``XYZ``. It runs once, and the scripted upgrade path
    applies migrations while the previous app containers are still serving, so a
    dataset created in that window is written by the OLD template AFTER the
    UPDATE has committed. Alembic will not repeat the revision, and the skip
    in ``generate_distributions`` means the template never rewrites a pair it
    already owns, so without the repair below the row stays wrong for good.

    fix(#1463, codex round 4): what this does NOT do. Both refresh callers gate
    ``reconcile_distributions`` on a modality flip, so an ordinary refresh of an
    unchanged dataset never arrives here and the repair is a partial mitigation
    rather than a closer. The reach is a dataset that gains or loses geometry,
    plus any future caller that regenerates. Removing the window itself is
    #1467. These tests pin the repair's behaviour where it does run; they are
    not evidence that every stranded row gets fixed.
    """

    async def _stale(self, session: AsyncSession, record_id: uuid.UUID) -> None:
        """Put a record's generated vector-tile row back to the old label."""
        row = await _row(session, record_id, "vector_tiles", "pbf")
        assert row is not None
        row.protocol = "OGC:WMTS"
        await session.commit()

    async def test_generate_repairs_a_surviving_stale_row(
        self, test_db_session: AsyncSession
    ) -> None:
        dataset = await _spatial_dataset(test_db_session)
        await self._stale(test_db_session, dataset.record_id)

        await generate_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()

        row = await _row(test_db_session, dataset.record_id, "vector_tiles", "pbf")
        assert row is not None
        await test_db_session.refresh(row)
        assert row.protocol == "XYZ"

    async def test_reconcile_repairs_it_too(
        self, test_db_session: AsyncSession
    ) -> None:
        """The modality-flip path, which is the one that reaches this in prod."""
        dataset = await _spatial_dataset(test_db_session)
        await self._stale(test_db_session, dataset.record_id)

        await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()

        row = await _row(test_db_session, dataset.record_id, "vector_tiles", "pbf")
        assert row is not None
        await test_db_session.refresh(row)
        assert row.protocol == "XYZ"

    async def test_a_user_authored_row_keeps_its_own_protocol(
        self, test_db_session: AsyncSession
    ) -> None:
        """Same rule as the migration's WHERE: user rows are not ours to edit.

        Somebody pointing their own distribution at a real WMTS service is
        correct, and the repair must not reach it just because the type and
        the value match.
        """
        dataset = await _spatial_dataset(test_db_session)
        await self._stale(test_db_session, dataset.record_id)
        mine = await create_distribution(
            test_db_session,
            dataset.record_id,
            distribution_type="vector_tiles",
            format="pbf",
            url="https://example.org/wmts/1.0.0/WMTSCapabilities.xml",
            title="My own WMTS",
            protocol="OGC:WMTS",
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

        theirs = await test_db_session.get(RecordDistribution, mine.id)
        assert theirs is not None
        await test_db_session.refresh(theirs)
        assert theirs.protocol == "OGC:WMTS"

    async def test_a_healthy_row_is_left_alone(
        self, test_db_session: AsyncSession
    ) -> None:
        """The repair matches the stale value, not the pair.

        An auto-generated row an operator already corrected by hand to
        something else is not stale, and rewriting it would be the same
        overreach the migration's downgrade was dropped for.
        """
        dataset = await _spatial_dataset(test_db_session)
        row = await _row(test_db_session, dataset.record_id, "vector_tiles", "pbf")
        assert row is not None
        row.protocol = "WWW:LINK"
        await test_db_session.commit()

        await reconcile_distributions(
            test_db_session,
            dataset.id,
            dataset.record_id,
            dataset.table_name,
            geometry_type="POLYGON",
        )
        await test_db_session.commit()

        row = await _row(test_db_session, dataset.record_id, "vector_tiles", "pbf")
        assert row is not None
        await test_db_session.refresh(row)
        assert row.protocol == "WWW:LINK"
