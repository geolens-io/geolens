"""An OGC items page ends, with a keyset `next` link, once its geometries reach the stored-bytes budget."""

from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import text

import app.standards.ogc.router as ogc_router
from tests.factories import get_user_id
from tests.test_ogc_features import _cleanup_table, _create_test_table_and_dataset

pytestmark = pytest.mark.anyio

# Buffer quad_segs per row, so stored sizes differ; None stores a NULL geometry.
_ROWS = [1, None, 2, None, None, 3, 4, None, 5, 6, 7, 8]
_BBOX = "-75,40,-73,42"


@pytest.fixture
async def polygons(test_db_session):
    """A public dataset of buffered points with known stored sizes, in gid order."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session,
        created_by=admin_id,
        geometry_type="POLYGON",
    )
    table = f"data.{dataset.table_name}"
    for i, quad_segs in enumerate(_ROWS):
        geom = (
            "NULL"
            if quad_segs is None
            else f"ST_Buffer(ST_SetSRID(ST_MakePoint(-74 + {i} * 0.01, 41), 4326), "
            f"0.001, {quad_segs})"
        )
        await test_db_session.execute(
            text(f"INSERT INTO {table} (geom_4326, name) VALUES ({geom}, :name)"),
            {"name": f"feature {i}"},
        )
    counted = await test_db_session.execute(
        text(
            f"SELECT gid, COALESCE(pg_column_size(geom_4326), 0) FROM {table} ORDER BY gid"
        )
    )
    sizes = [(gid, n) for gid, n in counted.all()]
    dataset.feature_count = len(sizes)
    await test_db_session.commit()
    yield dataset, sizes
    await _cleanup_table(test_db_session, dataset.table_name)


def _first_page(sizes: list[tuple[int, int]], budget: int, limit: int) -> list[int]:
    """The gids a page holds: rows while the bytes before each stay under budget."""
    kept, before = [], 0
    for gid, n in sizes[:limit]:
        if before >= budget:
            break
        kept.append(gid)
        before += n
    return kept


def _two_polygons(sizes: list[tuple[int, int]]) -> int:
    """A budget the first two polygons stay under, so the page ends at the third."""
    first, second = [n for _, n in sizes if n][:2]
    return first + second + 1


def _next(data: dict) -> str | None:
    for link in data["links"]:
        if link["rel"] == "next":
            parsed = urlparse(link["href"])
            return f"{parsed.path.removeprefix('/api')}?{parsed.query}"
    return None


async def _walk(client: AsyncClient, url: str, params: dict) -> list[list[int]]:
    pages = []
    resp = await client.get(url, params=params)
    while True:
        assert resp.status_code == 200, resp.text
        data = resp.json()
        ids = [feature["id"] for feature in data["features"]]
        assert data["numberReturned"] == len(ids)
        pages.append(ids)
        following = _next(data)
        if following is None:
            return pages
        assert len(pages) <= len(_ROWS), "the walk did not finish"
        resp = await client.get(following)


async def test_a_page_ends_at_the_row_that_reaches_the_budget(
    client: AsyncClient, polygons, monkeypatch
) -> None:
    dataset, sizes = polygons
    budget = _two_polygons(sizes)
    monkeypatch.setattr(ogc_router, "_ITEMS_PAGE_MAX_GEOMETRY_BYTES", budget)
    expected = _first_page(sizes, budget, 100)
    assert 1 < len(expected) < len(sizes)

    resp = await client.get(f"/collections/{dataset.id}/items", params={"limit": 100})

    data = resp.json()
    assert [feature["id"] for feature in data["features"]] == expected
    assert data["numberReturned"] == len(expected)
    assert data["numberMatched"] == len(sizes)
    following = parse_qs(urlparse(_next(data)).query)
    assert following["after_gid"] == [str(expected[-1])]
    assert following["limit"] == ["100"]


@pytest.mark.parametrize(
    "start",
    [{"bbox": _BBOX}, {"bbox": _BBOX, "after_gid": 0}],
    ids=["offset", "keyset"],
)
async def test_walking_next_returns_every_feature_once(
    client: AsyncClient, polygons, monkeypatch, start
) -> None:
    dataset, sizes = polygons
    monkeypatch.setattr(
        ogc_router, "_ITEMS_PAGE_MAX_GEOMETRY_BYTES", _two_polygons(sizes)
    )
    with_geometry = [gid for gid, n in sizes if n]

    pages = await _walk(
        client, f"/collections/{dataset.id}/items", {"limit": 100, **start}
    )

    assert [gid for page in pages for gid in page] == with_geometry
    assert len(pages) > 1


async def test_a_feature_larger_than_the_budget_is_served_alone(
    client: AsyncClient, polygons, monkeypatch
) -> None:
    dataset, sizes = polygons
    monkeypatch.setattr(ogc_router, "_ITEMS_PAGE_MAX_GEOMETRY_BYTES", 1)

    pages = await _walk(client, f"/collections/{dataset.id}/items", {"limit": 100})

    assert [gid for page in pages for gid in page] == [gid for gid, _ in sizes]
    # Each page ends at its first polygon, so a NULL geometry opens the next page.
    expected, current = [], []
    for gid, n in sizes:
        current.append(gid)
        if n:
            expected.append(current)
            current = []
    assert pages == expected


async def test_null_geometries_count_as_no_bytes(
    client: AsyncClient, polygons, monkeypatch
) -> None:
    dataset, sizes = polygons
    first_null = next(i for i, (_, n) in enumerate(sizes) if n == 0)
    budget = sizes[first_null + 1][1] + 1
    monkeypatch.setattr(ogc_router, "_ITEMS_PAGE_MAX_GEOMETRY_BYTES", budget)

    resp = await client.get(
        f"/collections/{dataset.id}/items",
        params={"limit": 100, "after_gid": sizes[first_null - 1][0]},
    )

    ids = [feature["id"] for feature in resp.json()["features"]]
    assert ids == _first_page(sizes[first_null:], budget, 100)
    assert sum(1 for gid, n in sizes if gid in ids and n == 0) > 1


async def test_a_page_under_the_budget_is_unchanged(
    client: AsyncClient, polygons, monkeypatch
) -> None:
    dataset, sizes = polygons
    url = f"/collections/{dataset.id}/items"

    budgeted = await client.get(url, params={"limit": 4, "bbox": _BBOX})
    monkeypatch.setattr(ogc_router, "_ITEMS_PAGE_MAX_GEOMETRY_BYTES", None)
    unbudgeted = await client.get(url, params={"limit": 4, "bbox": _BBOX})

    with_budget, without_budget = budgeted.json(), unbudgeted.json()
    with_budget.pop("timeStamp")
    without_budget.pop("timeStamp")
    assert with_budget == without_budget
    assert with_budget["numberReturned"] == 4
    assert _next(with_budget) is not None
