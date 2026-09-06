"""Integration tests for /search/facets endpoint and facet counting."""

import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select, text, update

from app.core.db.models import AppSetting
from app.core.persistent_config import EMBEDDING_MODEL, SEMANTIC_SEARCH_ENABLED
from app.modules.catalog.collections.models import Collection
from app.modules.catalog.datasets.domain.models import Dataset, Record, RecordKeyword
from app.processing.embeddings import helpers as embedding_helpers
from app.processing.embeddings.models import RecordEmbedding

from tests.factories import get_user_id

# Vector band this file owns; the other search suites use 40, 70, 90 and 800+.
_BAND_LO = 130
_SEMANTIC_ONLY_QUERY = "zzznolexicalfacetsxyz"


# ---------------------------------------------------------------------------
# Helpers (duplicated from test_search.py for isolation)
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
) -> Dataset:
    """Insert a Record + Dataset pair."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=description or f"Description for {name}",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
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
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def facet_datasets(test_db_session):
    """Create datasets with different record types for facet tests."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    vector_ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Vector Parks Facet",
        keywords=["parks"],
        description="Vector park boundaries for facet testing",
    )

    raster_ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Raster Elevation Facet",
        description="Raster elevation model for facet testing",
    )
    # Update record_type to raster_dataset
    await session.execute(
        update(Record)
        .where(Record.id == raster_ds.record_id)
        .values(record_type="raster_dataset")
    )

    vrt_ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="VRT Mosaic Facet",
        description="VRT mosaic dataset for facet testing",
    )
    # Update record_type to vrt_dataset
    await session.execute(
        update(Record)
        .where(Record.id == vrt_ds.record_id)
        .values(record_type="vrt_dataset")
    )

    await session.commit()

    return {"vector": vector_ds, "raster": raster_ds, "vrt": vrt_ds}


