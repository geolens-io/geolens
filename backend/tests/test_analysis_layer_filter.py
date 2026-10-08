"""Analysis inputs honour each layer's filter.

The builder sends a layer's filter as CQL2-JSON, the language the OGC items
``filter`` parameter accepts, and the same code validates and compiles it.
Previews, materialized outputs and the size limits all count only the
features a filter keeps, and a materialized output records its source filter.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.api import router_analysis
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import IngestJob
from app.processing.analysis.tasks import _materialize

from tests.factories import get_user_id
from tests.test_analysis_materialize import _create_job
from tests.test_analysis_spatial_join import _create_layer

pytestmark = pytest.mark.anyio

KEEP = {"op": "=", "args": [{"property": "kind"}, "keep"]}
ONLY_A = {"op": "=", "args": [{"property": "name"}, "A"]}

# Two side-by-side squares: A covers points 1-4, B covers points 5-8.
SQUARE_A = "POLYGON((0 -0.001, 0.0045 -0.001, 0.0045 0.001, 0 0.001, 0 -0.001))"
SQUARE_B = (
    "POLYGON((0.0045 -0.001, 0.01 -0.001, 0.01 0.001, 0.0045 0.001, 0.0045 -0.001))"
)


async def _create_points(session: AsyncSession, *, created_by: uuid.UUID):
    """Eight points on the equator; gids 1-6 are ``keep``, 7-8 are ``drop``."""
    rows = ", ".join(
        f"('p{i}', '{'keep' if i <= 6 else 'drop'}', {i},"
        f" ST_SetSRID(ST_MakePoint({i * 0.001}, 0), 4326),"
        f" ST_SetSRID(ST_MakePoint({i * 0.001}, 0), 4326))"
        for i in range(1, 9)
    )
    return await _create_layer(
        session,
        created_by=created_by,
        column_type="Point",
        geometry_type="POINT",
        extra_columns="kind TEXT, pop INTEGER,",
        column_info=[
            {"name": "name", "type": "text"},
            {"name": "kind", "type": "text"},
            {"name": "pop", "type": "integer"},
        ],
        feature_count=8,
        values_sql=rows,
    )


async def _create_squares(
    session: AsyncSession, *, created_by: uuid.UUID, visibility: str = "public"
):
    return await _create_layer(
        session,
        created_by=created_by,
        column_type="Polygon",
        geometry_type="POLYGON",
        feature_count=2,
        visibility=visibility,
        values_sql=(
            f"('A', ST_GeomFromText('{SQUARE_A}', 4326),"
            f" ST_GeomFromText('{SQUARE_A}', 4326)),"
            f"('B', ST_GeomFromText('{SQUARE_B}', 4326),"
            f" ST_GeomFromText('{SQUARE_B}', 4326))"
        ),
    )


def _gids(payload: dict) -> list[int]:
    return sorted(f["properties"]["gid"] for f in payload["geojson"]["features"])


class TestPreview:
    async def test_a_buffer_previews_only_the_filtered_points(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Six of eight points pass the filter, so six buffers come back."""
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_points(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{points.id}/analysis/preview/",
            json={"operation": "buffer", "distance_meters": 10, "filter": KEEP},
            headers=admin_auth_header,
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert _gids(body) == [1, 2, 3, 4, 5, 6]
        assert body["feature_count"] == 6
        # The denominator is the filtered layer, not the cached whole table.
        assert body["source_feature_count"] == 6

    async def test_a_mask_filter_narrows_the_selecting_layer(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_points(test_db_session, created_by=admin_id)
        squares = await _create_squares(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{points.id}/analysis/preview/",
            json={
                "operation": "select_by_location",
                "mask_dataset_id": str(squares.id),
                "mask_filter": ONLY_A,
                "filter": KEEP,
            },
            headers=admin_auth_header,
        )

        assert resp.status_code == 200, resp.text
        assert _gids(resp.json()) == [1, 2, 3, 4]
        assert resp.json()["match_count"] == 4

    async def test_a_join_filter_narrows_what_is_counted(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_points(test_db_session, created_by=admin_id)
        squares = await _create_squares(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{points.id}/analysis/preview/",
            json={
                "operation": "spatial_join",
                "join_dataset_id": str(squares.id),
                "join_filter": ONLY_A,
            },
            headers=admin_auth_header,
        )

        assert resp.status_code == 200, resp.text
        counts = {
            f["properties"]["gid"]: f["properties"]["join_count"]
            for f in resp.json()["geojson"]["features"]
        }
        assert counts == {1: 1, 2: 1, 3: 1, 4: 1, 5: 0, 6: 0, 7: 0, 8: 0}
        assert resp.json()["match_count"] == 4

    @pytest.mark.parametrize(
        ("cql2", "expected"),
        [
            # The shapes the builder's filter editor produces.
            ({"op": "like", "args": [{"property": "name"}, "%p1%"]}, [1]),
            ({"op": "like", "args": [{"property": "name"}, "%\\_%"]}, []),
            ({"op": "in", "args": [{"property": "pop"}, [2, 3]]}, [2, 3]),
            (
                {
                    "op": "or",
                    "args": [
                        {"op": "isNull", "args": [{"property": "kind"}]},
                        {"op": "<>", "args": [{"property": "kind"}, "keep"]},
                    ],
                },
                [7, 8],
            ),
            (
                {
                    "op": "and",
                    "args": [
                        {"op": ">=", "args": [{"property": "pop"}, 3]},
                        {
                            "op": "not",
                            "args": [{"op": "isNull", "args": [{"property": "kind"}]}],
                        },
                    ],
                },
                [3, 4, 5, 6, 7, 8],
            ),
        ],
        ids=["contains", "escaped-wildcard", "in-list", "not-equal", "and-has"],
    )
    async def test_each_builder_filter_shape(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        cql2: dict,
        expected: list[int],
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_points(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{points.id}/analysis/preview/",
            json={"operation": "centroid", "filter": cql2},
            headers=admin_auth_header,
        )

        assert resp.status_code == 200, resp.text
        assert _gids(resp.json()) == expected

    @pytest.mark.parametrize(
        "bad_filter",
        [
            {"op": "=", "args": [{"property": "no_such_column"}, "x"]},
            {"op": "=", "args": [{"property": "pop"}, "not a number"]},
            {"op": "nonsense", "args": []},
        ],
        ids=["unknown-column", "type-mismatch", "malformed"],
    )
    async def test_an_invalid_filter_is_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        bad_filter: dict,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_points(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{points.id}/analysis/preview/",
            json={"operation": "centroid", "filter": bad_filter},
            headers=admin_auth_header,
        )

        assert resp.status_code == 422, resp.text

    async def test_a_drawn_mask_takes_no_mask_filter(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_points(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{points.id}/analysis/preview/",
            json={
                "operation": "clip",
                "mask": {
                    "type": "Polygon",
                    "coordinates": [[[0, -1], [1, -1], [1, 1], [0, 1], [0, -1]]],
                },
                "mask_filter": ONLY_A,
            },
            headers=admin_auth_header,
        )

        assert resp.status_code == 422
        assert "mask_filter requires mask_dataset_id" in resp.text


class TestMaterialize:
    async def test_the_size_limit_counts_filtered_rows(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Eight points are over a limit of seven; the six the filter keeps are not."""
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_points(test_db_session, created_by=admin_id)

        with patch.dict("app.platform.analysis_sql.MAX_SOURCE_FEATURES", {"buffer": 7}):
            whole = await client.post(
                f"/datasets/{points.id}/analysis/materialize/",
                json={"operation": "buffer", "distance_meters": 10, "title": "All"},
                headers=admin_auth_header,
            )
            with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
                filtered = await client.post(
                    f"/datasets/{points.id}/analysis/materialize/",
                    json={
                        "operation": "buffer",
                        "distance_meters": 10,
                        "title": "Kept",
                        "filter": KEEP,
                    },
                    headers=admin_auth_header,
                )

        assert whole.status_code == 422
        assert "too large for buffer" in whole.json()["detail"]
        assert filtered.status_code == 200, filtered.text
        job = await test_db_session.get(IngestJob, uuid.UUID(filtered.json()["job_id"]))
        assert job.user_metadata["analysis"]["source_filter"] == KEEP
        job.status = "failed"
        await test_db_session.commit()

    async def test_an_invalid_filter_is_rejected_before_a_job_exists(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_points(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{points.id}/analysis/materialize/",
            json={
                "operation": "centroid",
                "title": "Bad",
                "filter": {"op": "=", "args": [{"property": "missing"}, 1]},
            },
            headers=admin_auth_header,
        )

        assert resp.status_code == 422
        assert "missing" in resp.json()["detail"]

    async def test_the_output_holds_the_filtered_rows_and_records_the_filter(
        self, test_db_session: AsyncSession
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_points(test_db_session, created_by=admin_id)
        squares = await _create_squares(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(points.id),
            user_id=str(admin_id),
            operation="select_by_location",
            title=f"Kept {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(squares.id),
            source_filter=KEEP,
            mask_filter=ONLY_A,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        out = await test_db_session.get(Dataset, job.dataset_id)
        assert out.feature_count == 4
        record = (
            await test_db_session.execute(
                select(Record).where(Record.id == out.record_id)
            )
        ).scalar_one()
        assert record.derived_from["dataset_id"] == str(points.id)
        assert record.derived_from["source_filter"] == KEEP
        assert record.derived_from["params"]["mask_filter"] == ONLY_A
        assert "using its features filtered on kind" in record.lineage_summary
        # Search matches this prose before redaction, so no filter value.
        assert "keep" not in record.lineage_summary

    @pytest.mark.parametrize(
        ("operation", "params", "expected"),
        [
            ("buffer", {"distance_meters": 10}, 6),
            ("centroid", {}, 6),
            ("measure", {}, 6),
            ("dissolve", {}, 1),
            ("clip", {"mask_filter": ONLY_A}, 4),
            ("intersect", {"mask_filter": ONLY_A}, 4),
            ("spatial_join", {"join_filter": ONLY_A}, 6),
        ],
    )
    async def test_every_operation_reads_the_filtered_layers(
        self,
        test_db_session: AsyncSession,
        operation: str,
        params: dict,
        expected: int,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_points(test_db_session, created_by=admin_id)
        squares = await _create_squares(test_db_session, created_by=admin_id)
        if operation == "intersect":
            # An overlay carries both layers' columns, so they may not share one.
            await test_db_session.execute(
                text(f"ALTER TABLE data.{points.table_name} DROP COLUMN name")
            )
            await test_db_session.commit()
        job = await _create_job(test_db_session, admin_id)
        layer = (
            {"join_dataset_id": str(squares.id)}
            if operation == "spatial_join"
            else {"mask_dataset_id": str(squares.id)}
            if "mask_filter" in params
            else {}
        )

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(points.id),
            user_id=str(admin_id),
            operation=operation,
            title=f"{operation} {uuid.uuid4().hex[:6]}",
            source_filter=KEEP,
            **layer,
            **params,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        out = await test_db_session.get(Dataset, job.dataset_id)
        assert out.feature_count == expected

    async def test_a_filter_on_a_column_dropped_while_queued_fails_the_job(
        self, test_db_session: AsyncSession
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_points(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(points.id),
            user_id=str(admin_id),
            operation="centroid",
            title=f"Gone {uuid.uuid4().hex[:6]}",
            source_filter={"op": "=", "args": [{"property": "renamed"}, "x"]},
        )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "source layer's filter can't be applied" in job.error_message


class TestProvenanceRedaction:
    async def test_a_private_mask_layer_takes_its_filter_with_it(
        self, test_db_session: AsyncSession
    ):
        """A mask filter names the mask layer's columns and values."""
        from app.modules.catalog.authorization import visible_derived_from

        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_points(test_db_session, created_by=admin_id)
        private_mask = await _create_squares(
            test_db_session, created_by=admin_id, visibility="private"
        )
        reference = {
            "dataset_id": str(points.id),
            "source_filter": KEEP,
            "operation": "select_by_location",
            "params": {
                "mask_dataset_id": str(private_mask.id),
                "mask_filter": ONLY_A,
            },
            "created_at": "2026-10-07T00:00:00+00:00",
        }

        anonymous = await visible_derived_from(test_db_session, reference, None, set())

        assert anonymous is not None
        assert anonymous["source_filter"] == KEEP
        assert "mask_dataset_id" not in anonymous["params"]
        assert "mask_filter" not in anonymous["params"]
