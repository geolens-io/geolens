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


async def _create_dataset(
    session, *, created_by: uuid.UUID, rows: int = ROW_COUNT
) -> Dataset:
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
    for i in range(rows):
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
        feature_count=rows,
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
    page = await features_service.get_features(
        test_db_session,
        counted_dataset.table_name,
        limit=5,
        property_filters={"era": "Art Deco"},
        allowed_columns={"era"},
        cached_feature_count=ROW_COUNT,
    )

    assert len(page.rows) == 5
    assert page.total == ROW_COUNT
    assert page.total_is_estimate is False


async def test_a_filtered_count_above_the_cap_stops_and_estimates(
    counted_dataset: Dataset, test_db_session, monkeypatch
):
    """Past the cap the scan stops and the planner answers instead."""
    monkeypatch.setattr(features_service, "_FILTERED_COUNT_CAP", 5)

    page = await features_service.get_features(
        test_db_session,
        counted_dataset.table_name,
        limit=2,
        property_filters={"era": "Art Deco"},
        allowed_columns={"era"},
        cached_feature_count=ROW_COUNT,
    )

    assert page.total_is_estimate is True
    # Never below the rows already counted, so `offset + limit < total`
    # pagination cannot truncate at the cap.
    assert page.total > 5


async def test_the_unfiltered_page_still_uses_the_cached_count(
    counted_dataset: Dataset, test_db_session, monkeypatch
):
    """The fast path is untouched: no filter, no count query, never an estimate."""
    monkeypatch.setattr(features_service, "_FILTERED_COUNT_CAP", 1)

    page = await features_service.get_features(
        test_db_session,
        counted_dataset.table_name,
        limit=2,
        cached_feature_count=ROW_COUNT,
    )

    assert page.total == ROW_COUNT
    assert page.total_is_estimate is False


async def test_the_keyset_cursor_is_still_excluded_from_the_count(
    counted_dataset: Dataset, test_db_session
):
    """The total is the whole match set, not the rows after the cursor."""
    page = await features_service.get_features(
        test_db_session,
        counted_dataset.table_name,
        limit=5,
        after_gid=10,
        property_filters={"era": "Art Deco"},
        allowed_columns={"era"},
        cached_feature_count=ROW_COUNT,
    )

    assert page.total == ROW_COUNT
    assert page.total_is_estimate is False


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


# ---------------------------------------------------------------------------
# fix(#1778 review r1): pagination must not depend on the estimated total.
# ---------------------------------------------------------------------------

DEEP_ROW_COUNT = 20_300


