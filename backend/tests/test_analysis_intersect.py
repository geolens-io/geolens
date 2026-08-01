"""Intersect/overlay: new geometry from two layers (#956).

One test per acceptance criterion on the issue.

The fixture throughout is a 3x1 bar laid across three side-by-side unit
squares. It is the shape that separates an overlay from a clip: a clip returns
ONE feature (the bar trimmed to the union of the zones), an overlay returns
THREE, each carrying its own zone's attributes.

    +---+---+---+
    | A | B | C |   mask: three 1x1 zones
    +---+---+---+
    #############   source: one 3x1 bar crossing all three

Requirements:
  - Docker database must be running (docker compose up db)
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.analysis_sql import (
    INTERSECT_SOURCE_GID_COLUMN,
    MAX_SOURCE_FEATURES,
)
from app.processing.analysis.tasks import _materialize

from tests.factories import get_user_id
from tests.test_analysis_materialize import _create_job
from tests.test_analysis_spatial_join import _create_layer

BAR_WKT = "POLYGON((0 0, 3 0, 3 1, 0 1, 0 0))"


def _preview_url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/analysis/preview/"


def _materialize_url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/analysis/materialize/"


def _zone_values(count: int = 3) -> str:
    """``count`` side-by-side unit squares named A, B, C, ..."""
    return ",".join(
        f"('{chr(65 + i)}',"
        f" ST_MakeEnvelope({i}, 0, {i + 1}, 1, 4326),"
        f" ST_MakeEnvelope({i}, 0, {i + 1}, 1, 4326))"
        for i in range(count)
    )


async def _create_zones(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    count: int = 3,
    visibility: str = "public",
    name_column: str = "zone",
):
    zones = await _create_layer(
        session,
        created_by=created_by,
        column_type="Geometry",
        geometry_type="POLYGON",
        visibility=visibility,
        feature_count=count,
        values_sql=_zone_values(count),
        column_info=[{"name": name_column, "type": "text"}],
    )
    # The shared helper always creates a physical "name" column, and the worker
    # reads LIVE columns rather than column_info — so without this both layers
    # would carry "name" and the collision guard would (correctly) reject every
    # overlay. Rename to whatever this fixture claims in column_info.
    if name_column != "name":
        await session.execute(
            text(
                f"ALTER TABLE data.{zones.table_name} "  # noqa: S608
                f"RENAME COLUMN name TO {name_column}"
            )
        )
        await session.commit()
    return zones


async def _create_bar(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
    wkt: str = BAR_WKT,
):
    bar = await _create_layer(
        session,
        created_by=created_by,
        column_type="Geometry",
        geometry_type="POLYGON",
        visibility=visibility,
        values_sql=(
            f"('bar', ST_GeomFromText('{wkt}', 4326), ST_GeomFromText('{wkt}', 4326))"
        ),
        column_info=[{"name": "parcel", "type": "text"}],
    )
    await session.execute(
        text(
            f"ALTER TABLE data.{bar.table_name} "  # noqa: S608
            "RENAME COLUMN name TO parcel"
        )
    )
    await session.commit()
    return bar


class TestPairwiseRows:
    async def test_one_source_over_three_zones_yields_three_rows(
        self,
        test_db_session: AsyncSession,
    ):
        """Criterion 3, the one that distinguishes this from clip.

        Clip aggregates every mask piece back to one geometry per source row.
        An overlay must not: three zones, three rows, each carrying ITS zone's
        attribute and only its own third of the bar.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        zones = await _create_zones(test_db_session, created_by=admin_id)
        bar = await _create_bar(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(bar.id),
            user_id=str(admin_id),
            operation="intersect",
            title=f"Overlay {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(zones.id),
        )
        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        out = await test_db_session.get(Dataset, job.dataset_id)
        assert out is not None
        assert out.feature_count == 3

        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT gid, source_gid, parcel, zone, ST_Area(geom_4326)"  # noqa: S608
                    f" FROM data.{out.table_name} ORDER BY zone"
                )
            )
        ).all()
        assert [r[3] for r in rows] == ["A", "B", "C"]
        # Every row traces back to the one source feature...
        assert {r[1] for r in rows} == {1}
        assert {r[2] for r in rows} == {"bar"}
        # ...and each carries a third of the bar, not the whole thing.
        for row in rows:
            assert row[4] == 1.0

    async def test_the_output_gid_is_generated_not_the_source_gid(
        self,
        test_db_session: AsyncSession,
    ):
        """Criterion 2: three rows sharing one source gid would fail the
        unconditional ADD PRIMARY KEY (gid) outright — the job dies, it is not
        a subtle data-quality issue. Pinned at materialize, where the ALTER
        actually runs, not just in a preview."""
        admin_id = await get_user_id(test_db_session, "admin")
        zones = await _create_zones(test_db_session, created_by=admin_id)
        bar = await _create_bar(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(bar.id),
            user_id=str(admin_id),
            operation="intersect",
            title=f"Keyed {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(zones.id),
        )
        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        out = await test_db_session.get(Dataset, job.dataset_id)
        gids = (
            (
                await test_db_session.execute(
                    text(f"SELECT gid FROM data.{out.table_name} ORDER BY gid")  # noqa: S608
                )
            )
            .scalars()
            .all()
        )
        assert list(gids) == [1, 2, 3], "generated key, contiguous, no duplicates"

        pk_count = (
            await test_db_session.execute(
                text(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE conrelid = ('data.' || :t)::regclass AND contype = 'p'"
                ).bindparams(t=out.table_name)
            )
        ).scalar_one()
        assert pk_count == 1

    async def test_a_mask_polygon_that_subdivides_still_yields_one_row(
        self,
        test_db_session: AsyncSession,
    ):
        """The trap inside the trap.

        The mask is subdivided into <=256-vertex pieces for the performance
        reason render_clip_layer_join documents. Grouping by piece instead of
        by mask FEATURE would silently multiply the output by however many
        pieces a polygon happened to split into. This zone is a single ~2000-
        vertex circle, so it definitely subdivides, and it must still produce
        exactly one output row.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        big = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            values_sql=(
                "('circle',"
                " ST_Buffer(ST_SetSRID(ST_MakePoint(1.5, 0.5), 4326), 2,"
                " 'quad_segs=512'),"
                " ST_Buffer(ST_SetSRID(ST_MakePoint(1.5, 0.5), 4326), 2,"
                " 'quad_segs=512'))"
            ),
            column_info=[{"name": "zone", "type": "text"}],
        )
        vertices = (
            await test_db_session.execute(
                text(f"SELECT ST_NPoints(geom_4326) FROM data.{big.table_name}")  # noqa: S608
            )
        ).scalar_one()
        assert vertices > 256, "fixture must exceed the subdivide threshold"

        bar = await _create_bar(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        await _materialize(
            job_id=str(job.id),
            dataset_id=str(bar.id),
            user_id=str(admin_id),
            operation="intersect",
            title=f"Subdivided {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(big.id),
        )
        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        out = await test_db_session.get(Dataset, job.dataset_id)
        assert out.feature_count == 1, "one mask FEATURE, one row, however it split"


class TestPreview:
    async def test_preview_rows_carry_distinct_generated_gids(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 4: preview and materialize must agree on what a row is.

        Selecting the source gid here would show three features all claiming
        gid 1 — nothing crashes, and the map silently lies about identity.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        zones = await _create_zones(test_db_session, created_by=admin_id)
        bar = await _create_bar(test_db_session, created_by=admin_id)

        resp = await client.post(
            _preview_url(bar.id),
            json={"operation": "intersect", "mask_dataset_id": str(zones.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        features = body["geojson"]["features"]
        assert [f["properties"]["gid"] for f in features] == [1, 2, 3]
        # ...and each still points back at the source feature it came from.
        assert {f["properties"][INTERSECT_SOURCE_GID_COLUMN] for f in features} == {1}
        assert body["feature_count"] == 3
        # A row-multiplying operation cannot report a source total.
        assert body["source_feature_count"] is None
        # The exact pair total rides the same statement as a window column.
        assert body["match_count"] == 3

    async def test_match_count_is_zero_not_null_when_nothing_overlaps(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#1097 review): an empty result is an ANSWER, not a failure.

        match_count is null in the contract when the total could not be
        computed — a timed-out count. intersect's total rides its preview
        statement as a window column, so with no overlapping pairs there is no
        row to read it off, and it defaulted to null. That made "these two
        layers do not overlap" (an ordinary result) indistinguishable from
        "the server gave up", and the panel renders those differently.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        zones = await _create_zones(test_db_session, created_by=admin_id)
        # Same shape as the overlapping fixture, parked far away: the query
        # runs and returns cleanly, it just finds nothing.
        far = await _create_bar(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((100 40, 101 40, 101 41, 100 41, 100 40))",
        )

        resp = await client.post(
            _preview_url(far.id),
            json={"operation": "intersect", "mask_dataset_id": str(zones.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["geojson"]["features"] == []
        assert body["feature_count"] == 0
        assert body["match_count"] == 0, "zero pairs is a computed answer"
        assert body["match_count"] is not None

    async def test_match_count_is_exact_beyond_the_preview_cap(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The window is computed before the row cap, so the total is the real
        one even when the feature list is truncated."""
        from app.modules.catalog.datasets.domain.service_analysis import (
            PREVIEW_FEATURE_CAP,
        )

        admin_id = await get_user_id(test_db_session, "admin")
        # 600 zones in a row; the bar crosses the first three, so widen it.
        zones = await _create_zones(
            test_db_session, created_by=admin_id, count=PREVIEW_FEATURE_CAP + 100
        )
        wide = "POLYGON((0 0, 600 0, 600 1, 0 1, 0 0))"
        src = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            values_sql=(
                f"('wide', ST_GeomFromText('{wide}', 4326),"
                f" ST_GeomFromText('{wide}', 4326))"
            ),
            column_info=[{"name": "parcel", "type": "text"}],
        )
        await test_db_session.execute(
            text(
                f"ALTER TABLE data.{src.table_name} "  # noqa: S608
                "RENAME COLUMN name TO parcel"
            )
        )
        await test_db_session.commit()

        resp = await client.post(
            _preview_url(src.id),
            json={"operation": "intersect", "mask_dataset_id": str(zones.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["truncated"] is True
        assert body["feature_count"] == PREVIEW_FEATURE_CAP
        assert body["match_count"] == PREVIEW_FEATURE_CAP + 100


class TestColumnCollisions:
    async def test_a_column_in_both_layers_is_rejected_at_enqueue(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 5: an overlay carries columns from BOTH inputs, so a
        same-named column is likely rather than exotic. The CTAS would fail it
        with an opaque "column specified more than once" after the queue wait;
        name it at enqueue instead."""
        admin_id = await get_user_id(test_db_session, "admin")
        # Both layers call their text column "name".
        zones = await _create_zones(
            test_db_session, created_by=admin_id, name_column="name"
        )
        bar = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            values_sql=(
                f"('bar', ST_GeomFromText('{BAR_WKT}', 4326),"
                f" ST_GeomFromText('{BAR_WKT}', 4326))"
            ),
            column_info=[{"name": "name", "type": "text"}],
        )

        resp = await client.post(
            _materialize_url(bar.id),
            json={
                "operation": "intersect",
                "mask_dataset_id": str(zones.id),
                "title": "Nope",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "name" in resp.text

    async def test_an_ungroupable_overlay_column_is_rejected_at_enqueue(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#1097 review): json and xml have no equality operator.

        render_intersect_pairs groups by the two gids plus every carried
        OVERLAY column — the source's columns ride the functional dependency on
        _src.gid, but _mask_pieces is a CTE with no key, so its columns must be
        named in the GROUP BY. Grouping on json fails the CTAS with SQLSTATE
        42883, and it fails only there: the preview carries gid and source_gid
        alone, so it succeeds first and the operation dies after the queue wait
        quoting a generated alias the user never wrote.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        zones = await _create_zones(test_db_session, created_by=admin_id)
        bar = await _create_bar(test_db_session, created_by=admin_id)
        # Physical column AND catalog snapshot: the guard reads column_info,
        # and the worker that would hit 42883 reads the live table.
        await test_db_session.execute(
            text(f"ALTER TABLE data.{zones.table_name} ADD COLUMN props json")  # noqa: S608
        )
        zones.column_info = [
            {"name": "zone", "type": "text"},
            {"name": "props", "type": "json"},
        ]
        await test_db_session.commit()

        resp = await client.post(
            _materialize_url(bar.id),
            json={
                "operation": "intersect",
                "mask_dataset_id": str(zones.id),
                "title": "Nope",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        # Names the column and its type: "cannot be grouped" with no referent
        # sends the operator looking through both layers by hand.
        assert "props" in resp.text
        assert "json" in resp.text

    def test_an_ungroupable_SOURCE_column_is_still_allowed(self):
        """The guard is deliberately one-sided, so pin the side it lets through.

        A json column on the SOURCE never reaches the GROUP BY: _src.gid is a
        real table's primary key, so PostgreSQL licenses every other _src
        column by functional dependency. Rejecting both sides would refuse
        overlays that work.

        Against the validator rather than the endpoint: enqueueing needs the
        task queue, so an HTTP assertion here would be reading a 503 from the
        broker as evidence about column rules.
        """
        from types import SimpleNamespace

        from app.modules.catalog.datasets.api.router_analysis import (
            _validate_intersect_columns,
        )

        source = SimpleNamespace(
            column_info=[
                {"name": "parcel", "type": "text"},
                {"name": "props", "type": "json"},
            ]
        )
        overlay = SimpleNamespace(column_info=[{"name": "zone", "type": "text"}])
        _validate_intersect_columns(source, overlay)

        # And the mirror image is refused, which is what makes the pass above
        # a statement about WHICH side rather than about json in general.
        with pytest.raises(HTTPException) as excinfo:
            _validate_intersect_columns(overlay, source)
        assert "props" in str(excinfo.value.detail)

    async def test_a_source_column_named_source_gid_is_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The generated column has the same problem as dissolve's
        source_count."""
        admin_id = await get_user_id(test_db_session, "admin")
        zones = await _create_zones(test_db_session, created_by=admin_id)
        bar = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            extra_columns="source_gid INTEGER,",
            values_sql=(
                f"('bar', 7, ST_GeomFromText('{BAR_WKT}', 4326),"
                f" ST_GeomFromText('{BAR_WKT}', 4326))"
            ),
            column_info=[
                {"name": "parcel", "type": "text"},
                {"name": "source_gid", "type": "integer"},
            ],
        )

        resp = await client.post(
            _materialize_url(bar.id),
            json={
                "operation": "intersect",
                "mask_dataset_id": str(zones.id),
                "title": "Nope",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert INTERSECT_SOURCE_GID_COLUMN in resp.text


class TestAccessControl:
    async def test_an_overlay_layer_the_caller_cannot_see_is_a_404(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 8: Rule 1 applies to BOTH datasets, on preview and
        materialize alike."""
        admin_id = await get_user_id(test_db_session, "admin")
        bar = await _create_bar(test_db_session, created_by=admin_id)
        private_zones = await _create_zones(
            test_db_session, created_by=admin_id, visibility="private"
        )

        for url in (_preview_url(bar.id), _materialize_url(bar.id)):
            resp = await client.post(
                url,
                json={
                    "operation": "intersect",
                    "mask_dataset_id": str(private_zones.id),
                    "title": "Nope",
                },
                headers=editor_auth_header,
            )
            assert resp.status_code == 404, f"{url}: {resp.text}"


class TestEnqueueValidation:
    async def test_oversized_source_rejected_at_enqueue(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 6's first half. The router reads MAX_SOURCE_FEATURES with
        .get(), so a missing key would leave the row-multiplying operation with
        NO ceiling — the entry existing is half the assertion."""
        assert "intersect" in MAX_SOURCE_FEATURES
        admin_id = await get_user_id(test_db_session, "admin")
        zones = await _create_zones(test_db_session, created_by=admin_id)
        bar = await _create_bar(test_db_session, created_by=admin_id)
        bar.feature_count = MAX_SOURCE_FEATURES["intersect"] + 1
        await test_db_session.commit()

        resp = await client.post(
            _materialize_url(bar.id),
            json={
                "operation": "intersect",
                "mask_dataset_id": str(zones.id),
                "title": "Too big",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "too large" in resp.text

    async def test_an_overlay_requires_a_layer(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Layer only: a drawn polygon carries no attributes to overlay with,
        which would make it an expensive clip. `mask` is not an intersect
        param, so a drawn one is dropped and the request then fails for want of
        the layer."""
        admin_id = await get_user_id(test_db_session, "admin")
        bar = await _create_bar(test_db_session, created_by=admin_id)

        for body in (
            {"operation": "intersect"},
            {
                "operation": "intersect",
                "mask": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                },
            },
        ):
            resp = await client.post(
                _preview_url(bar.id), json=body, headers=admin_auth_header
            )
            assert resp.status_code == 422, resp.text


class TestOutputSize:
    async def test_row_amplification_trips_the_output_ceiling(
        self,
        test_db_session: AsyncSession,
    ):
        """Criterion 7: the existing output-size tests grow GEOMETRY. This one
        grows ROW COUNT instead, which is the axis only this operation moves.

        One small source over 200 zones is 200 output rows from 1 input row —
        the shape no MAX_SOURCE_FEATURES value can bound, and therefore the
        shape _enforce_output_size has to be the thing that catches.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        zones = await _create_zones(test_db_session, created_by=admin_id, count=200)
        wide = "POLYGON((0 0, 200 0, 200 1, 0 1, 0 0))"
        src = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            values_sql=(
                f"('wide', ST_GeomFromText('{wide}', 4326),"
                f" ST_GeomFromText('{wide}', 4326))"
            ),
            column_info=[{"name": "parcel", "type": "text"}],
        )
        await test_db_session.execute(
            text(
                f"ALTER TABLE data.{src.table_name} "  # noqa: S608
                "RENAME COLUMN name TO parcel"
            )
        )
        await test_db_session.commit()
        job = await _create_job(test_db_session, admin_id)

        with patch("app.processing.analysis.tasks.MAX_OUTPUT_BYTES", 1):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(src.id),
                user_id=str(admin_id),
                operation="intersect",
                title=f"Too big {uuid.uuid4().hex[:6]}",
                mask_dataset_id=str(zones.id),
            )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.dataset_id is None
