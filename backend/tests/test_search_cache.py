"""Integration tests for anonymous search-response caching (PERF-2, PERF-7).

Covers ``/search/datasets/`` (PERF-2) and ``/search/facets/`` (PERF-7):
the anon path returns a cached payload on the second request within the TTL,
and the authenticated path bypasses the cache.

Cache assertions use the "mutate the DB between calls" pattern: if the second
request is a cache hit, the response equals the FIRST response (stale); if it
bypasses the cache, the second response reflects the mutation (live).
"""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import func, update

from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordKeyword,
)
from app.platform.cache import get_cache

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _reset_search_cache(client: AsyncClient):
    """Flush the search cache before and after each test.

    The in-memory cache provider (``InMemoryCacheProvider``) is a session-scoped
    singleton (``tests/conftest.py:174``), so without this fixture cached
    responses leak between tests in the same module. Both endpoints share the
    ``catalog:search:*`` namespace.

    Depending on ``client`` ensures ``init_cache()`` has been called before we
    flush — the session-scoped client fixture is what initializes the provider.
    """
    await get_cache().delete_pattern("catalog:search:*")
    yield
    await get_cache().delete_pattern("catalog:search:*")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_search_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    keywords: list[str] | None = None,
    geometry_type: str = "MultiPolygon",
    srid: int = 4326,
    visibility: str = "public",
    description: str | None = None,
    extent_wkt: str | None = None,
    data_vintage_start: date | None = None,
    data_vintage_end: date | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair (mirrors ``tests/test_search.py``)."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=description or f"Description for {name}",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
        temporal_start=data_vintage_start,
        temporal_end=data_vintage_end,
    )
    session.add(record)
    await session.flush()

    for kw in keywords or []:
        session.add(
            RecordKeyword(record_id=record.id, keyword=kw, keyword_type="theme")
        )

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=srid,
        geometry_type=geometry_type,
        feature_count=100,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()

    if extent_wkt:
        await session.execute(
            update(Record)
            .where(Record.id == record.id)
            .values(spatial_extent=func.ST_GeomFromText(extent_wkt, 4326))
        )

    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# /search/datasets/ — PERF-2
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_anon_search_caches_response(
    client: AsyncClient,
    test_db_session,
):
    """Anon GET /search/datasets/ returns the cached payload on the second call.

    Mutating the DB between the two anon calls must NOT change the second
    response — proving the second request is served from cache.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    slug = f"cachetest_{uuid.uuid4().hex[:8]}"

    # Seed one matching dataset before the first call.
    await _create_search_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"{slug} initial",
        description=f"{slug} dataset one",
    )

    first = await client.get("/search/datasets/", params={"q": slug})
    assert first.status_code == 200
    first_matched = first.json()["numberMatched"]
    assert first_matched >= 1, "expected the seeded dataset to match"

    # Mutate the DB: insert a second matching dataset between calls.
    await _create_search_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"{slug} second",
        description=f"{slug} dataset two",
    )

    second = await client.get("/search/datasets/", params={"q": slug})
    assert second.status_code == 200
    second_matched = second.json()["numberMatched"]

    # Cache hit: second response should be byte-for-byte the first (stale).
    assert (
        second_matched == first_matched
    ), "anon second request should return cached (stale) numberMatched"


@pytest.mark.anyio
async def test_authed_search_bypasses_cache(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Authenticated GET /search/datasets/ must bypass the cache.

    Mutating the DB between two authenticated calls MUST change the second
    response — proving authed requests run live.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    slug = f"cachetest_{uuid.uuid4().hex[:8]}"

    await _create_search_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"{slug} initial",
        description=f"{slug} authed dataset one",
    )

    first = await client.get(
        "/search/datasets/", params={"q": slug}, headers=admin_auth_header
    )
    assert first.status_code == 200
    first_matched = first.json()["numberMatched"]
    assert first_matched >= 1

    await _create_search_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"{slug} second",
        description=f"{slug} authed dataset two",
    )

    second = await client.get(
        "/search/datasets/", params={"q": slug}, headers=admin_auth_header
    )
    assert second.status_code == 200
    second_matched = second.json()["numberMatched"]

    assert (
        second_matched == first_matched + 1
    ), "authed second request should reflect DB mutation (cache bypass)"


# ---------------------------------------------------------------------------
# /search/facets/ — PERF-7
# ---------------------------------------------------------------------------


def _record_type_total(payload: dict) -> int:
    """Sum the record_type facet bucket counts in a FacetCountResponse."""
    record_type = payload.get("record_type") or {}
    return sum(int(v) for v in record_type.values())


@pytest.mark.anyio
async def test_anon_facets_caches_response(
    client: AsyncClient,
    test_db_session,
):
    """Anon GET /search/facets/ returns the cached payload on the second call.

    Mutating the DB between two anon calls must NOT change the second response —
    proving the second request is served from cache.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    slug = f"facettest_{uuid.uuid4().hex[:8]}"

    await _create_search_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"{slug} initial",
        description=f"{slug} facet dataset one",
    )

    first = await client.get("/search/facets/", params={"q": slug})
    assert first.status_code == 200
    first_total = _record_type_total(first.json())
    assert first_total >= 1, "expected the seeded dataset to be counted"

    await _create_search_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"{slug} second",
        description=f"{slug} facet dataset two",
    )

    second = await client.get("/search/facets/", params={"q": slug})
    assert second.status_code == 200
    second_total = _record_type_total(second.json())

    assert (
        second_total == first_total
    ), "anon second request should return cached (stale) facet totals"


@pytest.mark.anyio
async def test_authed_facets_bypasses_cache(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Authenticated GET /search/facets/ must bypass the cache.

    Mutating the DB between two authenticated calls MUST change the second
    response — proving authed requests run live.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    slug = f"facettest_{uuid.uuid4().hex[:8]}"

    await _create_search_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"{slug} initial",
        description=f"{slug} authed facet dataset one",
    )

    first = await client.get(
        "/search/facets/", params={"q": slug}, headers=admin_auth_header
    )
    assert first.status_code == 200
    first_total = _record_type_total(first.json())
    assert first_total >= 1

    await _create_search_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"{slug} second",
        description=f"{slug} authed facet dataset two",
    )

    second = await client.get(
        "/search/facets/", params={"q": slug}, headers=admin_auth_header
    )
    assert second.status_code == 200
    second_total = _record_type_total(second.json())

    assert (
        second_total == first_total + 1
    ), "authed second request should reflect DB mutation (cache bypass)"