async def _create_deep_dataset(session, *, created_by: uuid.UUID) -> Dataset:
    """A layer with more matching rows than the exact-count cap."""
    table_name = f"test_dp_{uuid.uuid4().hex[:8]}"
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
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (geom, geom_4326, era) "
            "SELECT ST_SetSRID(ST_MakePoint(-74.0, 40.0 + i / 1000000.0), 4326), "
            "       ST_SetSRID(ST_MakePoint(-74.0, 40.0 + i / 1000000.0), 4326), "
            "       'Art Deco' "
            "FROM generate_series(1, :n) AS i"
        ).bindparams(n=DEEP_ROW_COUNT)
    )

    record = Record(
        title=f"Deep paging {table_name}",
        summary="More matches than the exact-count cap",
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
        feature_count=DEEP_ROW_COUNT,
        column_info=[{"name": "era", "type": "text"}],
        source_format="created",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


@pytest.fixture
async def deep_dataset(client: AsyncClient, test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_deep_dataset(test_db_session, created_by=admin_id)
    yield dataset
    await test_db_session.execute(
        text(f"DROP TABLE IF EXISTS data.{dataset.table_name}")
    )
    await test_db_session.commit()


@pytest.fixture
def estimate_forced_low(monkeypatch):
    """Make the planner estimate useless, the way a stale ANALYZE would."""

    async def _low(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(features_service, "_planner_row_estimate", _low)


async def test_a_low_estimate_does_not_strand_a_full_page(
    client: AsyncClient,
    deep_dataset: Dataset,
    admin_auth_header,
    estimate_forced_low,
):
    """The page at the cap boundary still links to the rest of the result set.

    With the count capped at 20000 and the estimate forced low, `total` lands at
    20001. A `next` link decided by `offset + limit < total` reads
    20200 < 20001 as false and disappears with a full page on screen and 100
    rows still to come.
    """
    resp = await client.get(
        f"/datasets/{deep_dataset.id}/features/",
        params={"era": "Art Deco", "offset": 20_000, "limit": 200},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["numberReturned"] == 200
    next_link = next((li for li in data["links"] if li["rel"] == "next"), None)
    assert next_link is not None, "a full page with rows remaining must link on"
    assert "offset=20200" in next_link["href"]
    # numberMatched may be an estimate, but it may never contradict the rows
    # already served beside it.
    assert data["numberMatched"] >= 20_200


async def test_the_last_page_emits_no_next_link(
    client: AsyncClient,
    deep_dataset: Dataset,
    admin_auth_header,
    estimate_forced_low,
):
    resp = await client.get(
        f"/datasets/{deep_dataset.id}/features/",
        params={"era": "Art Deco", "offset": 20_200, "limit": 200},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["numberReturned"] == DEEP_ROW_COUNT - 20_200
    assert not [li for li in data["links"] if li["rel"] == "next"]


async def test_has_more_is_measured_from_the_rows_not_the_total(
    deep_dataset: Dataset, test_db_session, estimate_forced_low
):
    """The mechanism, separate from the link it feeds."""
    page = await features_service.get_features(
        test_db_session,
        deep_dataset.table_name,
        limit=200,
        offset=20_000,
        property_filters={"era": "Art Deco"},
        allowed_columns={"era"},
        cached_feature_count=DEEP_ROW_COUNT,
    )

    assert len(page.rows) == 200
    assert page.has_more is True
    assert page.total_is_estimate is True


async def test_the_ogc_items_page_links_on_at_the_cap_boundary(
    client: AsyncClient, deep_dataset: Dataset, estimate_forced_low
):
    """The OGC handler reads the same has_more rather than re-deriving one."""
    resp = await client.get(
        f"/collections/{deep_dataset.id}/items",
        params={"era": "Art Deco", "offset": 20_000, "limit": 200},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["numberReturned"] == 200
    assert [li for li in data["links"] if li["rel"] == "next"]
    assert data["numberMatched"] >= 20_200


# ---------------------------------------------------------------------------
# fix(#1778 review r3): the floor may only count rows that exist.
# ---------------------------------------------------------------------------

SMALL_ROW_COUNT = 5


@pytest.fixture
async def small_dataset(client: AsyncClient, test_db_session):
    """Five matching rows, so an offset of 100 lands well past the end."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_dataset(
        test_db_session, created_by=admin_id, rows=SMALL_ROW_COUNT
    )
    yield dataset
    await test_db_session.execute(
        text(f"DROP TABLE IF EXISTS data.{dataset.table_name}")
    )
    await test_db_session.commit()


async def test_native_offset_past_the_end_reports_the_true_total(
    client: AsyncClient, small_dataset: Dataset, admin_auth_header
):
    """An empty page proves nothing, so it must not raise the count."""
    resp = await client.get(
        f"/datasets/{small_dataset.id}/features/",
        params={"era": "Art Deco", "offset": 100, "limit": 10},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["numberReturned"] == 0
    assert data["numberMatched"] == SMALL_ROW_COUNT
    assert not [li for li in data["links"] if li["rel"] == "next"]


async def test_ogc_offset_past_the_end_reports_the_true_total(
    client: AsyncClient, small_dataset: Dataset
):
    resp = await client.get(
        f"/collections/{small_dataset.id}/items",
        params={"era": "Art Deco", "offset": 100, "limit": 10},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["numberReturned"] == 0
    assert data["numberMatched"] == SMALL_ROW_COUNT
    assert not [li for li in data["links"] if li["rel"] == "next"]


async def test_a_keyset_page_reports_the_true_total_and_ignores_offset(
    client: AsyncClient, counted_dataset: Dataset, test_db_session
):
    """The query ignores `offset` under after_gid, so the floor must too."""
    first_gid = (
        await test_db_session.execute(
            text(f"SELECT MIN(gid) FROM data.{counted_dataset.table_name}")
        )
    ).scalar_one()

    resp = await client.get(
        f"/collections/{counted_dataset.id}/items",
        params={
            "era": "Art Deco",
            "after_gid": first_gid,
            "offset": 100,
            "limit": 10,
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["numberReturned"] == 10
    assert data["numberMatched"] == ROW_COUNT


async def test_an_exact_count_is_never_raised(small_dataset: Dataset, test_db_session):
    """A full page of an exact count stays at the count, not count + 1."""
    page = await features_service.get_features(
        test_db_session,
        small_dataset.table_name,
        limit=2,
        property_filters={"era": "Art Deco"},
        allowed_columns={"era"},
        cached_feature_count=SMALL_ROW_COUNT,
    )

    assert len(page.rows) == 2
    assert page.has_more is True
    assert page.total_is_estimate is False
    assert page.total == SMALL_ROW_COUNT


async def test_an_estimated_full_page_still_floors_to_offset_plus_rows(
    deep_dataset: Dataset, test_db_session, estimate_forced_low
):
    """The r1 property the r3 narrowing must not have thrown away."""
    page = await features_service.get_features(
        test_db_session,
        deep_dataset.table_name,
        limit=200,
        offset=20_000,
        property_filters={"era": "Art Deco"},
        allowed_columns={"era"},
        cached_feature_count=DEEP_ROW_COUNT,
    )

    assert page.total_is_estimate is True
    assert page.has_more is True
    assert page.total == 20_000 + 200 + 1


async def test_an_estimated_empty_page_is_not_floored(
    deep_dataset: Dataset, test_db_session, estimate_forced_low
):
    """Past the end, even an estimate has no rows to prove anything with."""
    page = await features_service.get_features(
        test_db_session,
        deep_dataset.table_name,
        limit=200,
        offset=DEEP_ROW_COUNT + 1_000,
        property_filters={"era": "Art Deco"},
        allowed_columns={"era"},
        cached_feature_count=DEEP_ROW_COUNT,
    )

    assert page.rows == []
    assert page.total < DEEP_ROW_COUNT + 1_000
