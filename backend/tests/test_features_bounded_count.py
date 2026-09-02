"""fix(#1778): a filtered feature page must not pay a full COUNT(*) every time.

`get_features` only reached its cached-feature_count fast path on a completely
unfiltered request, and it deliberately strips the keyset cursor from the count
so the total reflects the whole match set. One bbox or property filter
therefore put a full filtered COUNT(*) on EVERY page, including the keyset
pages whose entire purpose is constant-time access: 50 pages cost 50 full
scans, and the OGC caller saw constant-time row fetch with O(N) latency per
page.

The count now runs inside a LIMIT, so it is exact up to `_FILTERED_COUNT_CAP`
and bounded past it, where the planner's row estimate answers instead and the
response carries `X-GeoLens-Number-Matched: estimated`.

Requires the Docker test database.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.features import service as features_service
from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import get_user_id

pytestmark = pytest.mark.anyio

ROW_COUNT = 30


async def _create_dataset(session, *, created_by: uuid.UUID) -> Dataset:
    table_name = f"test_bc_{uuid.uuid4().hex[:8]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            "gid SERIAL PRIMARY KEY, "
            "geom geometry(Point, 4326), "
            "geom_4326 geometry(Point, 4326), "
            "era TEXT)"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))
    for i in range(ROW_COUNT):
        await session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326, era) VALUES ("
                "ST_SetSRID(ST_MakePoint(-74.0, :lat), 4326), "
                "ST_SetSRID(ST_MakePoint(-74.0, :lat), 4326), 'Art Deco')"
            ).bindparams(lat=40.0 + i / 1000.0)
        )
    # So the planner has real statistics to estimate from.
    await session.execute(text(f"ANALYZE data.{table_name}"))

    record = Record(
        title=f"Bounded count {table_name}",
        summary="Bounded filtered counts",
        theme_category=["test"],
        visibility="public",
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="POINT",
        feature_count=ROW_COUNT,
        column_info=[{"name": "era", "type": "text"}],
        source_format="created",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


@pytest.fixture
async def counted_dataset(client: AsyncClient, test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_dataset(test_db_session, created_by=admin_id)
    yield dataset
    await test_db_session.execute(
        text(f"DROP TABLE IF EXISTS data.{dataset.table_name}")
    )
    await test_db_session.commit()


async def test_a_filtered_count_below_the_cap_is_exact(
    counted_dataset: Dataset, test_db_session
):
    rows, total, estimated = await features_service.get_features(
        test_db_session,
        counted_dataset.table_name,
        limit=5,
        property_filters={"era": "Art Deco"},
        allowed_columns={"era"},
        cached_feature_count=ROW_COUNT,
    )

    assert len(rows) == 5
    assert total == ROW_COUNT
    assert estimated is False


async def test_a_filtered_count_above_the_cap_stops_and_estimates(
    counted_dataset: Dataset, test_db_session, monkeypatch
):
    """Past the cap the scan stops and the planner answers instead."""
    monkeypatch.setattr(features_service, "_FILTERED_COUNT_CAP", 5)

    _rows, total, estimated = await features_service.get_features(
        test_db_session,
        counted_dataset.table_name,
        limit=2,
        property_filters={"era": "Art Deco"},
        allowed_columns={"era"},
        cached_feature_count=ROW_COUNT,
    )

    assert estimated is True
    # Never below the rows already counted, so `offset + limit < total`
    # pagination cannot truncate at the cap.
    assert total > 5


async def test_the_unfiltered_page_still_uses_the_cached_count(
    counted_dataset: Dataset, test_db_session, monkeypatch
):
    """The fast path is untouched: no filter, no count query, never an estimate."""
    monkeypatch.setattr(features_service, "_FILTERED_COUNT_CAP", 1)

    _rows, total, estimated = await features_service.get_features(
        test_db_session,
        counted_dataset.table_name,
        limit=2,
        cached_feature_count=ROW_COUNT,
    )

    assert total == ROW_COUNT
    assert estimated is False


async def test_the_keyset_cursor_is_still_excluded_from_the_count(
    counted_dataset: Dataset, test_db_session
):
    """The total is the whole match set, not the rows after the cursor."""
    _rows, total, estimated = await features_service.get_features(
        test_db_session,
        counted_dataset.table_name,
        limit=5,
        after_gid=10,
        property_filters={"era": "Art Deco"},
        allowed_columns={"era"},
        cached_feature_count=ROW_COUNT,
    )

    assert total == ROW_COUNT
    assert estimated is False


async def test_an_exact_page_carries_no_estimate_header(
    client: AsyncClient, counted_dataset: Dataset
):
    resp = await client.get(
        f"/collections/{counted_dataset.id}/items", params={"era": "Art Deco"}
    )

    assert resp.status_code == 200
    assert resp.json()["numberMatched"] == ROW_COUNT
    assert "x-geolens-number-matched" not in resp.headers


async def test_an_estimated_page_says_so_in_a_header(
    client: AsyncClient, counted_dataset: Dataset, monkeypatch
):
    monkeypatch.setattr(features_service, "_FILTERED_COUNT_CAP", 5)

    resp = await client.get(
        f"/collections/{counted_dataset.id}/items", params={"era": "Art Deco"}
    )

    assert resp.status_code == 200
    assert resp.headers["x-geolens-number-matched"] == "estimated"
    assert resp.json()["numberMatched"] > 5


async def test_the_estimate_header_is_readable_cross_origin(
    client: AsyncClient, counted_dataset: Dataset
):
    """A response header outside Fetch's safelist is invisible, not merely undocumented."""
    resp = await client.get(
        f"/collections/{counted_dataset.id}/items",
        headers={"Origin": "https://example.invalid"},
    )

    exposed = {
        name.strip().lower()
        for name in resp.headers.get("access-control-expose-headers", "").split(",")
    }
    assert "content-crs" in exposed, "the anonymous standards policy did not apply"
    assert "x-geolens-number-matched" in exposed
