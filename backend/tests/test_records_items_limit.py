"""OGC Records items pages hold at most ``limit`` items, collections included."""

import uuid
from urllib.parse import urlsplit

import pytest
from httpx import AsyncClient

from app.modules.catalog.collections.models import Collection

from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _seed(session, *, datasets: int, collections: int) -> str:
    token = f"zlimit{uuid.uuid4().hex[:8]}"
    admin_id = await get_user_id(session, "admin")
    for i in range(datasets):
        await create_dataset(session, created_by=admin_id, name=f"{token} dataset {i}")
    for i in range(collections):
        session.add(Collection(name=f"{token} collection {i}", created_by=admin_id))
    await session.commit()
    return token


async def _walk(client: AsyncClient, params: dict) -> list[dict]:
    pages: list[dict] = []
    resp = await client.get("/collections/datasets/items", params=params)
    while True:
        assert resp.status_code == 200
        body = resp.json()
        pages.append(body)
        nxt = next((x["href"] for x in body["links"] if x["rel"] == "next"), None)
        if nxt is None:
            return pages
        assert len(pages) < 20, "next links did not terminate"
        parts = urlsplit(nxt)
        resp = await client.get(f"{parts.path}?{parts.query}".replace("/api", "", 1))


@pytest.mark.parametrize("limit", [2, 3, 4])
async def test_text_search_pages_stay_within_limit_and_cover_every_match(
    client: AsyncClient, test_db_session, limit: int
):
    token = await _seed(test_db_session, datasets=4, collections=3)
    pages = await _walk(client, {"q": token, "limit": limit})

    ids = [f["id"] for p in pages for f in p["features"]]
    assert all(len(p["features"]) <= limit for p in pages)
    assert all(p["numberReturned"] == len(p["features"]) for p in pages)
    assert len(ids) == len(set(ids)) == 7
    assert {p["numberMatched"] for p in pages} == {7}


async def test_explicit_collection_type_pages_stay_within_limit(
    client: AsyncClient, test_db_session
):
    token = await _seed(test_db_session, datasets=3, collections=4)
    pages = await _walk(client, {"q": token, "limit": 2, "type": "dataset,collection"})

    ids = [f["id"] for p in pages for f in p["features"]]
    assert all(len(p["features"]) <= 2 for p in pages)
    assert len(ids) == len(set(ids)) == 7
    assert {p["numberMatched"] for p in pages} == {7}


async def test_text_search_surfaces_at_most_five_collections(
    client: AsyncClient, test_db_session
):
    token = await _seed(test_db_session, datasets=1, collections=7)
    pages = await _walk(client, {"q": token, "limit": 3})

    ids = [f["id"] for p in pages for f in p["features"]]
    assert all(len(p["features"]) <= 3 for p in pages)
    assert len(ids) == len(set(ids)) == 6
    assert {p["numberMatched"] for p in pages} == {6}


async def test_catalog_search_keeps_matching_collections_on_its_first_page(
    client: AsyncClient, test_db_session
):
    token = await _seed(test_db_session, datasets=4, collections=2)
    resp = await client.get("/search/datasets/", params={"q": token, "limit": 2})

    assert resp.status_code == 200
    types = [f["properties"]["record_type"] for f in resp.json()["features"]]
    assert types.count("collection") == 2


async def test_records_and_catalog_search_keep_separate_cached_pages(
    client: AsyncClient, test_db_session
):
    native_first = await _seed(test_db_session, datasets=4, collections=2)
    params = {"q": native_first, "limit": 2}
    await client.get("/search/datasets/", params=params)
    records = (await client.get("/collections/datasets/items", params=params)).json()
    assert len(records["features"]) <= 2

    records_first = await _seed(test_db_session, datasets=4, collections=2)
    params = {"q": records_first, "limit": 2}
    await client.get("/collections/datasets/items", params=params)
    native = (await client.get("/search/datasets/", params=params)).json()
    types = [f["properties"]["record_type"] for f in native["features"]]
    assert types.count("collection") == 2


async def test_catalog_search_links_page_the_catalog_search(
    client: AsyncClient, test_db_session
):
    token = await _seed(test_db_session, datasets=3, collections=1)
    first = (
        await client.get("/search/datasets/", params={"q": token, "limit": 2})
    ).json()
    nxt = next(x["href"] for x in first["links"] if x["rel"] == "next")
    parts = urlsplit(nxt)
    assert parts.path.endswith("/search/datasets/")

    second = (
        await client.get(f"{parts.path}?{parts.query}".replace("/api", "", 1))
    ).json()
    first_ids = {f["id"] for f in first["features"]}
    assert not first_ids & {f["id"] for f in second["features"]}
