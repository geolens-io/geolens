"""`startindex` pages an OGC items collection exactly as `offset` does."""

from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.factories import get_user_id
from tests.test_ogc_features import _cleanup_table, _create_test_table_and_dataset

pytestmark = pytest.mark.anyio

# Feature i sits at (-74 + 0.01 i, 40.7 + 0.01 i) with gid i + 1, so this box
# holds features 2..10: gids 3..11.
_BBOX = "-73.985,40.705,-73.895,40.805"
_IN_BBOX = list(range(3, 12))


@pytest.fixture
async def points(test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session, created_by=admin_id, with_features=12
    )
    yield dataset
    await _cleanup_table(test_db_session, dataset.table_name)


def _ids(data: dict) -> list[int]:
    return [feature["id"] for feature in data["features"]]


def _link_query(data: dict, rel: str) -> dict[str, list[str]] | None:
    for link in data["links"]:
        if link["rel"] == rel:
            return parse_qs(urlparse(link["href"]).query)
    return None


async def test_startindex_returns_the_same_page_as_offset(
    client: AsyncClient, points
) -> None:
    url = f"/collections/{points.id}/items"

    by_offset = await client.get(url, params={"limit": 3, "offset": 3})
    by_startindex = await client.get(url, params={"limit": 3, "startindex": 3})

    assert by_startindex.status_code == 200, by_startindex.text
    assert _ids(by_startindex.json()) == _ids(by_offset.json()) == [4, 5, 6]


@pytest.mark.parametrize("limit", [2, 3])
async def test_paging_a_bbox_by_startindex_visits_every_feature_once(
    client: AsyncClient, points, limit: int
) -> None:
    """Page the way ArcGIS does: advance startindex by limit while pages are full."""
    url = f"/collections/{points.id}/items"
    seen: list[int] = []
    start = 0
    while True:
        params = {"bbox": _BBOX, "limit": limit}
        if start:
            params["startindex"] = start
        resp = await client.get(url, params=params)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        seen.extend(_ids(data))
        if data["numberReturned"] < limit or _link_query(data, "next") is None:
            break
        start += limit
        assert start <= len(_IN_BBOX), "paging did not stop"

    assert seen == _IN_BBOX
    assert data["numberMatched"] == len(_IN_BBOX)


@pytest.mark.parametrize("startindex", [len(_IN_BBOX), 1_000])
async def test_a_startindex_past_the_end_returns_an_empty_last_page(
    client: AsyncClient, points, startindex: int
) -> None:
    """ArcGIS pages on while a page is full and has a next link; this page ends it."""
    resp = await client.get(
        f"/collections/{points.id}/items",
        params={"bbox": _BBOX, "limit": 3, "startindex": startindex},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["features"] == []
    assert data["numberReturned"] == 0
    assert data["numberMatched"] == len(_IN_BBOX)
    assert _link_query(data, "next") is None


async def test_a_column_named_startindex_is_filtered_with_cql2(
    client: AsyncClient, points, test_db_session
) -> None:
    table = f"data.{points.table_name}"
    await test_db_session.execute(
        text(f"ALTER TABLE {table} ADD COLUMN startindex integer")
    )
    await test_db_session.execute(text(f"UPDATE {table} SET startindex = gid * 10"))
    await test_db_session.commit()
    url = f"/collections/{points.id}/items"

    filtered = await client.get(url, params={"filter": "startindex = 30"})
    paged = await client.get(url, params={"limit": 2, "startindex": 3})

    assert filtered.status_code == 200, filtered.text
    assert _ids(filtered.json()) == [3]
    assert paged.status_code == 200, paged.text
    assert _ids(paged.json()) == [4, 5]


async def test_startindex_and_a_different_offset_are_refused(
    client: AsyncClient, points
) -> None:
    resp = await client.get(
        f"/collections/{points.id}/items",
        params={"limit": 3, "offset": 2, "startindex": 3},
    )

    assert resp.status_code == 400


@pytest.mark.parametrize("offset", [0, 3], ids=["default", "equal"])
async def test_startindex_with_a_default_or_equal_offset_is_accepted(
    client: AsyncClient, points, offset: int
) -> None:
    resp = await client.get(
        f"/collections/{points.id}/items",
        params={"limit": 3, "offset": offset, "startindex": 3},
    )

    assert resp.status_code == 200, resp.text
    assert _ids(resp.json()) == [4, 5, 6]


async def test_links_carry_startindex_as_offset_and_never_echo_it(
    client: AsyncClient, points
) -> None:
    resp = await client.get(
        f"/collections/{points.id}/items",
        params={"bbox": _BBOX, "limit": 2, "startindex": 4},
    )

    data = resp.json()
    assert _ids(data) == _IN_BBOX[4:6]
    self_query = _link_query(data, "self")
    assert self_query["offset"] == ["4"]
    assert _link_query(data, "prev")["offset"] == ["2"]
    assert _link_query(data, "next")["after_gid"] == [str(_IN_BBOX[5])]
    for link in data["links"]:
        assert "startindex" not in parse_qs(urlparse(link["href"]).query)
