"""Pagination stability tests for /search/datasets.

Regression coverage: the standard (non-RRF) sort path used 6 ORDER BY
branches, none of which had a unique tiebreaker. When many rows tie on the
sort key (same record_status, updated_at, created_at, title) OFFSET/LIMIT
returned a non-stable order, so paging the full result set produced duplicate
records on some pages and dropped others.

The fix appends Record.id (the UUID PK) as a deterministic final tiebreaker to
every branch. These tests seed > limit datasets with identical sort keys, page
the whole set at a small limit, and assert: no dupes, no drops, full coverage,
and an identical order across two independent runs.
"""

import uuid
from datetime import date
from urllib.parse import urlsplit

import pytest
from httpx import AsyncClient
from sqlalchemy import func, update

from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_tied_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    keyword_tag: str,
    fixed_ts,
) -> Dataset:
    """Insert a Record + Dataset whose sort keys are identical to its siblings.

    title, record_status, created_at and updated_at are all pinned to the same
    value so the only thing distinguishing rows is the UUID PK tiebreaker.
    """
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Description for {name}",
        visibility="public",
        record_status="published",
        created_by=created_by,
        theme_category=[keyword_tag],
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="MultiPolygon",
        feature_count=100,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()

    # Pin created_at / updated_at to identical timestamps so every row ties.
    await session.execute(
        update(Record)
        .where(Record.id == record.id)
        .values(created_at=fixed_ts, updated_at=fixed_ts)
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _page_all_ids(
    client: AsyncClient,
    headers: dict,
    *,
    sort_by: str,
    keyword_tag: str,
    page_size: int,
) -> list[str]:
    """Walk every page of a search and collect the dataset feature ids in order."""
    all_ids: list[str] = []
    offset = 0
    # Use the theme_category token as q so only our seeded datasets match.
    while True:
        resp = await client.get(
            "/search/datasets/",
            params={
                "q": keyword_tag,
                "sort_by": sort_by,
                "limit": page_size,
                "offset": offset,
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        page_ids = [
            f["id"]
            for f in data["features"]
            if f["properties"].get("type") != "collection"
        ]
        all_ids.extend(page_ids)
        offset += page_size
        if offset >= data["numberMatched"]:
            break
        # Safety valve against an accidental infinite loop.
        if offset > data["numberMatched"] + page_size * 5:
            pytest.fail("pagination did not terminate")
    return all_ids


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def tied_datasets(test_db_session):
    """Seed a pool of datasets that tie on every non-id sort key."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    keyword_tag = f"tiebreak{uuid.uuid4().hex[:8]}"
    fixed_ts = date(2024, 3, 14)
    datasets = []
    # 7 rows, all identical sort keys; page at limit=2 (4 pages).
    for _ in range(7):
        ds = await _create_tied_dataset(
            session,
            created_by=admin_id,
            name="Identical Tiebreak Dataset",
            keyword_tag=keyword_tag,
            fixed_ts=fixed_ts,
        )
        datasets.append(ds)
    return {"datasets": datasets, "keyword_tag": keyword_tag}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "sort_by",
    ["relevance", "date_added", "last_updated", "title", "name"],
)
async def test_pagination_no_dupes_no_drops_across_branches(
    client: AsyncClient,
    admin_auth_header: dict,
    tied_datasets: dict,
    sort_by: str,
):
    expected = {str(ds.id) for ds in tied_datasets["datasets"]}
    keyword_tag = tied_datasets["keyword_tag"]

    paged = await _page_all_ids(
        client,
        admin_auth_header,
        sort_by=sort_by,
        keyword_tag=keyword_tag,
        page_size=2,
    )

    seen = [pid for pid in paged if pid in expected]
    assert len(seen) == len(set(seen)), f"duplicate ids paging sort_by={sort_by}"
    assert set(seen) == expected, f"missing/extra ids paging sort_by={sort_by}"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "sort_by",
    ["relevance", "date_added", "last_updated", "title", "name"],
)
async def test_pagination_order_is_stable_across_runs(
    client: AsyncClient,
    admin_auth_header: dict,
    tied_datasets: dict,
    sort_by: str,
):
    expected = {str(ds.id) for ds in tied_datasets["datasets"]}
    keyword_tag = tied_datasets["keyword_tag"]

    run1 = [
        pid
        for pid in await _page_all_ids(
            client,
            admin_auth_header,
            sort_by=sort_by,
            keyword_tag=keyword_tag,
            page_size=2,
        )
        if pid in expected
    ]
    run2 = [
        pid
        for pid in await _page_all_ids(
            client,
            admin_auth_header,
            sort_by=sort_by,
            keyword_tag=keyword_tag,
            page_size=2,
        )
        if pid in expected
    ]
    assert run1 == run2, f"unstable order across runs for sort_by={sort_by}"


# ---------------------------------------------------------------------------
# Continuation links keep every parameter that shapes the result set
# ---------------------------------------------------------------------------

_ITEMS_PATH = "/collections/datasets/items"
_BOX = "0,0,10,10"
_INSIDE_WKT = "POLYGON((1 1, 2 1, 2 2, 1 2, 1 1))"
_STRADDLING_WKT = "POLYGON((8 8, 12 8, 12 12, 8 12, 8 8))"


async def _create_linked_dataset(
    session,
    *,
    created_by: uuid.UUID,
    title: str,
    tag: str,
    created_at: date | None = None,
    extent_wkt: str | None = None,
) -> Dataset:
    dataset = await _create_tied_dataset(
        session,
        created_by=created_by,
        name=title,
        keyword_tag=tag,
        fixed_ts=created_at or date(2024, 3, 14),
    )
    if extent_wkt is not None:
        await session.execute(
            update(Record)
            .where(Record.id == dataset.record_id)
            .values(spatial_extent=func.ST_GeomFromText(extent_wkt, 4326))
        )
        await session.commit()
    return dataset


async def _follow_next_links(
    client: AsyncClient, headers: dict, path: str, params: dict
) -> list[dict]:
    """Request the first page, then only ever follow the ``next`` link it returns."""
    response = await client.get(path, params=params, headers=headers)
    pages: list[dict] = []
    while True:
        assert response.status_code == 200, response.text
        body = response.json()
        pages.append(body)
        href = next(
            (link["href"] for link in body["links"] if link["rel"] == "next"), None
        )
        if href is None:
            return pages
        assert len(pages) < 10, "next links never ran out"
        target = urlsplit(href)
        assert target.path.endswith(_ITEMS_PATH)
        response = await client.get(f"{_ITEMS_PATH}?{target.query}", headers=headers)


def _page_titles(pages: list[dict]) -> list[str]:
    return [
        feature["properties"]["title"]
        for page in pages
        for feature in page["features"]
        if feature["properties"].get("type") != "collection"
    ]


@pytest.mark.anyio
async def test_next_links_keep_a_descending_sort(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    tag = f"linkdesc{uuid.uuid4().hex[:8]}"
    for letter in "ABC":
        await _create_linked_dataset(
            test_db_session, created_by=admin_id, title=f"Link {letter} {tag}", tag=tag
        )

    pages = await _follow_next_links(
        client,
        admin_auth_header,
        "/search/datasets/",
        {"q": tag, "sort_by": "name", "sort_desc": "true", "limit": 1},
    )

    assert _page_titles(pages) == [f"Link {letter} {tag}" for letter in "CBA"]


@pytest.mark.anyio
async def test_next_links_keep_an_ascending_override_of_a_descending_default(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """``sort_desc=false`` is a real override, not an absent parameter."""
    admin_id = await get_user_id(test_db_session, "admin")
    tag = f"linkasc{uuid.uuid4().hex[:8]}"
    for day in (1, 2, 3):
        await _create_linked_dataset(
            test_db_session,
            created_by=admin_id,
            title=f"Day {day} {tag}",
            tag=tag,
            created_at=date(2024, 1, day),
        )

    pages = await _follow_next_links(
        client,
        admin_auth_header,
        "/search/datasets/",
        {"q": tag, "sort_by": "date_added", "sort_desc": "false", "limit": 1},
    )

    assert _page_titles(pages) == [f"Day {day} {tag}" for day in (1, 2, 3)]


@pytest.mark.anyio
async def test_next_links_keep_an_ogc_sortby(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    tag = f"linkogc{uuid.uuid4().hex[:8]}"
    for letter in "ABC":
        await _create_linked_dataset(
            test_db_session, created_by=admin_id, title=f"Ogc {letter} {tag}", tag=tag
        )

    pages = await _follow_next_links(
        client,
        admin_auth_header,
        _ITEMS_PATH,
        {"q": tag, "sortby": "-title", "limit": 1},
    )

    assert _page_titles(pages) == [f"Ogc {letter} {tag}" for letter in "CBA"]


@pytest.mark.anyio
async def test_next_links_keep_the_within_predicate(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A ``within`` search must not start admitting overlapping extents on page 2."""
    admin_id = await get_user_id(test_db_session, "admin")
    tag = f"linkwithin{uuid.uuid4().hex[:8]}"
    for title, wkt in (
        (f"A inside {tag}", _INSIDE_WKT),
        (f"B straddling {tag}", _STRADDLING_WKT),
        (f"C inside {tag}", _INSIDE_WKT),
    ):
        await _create_linked_dataset(
            test_db_session,
            created_by=admin_id,
            title=title,
            tag=tag,
            extent_wkt=wkt,
        )

    pages = await _follow_next_links(
        client,
        admin_auth_header,
        "/search/datasets/",
        {
            "q": tag,
            "bbox": _BOX,
            "spatial_predicate": "within",
            "sort_by": "name",
            "limit": 1,
        },
    )

    assert _page_titles(pages) == [f"A inside {tag}", f"C inside {tag}"]
    assert {page["numberMatched"] for page in pages} == {2}


def test_active_pagination_params_cover_every_result_shaping_field():
    """Every query field except the paging cursor must survive into the links."""
    from app.modules.catalog.search.query_params import SearchQueryParams

    non_default = {
        "q": "roads",
        "bbox": _BOX,
        "keywords": ["a"],
        "geometry_type": "Point",
        "srid": 3857,
        "source_organization": "org",
        "record_type": "raster_dataset",
        "date_from": date(2024, 1, 1),
        "date_to": date(2024, 2, 1),
        "vintage_start": date(2020, 1, 1),
        "vintage_end": date(2021, 1, 1),
        "sort_by": "name",
        "sort_desc": False,
        "filter": "title = 'x'",
        "filter-lang": "cql2-json",
        "datetime": "2024-01-01/..",
        "exclude_synthetic": False,
        "spatial_predicate": "within",
        "geometry": '{"type": "Point", "coordinates": [0, 0]}',
        "collection_id": uuid.uuid4(),
    }
    params = SearchQueryParams.model_validate(non_default)

    carried = params.active_pagination_params()

    cursor = {"offset", "limit"}
    shaping = {
        field.alias or name
        for name, field in SearchQueryParams.model_fields.items()
        if name not in cursor
    }
    assert set(non_default) == shaping, "a new query field needs a non-default value"
    assert shaping <= set(carried), shaping - set(carried)
    assert carried["sort_desc"] == "false"
    assert carried["spatial_predicate"] == "within"
