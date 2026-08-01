"""Spatial join: point-in-polygon count and attribute transfer (#953).

One test per acceptance criterion on the issue, plus the two enqueue-time
validations that keep a bad request from becoming a job that fails minutes
later with a database error.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.api import router_analysis
from app.modules.catalog.datasets.domain.service_analysis import PREVIEW_FEATURE_CAP
from app.platform.analysis_sql import MAX_SOURCE_FEATURES
from app.processing.analysis.tasks import _materialize

from tests.factories import create_dataset, get_user_id
from tests.test_analysis_materialize import _create_job


def _preview_url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/analysis/preview/"


def _materialize_url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/analysis/materialize/"


async def _create_layer(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    values_sql: str,
    column_type: str,
    geometry_type: str,
    extra_columns: str = "",
    column_info: list[dict] | None = None,
    visibility: str = "public",
    feature_count: int = 1,
):
    """Create a dataset whose table is populated by a literal VALUES clause.

    ``values_sql`` is inserted verbatim after ``VALUES`` and must supply
    ``(name, geom, geom_4326)`` plus whatever ``extra_columns`` declares.
    """
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  name TEXT,"
            f"  {extra_columns}"
            f"  geom geometry({column_type}, 4326),"
            f"  geom_4326 geometry({column_type}, 4326)"
            f")"
        )
    )
    # Column NAMES from the declarations: the first token of each
    # comma-separated entry. Stripping known type keywords instead broke the
    # moment a two-word type appeared (DOUBLE PRECISION).
    extra_names = [d.strip().split()[0] for d in extra_columns.split(",") if d.strip()]
    cols = "".join(f"{n}, " for n in ["name", *extra_names])
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} ({cols} geom, geom_4326) "  # noqa: S608
            f"VALUES {values_sql}"
        )
    )
    await session.commit()
    return await create_dataset(
        session,
        created_by=created_by,
        table_name=table_name,
        geometry_type=geometry_type,
        feature_count=feature_count,
        visibility=visibility,
        column_info=column_info or [{"name": "name", "type": "text"}],
    )


async def _create_two_overlapping_polygons(
    session: AsyncSession, *, created_by: uuid.UUID, visibility: str = "public"
):
    """Two 1x1 polygons overlapping in x=[0.5, 1], plus a NULL-geometry row.

    A point at x=0.75 falls inside BOTH, which is the duplicate-row case the
    tie-break exists for. The NULL row must never inflate a count.
    """
    return await _create_layer(
        session,
        created_by=created_by,
        column_type="Geometry",
        geometry_type="POLYGON",
        extra_columns="pop INTEGER,",
        values_sql=(
            "('poly_a', 100, ST_MakeEnvelope(0,0,1,1,4326),"
            " ST_MakeEnvelope(0,0,1,1,4326)),"
            "('poly_b', 200, ST_MakeEnvelope(0.5,0,1.5,1,4326),"
            " ST_MakeEnvelope(0.5,0,1.5,1,4326)),"
            "('nullgeom', 999, NULL, NULL)"
        ),
        column_info=[
            {"name": "name", "type": "text"},
            {"name": "pop", "type": "integer"},
        ],
        visibility=visibility,
        feature_count=3,
    )


async def _create_probe_points(
    session: AsyncSession, *, created_by: uuid.UUID, visibility: str = "public"
):
    """Three points plus a NULL-geometry row.

    ``in_both`` sits in the overlap, ``in_a_only`` in one polygon, ``outside``
    in neither — so one fixture covers the tie-break, the ordinary match, and
    the no-match row that must survive as 1:1 output.
    """
    return await _create_layer(
        session,
        created_by=created_by,
        column_type="Point",
        geometry_type="POINT",
        values_sql=(
            "('in_both', ST_SetSRID(ST_MakePoint(0.75,0.5),4326),"
            " ST_SetSRID(ST_MakePoint(0.75,0.5),4326)),"
            "('in_a_only', ST_SetSRID(ST_MakePoint(0.25,0.5),4326),"
            " ST_SetSRID(ST_MakePoint(0.25,0.5),4326)),"
            "('outside', ST_SetSRID(ST_MakePoint(50,50),4326),"
            " ST_SetSRID(ST_MakePoint(50,50),4326)),"
            "('nullgeom', NULL, NULL)"
        ),
        visibility=visibility,
        feature_count=4,
    )


class TestSpatialJoinPreview:
    async def test_overlap_yields_one_row_under_the_tie_break(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 2, preview half: a point inside two overlapping polygons
        produces exactly ONE feature, counting both, carrying the lowest-gid
        polygon's attributes."""
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )

        resp = await client.post(
            _preview_url(points.id),
            json={
                "operation": "spatial_join",
                "join_dataset_id": str(polys.id),
                "join_fields": ["name", "pop"],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        features = resp.json()["geojson"]["features"]

        by_gid = {f["properties"]["gid"]: f["properties"] for f in features}
        # The NULL-geometry source row is dropped; the other three survive.
        assert len(features) == 3
        # One row, both polygons counted, poly_a (lower gid) wins the tie.
        assert by_gid[1]["join_count"] == 2
        assert by_gid[1]["join_name"] == "poly_a"
        assert by_gid[1]["join_pop"] == 100
        assert by_gid[2]["join_count"] == 1
        # The unmatched point KEEPS its row: the operation is 1:1.
        assert by_gid[3]["join_count"] == 0
        assert by_gid[3]["join_name"] is None

    async def test_null_geometries_neither_crash_nor_inflate_counts(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 3: both fixtures carry a NULL-geometry row. The join
        layer's must not be counted, and the source's must not fail the run.

        What makes this hold is PostGIS three-valued logic, not the explicit
        IS NOT NULL term in the predicate — removing that term keeps this test
        green (checked by mutation). The behaviour is what the criterion asks
        for, so the behaviour is what is pinned here.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )

        resp = await client.post(
            _preview_url(points.id),
            json={"operation": "spatial_join", "join_dataset_id": str(polys.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        counts = {
            f["properties"]["gid"]: f["properties"]["join_count"]
            for f in body["geojson"]["features"]
        }
        # 2 real polygons match the overlap point, NOT 3 — the NULL row in the
        # join layer is excluded rather than silently counted.
        assert counts == {1: 2, 2: 1, 3: 0}
        # The source's NULL-geometry row produced no feature and no error.
        assert 4 not in counts

    async def test_invalid_join_geometry_neither_raises_nor_changes_the_count(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The join side is tested RAW, without ST_MakeValid — see the note in
        render_spatial_join for the 33.68s-vs-1.98s measurement behind that.

        This pins the safety half of that trade: a self-intersecting bowtie in
        the join layer must not abort the statement (which ST_Intersection over
        the same geometry does), and must produce the count the repaired
        geometry would.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        # Bowtie crossing at (1,1): two lobes, left and right, and the region
        # directly below the crossing belongs to neither.
        bowtie = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            values_sql=(
                "('bowtie',"
                " ST_GeomFromText('POLYGON((0 0, 2 2, 2 0, 0 2, 0 0))', 4326),"
                " ST_GeomFromText('POLYGON((0 0, 2 2, 2 0, 0 2, 0 0))', 4326))"
            ),
        )
        assert not (
            await test_db_session.execute(
                text(
                    f"SELECT ST_IsValid(geom_4326) "  # noqa: S608
                    f"FROM data.{bowtie.table_name} LIMIT 1"
                )
            )
        ).scalar_one(), "fixture must actually be invalid or this proves nothing"

        probes = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Point",
            geometry_type="POINT",
            values_sql=(
                # Inside the left lobe.
                "('in_lobe', ST_SetSRID(ST_MakePoint(0.3,1.0),4326),"
                " ST_SetSRID(ST_MakePoint(0.3,1.0),4326)),"
                # Below the crossing: inside the bbox, inside NEITHER lobe.
                "('between', ST_SetSRID(ST_MakePoint(1,0.5),4326),"
                " ST_SetSRID(ST_MakePoint(1,0.5),4326))"
            ),
            feature_count=2,
        )

        resp = await client.post(
            _preview_url(probes.id),
            json={"operation": "spatial_join", "join_dataset_id": str(bowtie.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        counts = {
            f["properties"]["gid"]: f["properties"]["join_count"]
            for f in resp.json()["geojson"]["features"]
        }

        # Ground truth from the REPAIRED geometry: the raw predicate must agree.
        expected = {
            gid: (
                await test_db_session.execute(
                    text(
                        f"SELECT count(*) FROM data.{bowtie.table_name} b "  # noqa: S608
                        f"JOIN data.{probes.table_name} p ON p.gid = :gid "
                        f"WHERE ST_Intersects(ST_MakeValid(b.geom_4326), p.geom_4326)"
                    ).bindparams(gid=gid)
                )
            ).scalar_one()
            for gid in counts
        }
        assert counts == expected
        assert set(counts.values()) == {0, 1}, counts

    async def test_match_count_covers_the_whole_source_not_the_cap(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 1: with more source features than PREVIEW_FEATURE_CAP the
        geometry preview truncates, but match_count reports the true total.

        This is the whole reason the count is a separate statement: summing the
        previewed rows would answer for 500 of them and look like the answer.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        n = PREVIEW_FEATURE_CAP + 1
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY, name TEXT,"
                f"  geom geometry(Point, 4326),"
                f"  geom_4326 geometry(Point, 4326))"
            )
        )
        # n points spread across the unit square, so every one of them falls
        # inside poly_a and exactly the ones past x=0.5 also fall inside poly_b.
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (name, geom, geom_4326) "  # noqa: S608
                f"SELECT 'p' || i,"
                f" ST_SetSRID(ST_MakePoint(i::float/{n}, 0.5), 4326),"
                f" ST_SetSRID(ST_MakePoint(i::float/{n}, 0.5), 4326)"
                f" FROM generate_series(1, {n}) AS i"
            )
        )
        await test_db_session.commit()
        source = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
            geometry_type="POINT",
            feature_count=n,
            column_info=[{"name": "name", "type": "text"}],
        )
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )

        resp = await client.post(
            _preview_url(source.id),
            json={"operation": "spatial_join", "join_dataset_id": str(polys.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["truncated"] is True
        assert body["feature_count"] == PREVIEW_FEATURE_CAP
        assert body["source_feature_count"] == n

        # Ground truth, computed independently of the code under test.
        expected = (
            await test_db_session.execute(
                text(
                    f"SELECT count(*) FROM data.{table_name} s "  # noqa: S608
                    f"JOIN data.{polys.table_name} p "
                    f"ON ST_Intersects(s.geom_4326, p.geom_4326)"
                )
            )
        ).scalar_one()
        assert body["match_count"] == expected
        # Not the capped number, and not a per-row count either.
        assert body["match_count"] > PREVIEW_FEATURE_CAP

    async def test_join_dataset_visibility_is_enforced(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 4: Rule 1 applies to BOTH datasets. Read on the source and
        not on the join layer is a 404, not a join the caller cannot see."""
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)
        private_polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id, visibility="private"
        )

        for url in (_preview_url(points.id), _materialize_url(points.id)):
            resp = await client.post(
                url,
                json={
                    "operation": "spatial_join",
                    "join_dataset_id": str(private_polys.id),
                    "title": "Nope",
                },
                headers=editor_auth_header,
            )
            assert resp.status_code == 404, f"{url}: {resp.text}"

    async def test_join_params_are_dropped_for_other_operations(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A stray join_dataset_id on a centroid must be ignored, not loaded —
        the _ANALYSIS_PARAM_OWNERS contract (fix(#682)) extended to the new
        params. A private id here would 404 if it were being resolved."""
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)
        private_polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id, visibility="private"
        )

        resp = await client.post(
            _preview_url(points.id),
            json={
                "operation": "centroid",
                "join_dataset_id": str(private_polys.id),
                "join_fields": ["name"],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        props = resp.json()["geojson"]["features"][0]["properties"]
        assert "join_count" not in props
        assert resp.json()["match_count"] is None


class TestSpatialJoinEnqueueValidation:
    async def test_unknown_join_column_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )

        resp = await client.post(
            _materialize_url(points.id),
            json={
                "operation": "spatial_join",
                "join_dataset_id": str(polys.id),
                "join_fields": ["not_a_column"],
                "title": "Nope",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "not_a_column" in resp.text

    async def test_generated_column_collision_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A source that already has a join_count column would reach the CTAS
        twice and fail it with "column specified more than once" after the
        whole queue wait. Named at enqueue instead."""
        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Point",
            geometry_type="POINT",
            extra_columns="join_count INTEGER,",
            values_sql=(
                "('p', 7, ST_SetSRID(ST_MakePoint(0.75,0.5),4326),"
                " ST_SetSRID(ST_MakePoint(0.75,0.5),4326))"
            ),
            column_info=[
                {"name": "name", "type": "text"},
                {"name": "join_count", "type": "integer"},
            ],
        )
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )

        resp = await client.post(
            _materialize_url(source.id),
            json={
                "operation": "spatial_join",
                "join_dataset_id": str(polys.id),
                "title": "Nope",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "join_count" in resp.text

    async def test_join_field_prefixing_onto_the_count_column_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#1097 review): the generated names must not collide with EACH
        OTHER, only with the source.

        A join layer with an ordinary column named `count` prefixes to
        `join_count`, which is the name the operation already generates for the
        match count. The guard above compares the generated names against the
        SOURCE's columns, so nothing noticed that the list contained the same
        name twice. Materialization then emitted two `join_count` columns and
        failed the CTAS after the whole queue wait, and the preview was worse:
        both values landed on one property, so the transferred field silently
        overwrote the real match count.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)
        polys = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="POLYGON",
            extra_columns='"count" INTEGER,',
            values_sql=(
                "('poly_a', 100, ST_MakeEnvelope(0,0,1,1,4326),"
                " ST_MakeEnvelope(0,0,1,1,4326))"
            ),
            column_info=[
                {"name": "name", "type": "text"},
                {"name": "count", "type": "integer"},
            ],
            feature_count=1,
        )

        resp = await client.post(
            _materialize_url(points.id),
            json={
                "operation": "spatial_join",
                "join_dataset_id": str(polys.id),
                "join_fields": ["count"],
                "title": "Nope",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "join_count" in resp.text

    async def test_the_same_join_field_twice_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The other way the same field arrives twice, caught a layer earlier.

        AnalysisMaterializeRequest already rejects a repeated join_fields entry,
        so this never reaches the router's collision guard. Pinned because the
        rule had no test: without one, the schema validator could be relaxed and
        the only signal would be a CTAS failing on a duplicate column after the
        whole queue wait.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )

        resp = await client.post(
            _materialize_url(points.id),
            json={
                "operation": "spatial_join",
                "join_dataset_id": str(polys.id),
                "join_fields": ["pop", "pop"],
                "title": "Nope",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "must not repeat a column" in resp.text

    async def test_a_count_only_join_is_validated_on_the_preview_path_too(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#1097 review): Preview must not approve what Create refuses.

        The preview path guarded the validator behind `if body.join_fields`,
        but that validator also checks the ALWAYS-generated join_count against
        the source's columns. A source that already had a join_count column
        therefore previewed happily and then failed Create on the identical
        form — the worst split, because the user has been told it works.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Point",
            geometry_type="POINT",
            extra_columns="join_count INTEGER,",
            values_sql=(
                "('p', 7, ST_SetSRID(ST_MakePoint(0.75,0.5),4326),"
                " ST_SetSRID(ST_MakePoint(0.75,0.5),4326))"
            ),
            column_info=[
                {"name": "name", "type": "text"},
                {"name": "join_count", "type": "integer"},
            ],
        )
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )
        body = {"operation": "spatial_join", "join_dataset_id": str(polys.id)}

        # No join_fields at all: the count is still generated.
        preview = await client.post(
            _preview_url(source.id), json=body, headers=admin_auth_header
        )
        assert preview.status_code == 422, preview.text
        assert "join_count" in preview.text

        # And the two paths agree, which is the actual invariant.
        materialize = await client.post(
            _materialize_url(source.id),
            json={**body, "title": "Nope"},
            headers=admin_auth_header,
        )
        assert materialize.status_code == preview.status_code

    async def test_a_join_layer_that_loses_its_geometry_is_caught(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#1097 review): points and lines stay valid, no geometry does not.

        A spatial join counts in any direction, so the join layer is
        deliberately NOT held to the mask's polygon rule. But a re-upload from
        a non-spatial source sets geometry_type to None and builds a table with
        no geom_4326 at all, and render_spatial_join references _j.geom_4326 —
        so the job died on a database error after the queue wait.
        """
        from app.modules.catalog.datasets.domain.models import Dataset
        from app.processing.analysis.tasks import _resolve_layer_table_ref

        admin_id = await get_user_id(test_db_session, "admin")
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )

        # A POINT join layer resolves: direction does not matter to a join.
        polys.geometry_type = "POINT"
        await test_db_session.commit()
        await _resolve_layer_table_ref(
            test_db_session,
            Dataset,
            str(polys.id),
            "data",
            label="join",
            require_geometry="any",
        )

        # No geometry at all does not.
        polys.geometry_type = None
        await test_db_session.commit()
        with pytest.raises(ValueError) as excinfo:
            await _resolve_layer_table_ref(
                test_db_session,
                Dataset,
                str(polys.id),
                "data",
                label="join",
                require_geometry="any",
            )
        assert "geometry" in str(excinfo.value).lower()

    async def test_a_join_field_dropped_after_enqueue_is_caught_before_the_ctas(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#1097 review): the transferred fields were validated at enqueue
        against column_info and never again.

        The worker re-resolved the join layer's TABLE but not its COLUMNS, so a
        re-upload that drops or renames a requested field left
        render_spatial_join referencing a column that no longer exists — and
        the CTAS failed after the whole queue wait, naming a column the user
        had legitimately selected when they asked for it.

        The sibling live rechecks beside this one exist for exactly that
        window. This one was the gap in the set.
        """
        from app.processing.analysis.tasks import _resolve_and_validate_columns

        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )
        # Present at enqueue, gone by the time the job runs.
        await test_db_session.execute(
            text(f"ALTER TABLE data.{polys.table_name} DROP COLUMN pop")  # noqa: S608
        )
        await test_db_session.commit()

        # Through the composition point, not the leaf guard: a test that calls
        # the guard directly stays green when the call site is deleted.
        with pytest.raises(ValueError) as excinfo:
            await _resolve_and_validate_columns(
                test_db_session,
                schema="data",
                operation="spatial_join",
                src_table_name=points.table_name,
                mask_table_name=None,
                join_table_name=polys.table_name,
                join_fields=["name", "pop"],
            )
        assert "pop" in str(excinfo.value)

    async def test_join_fields_that_still_exist_pass_the_live_recheck(
        self,
        test_db_session: AsyncSession,
    ):
        """The negative control: the recheck must not refuse an unchanged join
        layer, or every attribute transfer would fail at the worker."""
        from app.processing.analysis.tasks import _resolve_and_validate_columns

        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )
        for fields in (["name", "pop"], None):
            await _resolve_and_validate_columns(
                test_db_session,
                schema="data",
                operation="spatial_join",
                src_table_name=points.table_name,
                mask_table_name=None,
                join_table_name=polys.table_name,
                join_fields=fields,
            )

    async def test_oversized_source_rejected_at_enqueue(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Criterion 5: spatial_join has a MAX_SOURCE_FEATURES entry and the
        enqueue-time 422 fires. Without the entry the router's .get() would
        skip the gate entirely rather than apply a default."""
        assert "spatial_join" in MAX_SOURCE_FEATURES
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )
        # The cached snapshot is what the gate reads first.
        points.feature_count = MAX_SOURCE_FEATURES["spatial_join"] + 1
        await test_db_session.commit()

        resp = await client.post(
            _materialize_url(points.id),
            json={
                "operation": "spatial_join",
                "join_dataset_id": str(polys.id),
                "title": "Too big",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "too large" in resp.text

    async def test_missing_join_dataset_id_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)

        resp = await client.post(
            _preview_url(points.id),
            json={"operation": "spatial_join"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_job_metadata_records_the_join(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Admin → Jobs has to be able to say what a failed run was doing."""
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(points.id),
                json={
                    "operation": "spatial_join",
                    "join_dataset_id": str(polys.id),
                    "join_fields": ["name"],
                    "title": f"Joined {uuid.uuid4().hex[:6]}",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text

        from app.platform.jobs.models import IngestJob

        job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
        meta = job.user_metadata["analysis"]
        assert meta["operation"] == "spatial_join"
        assert meta["join_dataset_id"] == str(polys.id)
        assert meta["join_fields"] == ["name"]
        # Release the per-user active-job slot for later tests (shared DB).
        # The patched defer leaves this job pending forever, and the endpoint
        # allows one active analysis job per user — so without this every
        # later materialize in the run earns a 429 instead of testing itself.
        job.status = "failed"
        await test_db_session.commit()


class TestSpatialJoinWorker:
    async def test_materialize_creates_a_tileable_1to1_dataset(
        self,
        test_db_session: AsyncSession,
    ):
        """Criteria 2 (materialize half) and 6: one row per source feature, the
        tie-break agreeing with the preview, source attributes carried, and an
        output that registers with a real geometry type.

        The duplicate-row failure this pins is not subtle: two rows for one
        source gid violate ADD PRIMARY KEY (gid) and the job dies on a
        constraint error rather than anything a user could act on.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_probe_points(test_db_session, created_by=admin_id)
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(points.id),
            user_id=str(admin_id),
            operation="spatial_join",
            title=f"Points in polys {uuid.uuid4().hex[:6]}",
            join_dataset_id=str(polys.id),
            join_fields=["name", "pop"],
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        # 3 of the 4 source rows: the NULL-geometry one is dropped, and NOT a
        # 4th row from the overlap point matching two polygons.
        assert new_ds.feature_count == 3
        assert new_ds.geometry_type == "POINT"

        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT gid, name, join_count, join_name, join_pop, "  # noqa: S608
                    f"GeometryType(geom_4326) "
                    f"FROM data.{new_ds.table_name} ORDER BY gid"
                )
            )
        ).all()
        assert rows == [
            (1, "in_both", 2, "poly_a", 100, "POINT"),
            (2, "in_a_only", 1, "poly_a", 100, "POINT"),
            (3, "outside", 0, None, None, "POINT"),
        ]

    async def test_worker_rejects_a_collision_the_router_did_not_see(
        self,
        test_db_session: AsyncSession,
    ):
        """The router validates against column_info, a catalog snapshot. The
        worker holds the LIVE column list, and the queue wait sits between
        them — so the collision check runs again there, with a message rather
        than a raw "column specified more than once"."""
        admin_id = await get_user_id(test_db_session, "admin")
        source = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Point",
            geometry_type="POINT",
            extra_columns="join_count INTEGER,",
            values_sql=(
                "('p', 7, ST_SetSRID(ST_MakePoint(0.75,0.5),4326),"
                " ST_SetSRID(ST_MakePoint(0.75,0.5),4326))"
            ),
            # Stale snapshot: the router would see nothing wrong here.
            column_info=[{"name": "name", "type": "text"}],
        )
        polys = await _create_two_overlapping_polygons(
            test_db_session, created_by=admin_id
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(source.id),
            user_id=str(admin_id),
            operation="spatial_join",
            title=f"Collides {uuid.uuid4().hex[:6]}",
            join_dataset_id=str(polys.id),
        )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "join_count" in (job.error_message or "")