# ---------------------------------------------------------------------------
# Facet endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_facets_returns_all_types(
    client: AsyncClient,
    admin_auth_header: dict,
    facet_datasets: dict,
):
    """GET /search/facets returns counts for all record types present."""
    resp = await client.get(
        "/search/facets/",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "record_type" in data
    counts = data["record_type"]
    assert counts.get("vector_dataset", 0) >= 1
    assert counts.get("raster_dataset", 0) >= 1
    assert counts.get("vrt_dataset", 0) >= 1


@pytest.mark.anyio
async def test_facets_with_text_filter(
    client: AsyncClient,
    admin_auth_header: dict,
    facet_datasets: dict,
):
    """GET /search/facets/?q=Parks filters counts to matching datasets."""
    resp = await client.get(
        "/search/facets/",
        params={"q": "Vector Parks Facet"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    counts = data["record_type"]
    assert counts.get("vector_dataset", 0) >= 1
    # Raster and VRT should not match the text "Vector Parks Facet"
    assert counts.get("raster_dataset", 0) == 0
    assert counts.get("vrt_dataset", 0) == 0


@pytest.mark.anyio
async def test_facets_with_srid_filter(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """GET /search/facets/?srid=3857 returns only datasets with that SRID."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    # Create dataset with SRID 3857
    await _create_search_dataset(
        session,
        created_by=admin_id,
        name="SRID3857 Facet Dataset",
        srid=3857,
        description="Dataset with SRID 3857 for facet test",
    )

    resp = await client.get(
        "/search/facets/",
        params={"srid": 3857},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    counts = data["record_type"]
    assert counts.get("vector_dataset", 0) >= 1
    # Count should be smaller than unfiltered total
    resp_all = await client.get(
        "/search/facets/",
        headers=admin_auth_header,
    )
    all_counts = resp_all.json()["record_type"]
    total_filtered = sum(counts.values())
    total_all = sum(all_counts.values())
    assert total_filtered <= total_all


@pytest.mark.anyio
async def test_facets_excludes_dead_collection_record_type(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """A4 (#315 follow-up): the record_type facet must NOT advertise a 'collection'
    value. Collections live in the separate Collection table, not as Record rows
    with record_type='collection', so ?record_type=collection always returns 0 --
    a dead facet value. Collections are surfaced via the 'collections' facet instead.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    # Create a collection
    coll = Collection(
        name="Test Facet Collection",
        description="A collection for facet count testing",
        created_by=admin_id,
    )
    session.add(coll)
    await session.commit()

    resp = await client.get(
        "/search/facets/",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    counts = data["record_type"]
    assert "collection" not in counts, (
        "record_type facet must not advertise the unfilterable 'collection' value"
    )
    # Collections are exposed via the dedicated 'collections' facet group.
    assert "collections" in data


@pytest.mark.anyio
async def test_facets_returns_keyword_groups(
    client: AsyncClient,
    admin_auth_header: dict,
    facet_datasets: dict,
):
    """GET /search/facets returns keywords, source_organization, srid groups."""
    resp = await client.get("/search/facets/", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "record_type" in data
    assert "keywords" in data
    assert "source_organization" in data
    assert "srid" in data
    # keywords should be list of {value, count}
    assert isinstance(data["keywords"], list)
    if len(data["keywords"]) > 0:
        assert "value" in data["keywords"][0]
        assert "count" in data["keywords"][0]
    # srid should be list of {value, count}
    assert isinstance(data["srid"], list)
    if len(data["srid"]) > 0:
        assert "value" in data["srid"][0]
        assert "count" in data["srid"][0]


# ---------------------------------------------------------------------------
# fix(#1855): facet counts are taken over the results' candidate set
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_has_embeddings_cache():
    """The 30 s has_embeddings cache must not carry a False from an earlier test."""
    embedding_helpers._has_embeddings_cache.clear()
    yield
    embedding_helpers._has_embeddings_cache.clear()


async def _embedding_dim(session) -> int:
    result = await session.execute(
        text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'catalog.record_embeddings'::regclass "
            "AND attname = 'embedding'"
        )
    )
    dim = result.scalar_one_or_none()
    return dim if dim and dim > 0 else 1536


def _band_vector(base_value: float, dim: int) -> list[float]:
    """Unit vector with its signal in dims [_BAND_LO, _BAND_LO + 10), zeros elsewhere."""
    vec = [0.0] * dim
    for i in range(_BAND_LO, _BAND_LO + 10):
        vec[i] = base_value + ((i - _BAND_LO) * 0.01)
    magnitude = sum(v * v for v in vec) ** 0.5
    return [v / magnitude for v in vec]


async def _set_semantic_search(session, enabled: bool) -> None:
    result = await session.execute(
        select(AppSetting).where(AppSetting.key == "semantic_search_enabled")
    )
    existing = result.scalar_one_or_none()
    if existing is None:
        session.add(AppSetting(key="semantic_search_enabled", value={"v": enabled}))
    else:
        existing.value = {"v": enabled}
    await session.commit()

    from app.platform.cache import get_cache

    try:
        await get_cache().delete("config:semantic_search_enabled")
    except RuntimeError:
        pass


async def _embed(session, dataset: Dataset, vector: list[float]) -> None:
    session.add(
        RecordEmbedding(
            record_id=dataset.record_id,
            embedding=vector,
            model_name=await EMBEDDING_MODEL.get(session),
            content_hash=uuid.uuid4().hex[:64],
        )
    )
    await session.commit()


@pytest.fixture
async def semantic_facet_datasets(test_db_session) -> dict:
    """Three datasets a band query matches by meaning only: two vector, one raster.

    Their titles share no word with ``_SEMANTIC_ONLY_QUERY``, so whatever the
    facets count for that query is the vector arm and nothing else. The
    embeddings are deleted on teardown so the band holds one test's rows at a
    time; ``slug`` keeps the titles unique for the lexical control.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    dim = await _embedding_dim(session)
    slug = f"zq{uuid.uuid4().hex[:8]}"
    datasets = []
    for index, (name, record_type) in enumerate(
        (
            (f"Zqfacet Alpha {slug}", "vector_dataset"),
            (f"Zqfacet Beta {slug}", "vector_dataset"),
            (f"Zqfacet Gamma {slug}", "raster_dataset"),
        )
    ):
        ds = await _create_search_dataset(
            session,
            created_by=admin_id,
            name=name,
            keywords=[f"zqfacetband{index}"],
            description="matched by meaning rather than by its words",
        )
        if record_type != "vector_dataset":
            await session.execute(
                update(Record)
                .where(Record.id == ds.record_id)
                .values(record_type=record_type)
            )
            await session.commit()
        await _embed(session, ds, _band_vector(0.99 - index * 0.02, dim))
        datasets.append(ds)
    previous = await SEMANTIC_SEARCH_ENABLED.get(session)
    await _set_semantic_search(session, True)
    yield {
        "datasets": datasets,
        "slug": slug,
        "dim": dim,
        "query_vector": _band_vector(1.0, dim),
    }
    await session.execute(
        text("DELETE FROM catalog.record_embeddings WHERE record_id = ANY(:ids)"),
        {"ids": [ds.record_id for ds in datasets]},
    )
    await session.commit()
    await _set_semantic_search(session, previous)


def _patched_embedding(vector: list[float]):
    return patch(
        "app.modules.catalog.search.service_semantic.generate_embedding",
        new_callable=AsyncMock,
        return_value=vector,
    )


@pytest.mark.anyio
async def test_facets_count_the_semantic_candidate_set(
    client: AsyncClient,
    admin_auth_header: dict,
    semantic_facet_datasets: dict,
):
    """fix(#1855): with semantic mode on, facets count what the results return.

    The query matches nothing lexically, so on the lexical-only facets this
    read record_type {} beside three results.
    """
    with _patched_embedding(semantic_facet_datasets["query_vector"]):
        results = await client.get(
            "/search/datasets/",
            params={"q": _SEMANTIC_ONLY_QUERY},
            headers=admin_auth_header,
        )
        facets = await client.get(
            "/search/facets/",
            params={"q": _SEMANTIC_ONLY_QUERY},
            headers=admin_auth_header,
        )
    assert results.status_code == 200
    assert facets.status_code == 200

    body = results.json()
    titles = {f["properties"]["title"] for f in body["features"]}
    slug = semantic_facet_datasets["slug"]
    # Non-vacuity: the vector arm ran and the results are the three band records.
    assert titles == {f"Zqfacet {n} {slug}" for n in ("Alpha", "Beta", "Gamma")}
    assert body["numberMatched"] == 3

    payload = facets.json()
    assert payload["record_type"] == {"vector_dataset": 2, "raster_dataset": 1}
    assert sum(payload["record_type"].values()) == body["numberMatched"]
    assert {k["value"] for k in payload["keywords"]} == {
        "zqfacetband0",
        "zqfacetband1",
        "zqfacetband2",
    }


@pytest.mark.anyio
async def test_facets_count_the_lexical_candidate_set(
    client: AsyncClient,
    admin_auth_header: dict,
    semantic_facet_datasets: dict,
    test_db_session,
):
    """Control: with semantic search off both endpoints are lexical and agree."""
    lexical_q = f"Zqfacet Alpha {semantic_facet_datasets['slug']}"
    await _set_semantic_search(test_db_session, False)
    try:
        with _patched_embedding(semantic_facet_datasets["query_vector"]) as embed:
            results = await client.get(
                "/search/datasets/",
                params={"q": lexical_q},
                headers=admin_auth_header,
            )
            facets = await client.get(
                "/search/facets/",
                params={"q": lexical_q},
                headers=admin_auth_header,
            )
        embed.assert_not_called()
    finally:
        await _set_semantic_search(test_db_session, True)

    assert results.status_code == 200
    assert facets.status_code == 200
    body = results.json()
    assert {f["properties"]["title"] for f in body["features"]} == {lexical_q}
    counts = facets.json()["record_type"]
    assert counts == {"vector_dataset": 1}
    assert sum(counts.values()) == body["numberMatched"] == 1


@pytest.mark.anyio
async def test_facets_semantic_candidates_keep_the_visibility_filter(
    client: AsyncClient,
    semantic_facet_datasets: dict,
    test_db_session,
):
    """Rule 1: a private record the vector arm would match is not counted for anon."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    slug = semantic_facet_datasets["slug"]
    private_ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name=f"Zqfacet Private Delta {slug}",
        visibility="private",
        description="nearest to the query, visible to its owner only",
    )
    await _embed(
        session, private_ds, _band_vector(0.999, semantic_facet_datasets["dim"])
    )
    try:
        with _patched_embedding(semantic_facet_datasets["query_vector"]):
            # The slug keeps this anonymous (cacheable) request off any earlier key.
            facets = await client.get(
                "/search/facets/", params={"q": f"{_SEMANTIC_ONLY_QUERY} {slug}"}
            )
    finally:
        await session.execute(
            text("DELETE FROM catalog.record_embeddings WHERE record_id = :rid"),
            {"rid": private_ds.record_id},
        )
        await session.commit()
    assert facets.status_code == 200
    assert facets.json()["record_type"] == {"vector_dataset": 2, "raster_dataset": 1}


@contextmanager
def _count_cosine_scans():
    """Count executed statements carrying pgvector's cosine operator (``<=>``).

    Listens on the engine the API client runs against; every statement that
    evaluates a cosine distance is one scan over the embeddings table.
    """
    import app.core.db as db_module

    seen: list[str] = []

    def _before(_conn, _cursor, statement, *_args):
        if "<=>" in statement:
            seen.append(statement)

    sync_engine = db_module.engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before)
    try:
        yield seen
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)


@pytest.mark.anyio
async def test_facets_scan_the_embeddings_once_per_request(
    client: AsyncClient,
    admin_auth_header: dict,
    semantic_facet_datasets: dict,
):
    """fix(#1855): one cosine scan per facets request, whatever the facet count.

    The candidate CTE feeds five separately executed aggregates, so a cosine
    subquery inside it ran once per aggregate; the vector arm is materialised
    once and the aggregates see a list of ids.
    """
    with (
        _patched_embedding(semantic_facet_datasets["query_vector"]),
        _count_cosine_scans() as scans,
    ):
        facets = await client.get(
            "/search/facets/",
            params={"q": _SEMANTIC_ONLY_QUERY},
            headers=admin_auth_header,
        )
    assert facets.status_code == 200
    # Non-vacuity: the vector arm ran, so the counts are over the band records.
    assert facets.json()["record_type"] == {"vector_dataset": 2, "raster_dataset": 1}
    assert len(scans) == 1, (
        f"expected one cosine scan per facets request, got {len(scans)}"
    )
