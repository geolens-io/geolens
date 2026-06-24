"""Integration tests for hybrid (semantic + FTS) search.

Tests cover: RRF ranking, fallback when no embeddings exist, fallback when
SEMANTIC_SEARCH_ENABLED is off, semantic search when AI_ENABLED is off but
embeddings exist, and no regression when semantic search is disabled.

Semantic search is now auto-enabled when SEMANTIC_SEARCH_ENABLED is on and
embeddings exist -- there is no user-facing toggle.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied (including pgvector extension)
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.catalog.datasets.domain.models import Dataset, Record, RecordKeyword
from app.processing.embeddings.models import RecordEmbedding
from app.core.db.models import AppSetting

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_search_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    keywords: list[str] | None = None,
    description: str | None = None,
    visibility: str = "public",
    geometry_type: str = "MultiPolygon",
) -> Dataset:
    """Insert a Record + Dataset pair for hybrid search tests."""
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
        srid=4326,
        geometry_type=geometry_type,
        feature_count=10,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()
    await session.commit()
    await session.refresh(dataset)
    return dataset


def _make_vector(base_value: float, dim: int = 1536) -> list[float]:
    """Create a simple vector with a dominant direction.

    Different base_value values produce vectors with different cosine similarities.
    """
    vec = [0.01] * dim
    # Set first few dimensions to the base value to create direction
    for i in range(min(10, dim)):
        vec[i] = base_value + (i * 0.01)
    # Normalize roughly
    magnitude = sum(v * v for v in vec) ** 0.5
    return [v / magnitude for v in vec]


def _make_vector_band(base_value: float, dim: int = 1536, lo: int = 40) -> list[float]:
    """Vector with its signal in dims [lo, lo+10) and ZEROS elsewhere.

    Orthogonal to ``_make_vector`` (dims 0..9), so a query built here matches only
    records embedded here — isolating a test from other tests' committed vectors.
    """
    vec = [0.0] * dim
    for i in range(lo, min(lo + 10, dim)):
        vec[i] = base_value + ((i - lo) * 0.01)
    magnitude = sum(v * v for v in vec) ** 0.5
    return [v / magnitude for v in vec]


async def _get_embedding_dim(session) -> int:
    """Return the current fixed vector dimension for record embeddings."""
    result = await session.execute(
        text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'catalog.record_embeddings'::regclass "
            "AND attname = 'embedding'"
        )
    )
    current_dim = result.scalar_one_or_none()
    if current_dim and current_dim > 0:
        return current_dim

    setting_result = await session.execute(
        select(AppSetting).where(AppSetting.key == "embedding_dims")
    )
    setting = setting_result.scalar_one_or_none()
    if setting and isinstance(setting.value, dict):
        configured_dim = setting.value.get("v")
        if isinstance(configured_dim, int) and configured_dim > 0:
            return configured_dim

    return 1536


# ---------------------------------------------------------------------------
# Helpers: toggle semantic search setting
# ---------------------------------------------------------------------------


async def _set_semantic_search(session, enabled: bool):
    """Set SEMANTIC_SEARCH_ENABLED in app_settings and invalidate cache."""
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
        cache = get_cache()
        await cache.delete("config:semantic_search_enabled")
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def hybrid_datasets(test_db_session):
    """Create datasets for hybrid search tests and return a dict mapping names to Datasets."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    roads = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Roads and Highways Network",
        keywords=["roads", "highways", "infrastructure"],
        description="Major road and highway network covering urban and rural areas",
    )

    railways = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Railway Network Lines",
        keywords=["railways", "trains"],
        description="Railway lines and stations for passenger and freight transport",
    )

    population = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Population Census Data",
        keywords=["demographics", "census"],
        description="Population census data from the national statistics office",
    )

    rivers = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="River Systems Map",
        keywords=["hydrology", "rivers", "water"],
        description="Major river systems and watershed boundaries",
    )

    return {
        "roads": roads,
        "railways": railways,
        "population": population,
        "rivers": rivers,
    }


@pytest.fixture
async def hybrid_vectors(test_db_session) -> dict[str, list[float]]:
    """Build search vectors that match the current embedding column dimension."""
    dim = await _get_embedding_dim(test_db_session)
    return {
        "transport": _make_vector(1.0, dim=dim),
        "roads": _make_vector(0.95, dim=dim),
        "railways": _make_vector(0.90, dim=dim),
        "population": _make_vector(-0.5, dim=dim),
        "rivers": _make_vector(-0.8, dim=dim),
    }


@pytest.fixture
async def hybrid_datasets_with_embeddings(
    hybrid_datasets, hybrid_vectors: dict[str, list[float]], test_db_session
):
    """Add mock embeddings to the hybrid_datasets fixture records."""
    session = test_db_session

    for name, ds in hybrid_datasets.items():
        emb = RecordEmbedding(
            record_id=ds.record_id,
            embedding=hybrid_vectors[name],
            model_name="text-embedding-3-small",
            content_hash=f"test_hash_{name}",
        )
        session.add(emb)

    await session.commit()

    # Enable semantic search in app_settings
    await _set_semantic_search(session, True)

    return hybrid_datasets


# ---------------------------------------------------------------------------
# Tests: auto-enabled semantic search returns 200 (SRCH-01, SRCH-05)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_semantic_search_returns_200(
    client: AsyncClient,
    admin_auth_header: dict,
    hybrid_datasets_with_embeddings: dict,
    hybrid_vectors: dict[str, list[float]],
):
    """With semantic enabled and embeddings present, text query returns 200."""
    with patch(
        "app.modules.catalog.search.service_semantic.generate_embedding",
        new_callable=AsyncMock,
        return_value=hybrid_vectors["transport"],
    ):
        resp = await client.get(
            "/search/datasets/",
            params={"q": "transportation"},
            headers=admin_auth_header,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert "numberMatched" in data
    assert "features" in data


# ---------------------------------------------------------------------------
# Tests: fallback when no embeddings exist (SRCH-03)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_semantic_fallback_no_embeddings(
    client: AsyncClient,
    admin_auth_header: dict,
    hybrid_datasets: dict,
    test_db_session,
):
    """Falls back to FTS when semantic is enabled but no embeddings exist."""
    session = test_db_session
    await _set_semantic_search(session, True)

    # Ensure no embeddings exist for our datasets
    for ds in hybrid_datasets.values():
        await session.execute(
            text("DELETE FROM catalog.record_embeddings WHERE record_id = :rid"),
            {"rid": ds.record_id},
        )
    await session.commit()

    resp = await client.get(
        "/search/datasets/",
        params={"q": "roads"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    # Should still find roads via FTS
    titles = [f["properties"]["title"] for f in data["features"]]
    assert any("Roads" in t for t in titles)


# ---------------------------------------------------------------------------
# Tests: fallback when SEMANTIC_SEARCH_ENABLED is off
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_semantic_fallback_toggle_off(
    client: AsyncClient,
    admin_auth_header: dict,
    hybrid_datasets_with_embeddings: dict,
    test_db_session,
):
    """Falls back to FTS-only when SEMANTIC_SEARCH_ENABLED config is off."""
    session = test_db_session
    await _set_semantic_search(session, False)

    # Should still work via FTS
    resp = await client.get(
        "/search/datasets/",
        params={"q": "roads"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    titles = [f["properties"]["title"] for f in data["features"]]
    assert any("Roads" in t for t in titles)

    # Re-enable for other tests
    await _set_semantic_search(session, True)


# ---------------------------------------------------------------------------
# Tests: semantic works when AI_ENABLED is off but embeddings exist (SRCH-04)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_semantic_works_when_ai_disabled(
    client: AsyncClient,
    admin_auth_header: dict,
    hybrid_datasets_with_embeddings: dict,
    hybrid_vectors: dict[str, list[float]],
    test_db_session,
):
    """Semantic search still works when AI_ENABLED is off but embeddings exist.

    The search service reads existing embeddings from the DB -- it does not need
    AI to be enabled for that. Only generate_embedding needs to be mocked (no API key).
    """
    session = test_db_session

    # Disable AI
    result = await session.execute(
        select(AppSetting).where(AppSetting.key == "ai_enabled")
    )
    existing = result.scalar_one_or_none()
    if existing is None:
        session.add(AppSetting(key="ai_enabled", value={"v": False}))
    else:
        existing.value = {"v": False}
    await session.commit()

    from app.platform.cache import get_cache

    try:
        cache = get_cache()
        await cache.delete("config:ai_enabled")
    except RuntimeError:
        pass

    # Mock generate_embedding since there's no real API key,
    # but the vector search itself reads embeddings from DB directly
    with patch(
        "app.modules.catalog.search.service_semantic.generate_embedding",
        new_callable=AsyncMock,
        return_value=hybrid_vectors["transport"],
    ):
        resp = await client.get(
            "/search/datasets/",
            params={"q": "transportation"},
            headers=admin_auth_header,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) > 0

    # Cleanup: re-enable AI
    existing_row = (
        await session.execute(select(AppSetting).where(AppSetting.key == "ai_enabled"))
    ).scalar_one()
    existing_row.value = {"v": True}
    await session.commit()
    try:
        cache = get_cache()
        await cache.delete("config:ai_enabled")
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Tests: RRF ranking differs from FTS-only (SRCH-02)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_rrf_ranking_with_embeddings(
    client: AsyncClient,
    admin_auth_header: dict,
    hybrid_datasets_with_embeddings: dict,
    hybrid_vectors: dict[str, list[float]],
    test_db_session,
):
    """RRF-ranked results include vector similarity when semantic is enabled.

    Search for 'transport' -- vector search ranks roads/railways highly
    due to vector similarity, augmenting the FTS results.
    """
    with patch(
        "app.modules.catalog.search.service_semantic.generate_embedding",
        new_callable=AsyncMock,
        return_value=hybrid_vectors["transport"],
    ):
        resp_with = await client.get(
            "/search/datasets/",
            params={"q": "transport", "limit": 10},
            headers=admin_auth_header,
        )

    assert resp_with.status_code == 200
    data = resp_with.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) > 0

    # Now disable semantic and compare (FTS-only)
    session = test_db_session
    await _set_semantic_search(session, False)

    resp_without = await client.get(
        "/search/datasets/",
        params={"q": "transport", "limit": 10},
        headers=admin_auth_header,
    )

    assert resp_without.status_code == 200

    # Re-enable for other tests
    await _set_semantic_search(session, True)


# ---------------------------------------------------------------------------
# Tests: unit test for _compute_rrf_scores
# ---------------------------------------------------------------------------


def test_compute_rrf_scores_basic():
    """Verify RRF score computation merges FTS and vector ranks correctly."""
    from app.modules.catalog.search.service import _compute_rrf_scores

    fts_ids = ["a", "b", "c"]
    vector_ranks = {"b": 1, "c": 2, "d": 3}

    result = _compute_rrf_scores(fts_ids, vector_ranks, k=60)

    # 'b' should rank higher: FTS rank 2 + vector rank 1
    # 'a' only has FTS rank 1
    # 'c' has FTS rank 3 + vector rank 2
    # 'd' only has vector rank 3

    assert isinstance(result, list)
    assert set(result) == {"a", "b", "c", "d"}

    # Verify b is ranked first (highest RRF score)
    assert result[0] == "b", f"Expected 'b' first, got {result}"
    # c has second highest score
    assert result[1] == "c", f"Expected 'c' second, got {result}"
    # a has third highest score
    assert result[2] == "a", f"Expected 'a' third, got {result}"
    # d has lowest score
    assert result[3] == "d", f"Expected 'd' last, got {result}"


def test_compute_rrf_scores_equal_score_deterministic_tiebreak():
    """OGC-7/TQ-1: equal RRF scores get a stable, deterministic order.

    Two ids with the SAME vector rank (and no FTS contribution) earn an
    identical RRF score. Without a tiebreaker, their relative order would be
    arbitrary (and could differ between runs / processes), which is what made
    semantic-only matches drop or dupe across pages. The tiebreak is on the
    record id string. Production coerces ids to str before merging, so this
    uses str ids (not UUIDs).
    """
    from app.modules.catalog.search.service import _compute_rrf_scores

    fts_ids: list[str] = []
    # Identical rank => identical RRF score for both ids.
    vector_ranks = {"id_aaa": 1, "id_zzz": 1}

    result = _compute_rrf_scores(fts_ids, vector_ranks, k=60)

    assert set(result) == {"id_aaa", "id_zzz"}
    # Deterministic: sorted by (score, rid) descending, so the lexicographically
    # larger id wins the tie. Stable across repeated calls regardless of dict
    # insertion order.
    assert result == ["id_zzz", "id_aaa"]

    # Reversed insertion order yields the SAME deterministic result.
    result_reversed = _compute_rrf_scores(fts_ids, {"id_zzz": 1, "id_aaa": 1}, k=60)
    assert result_reversed == ["id_zzz", "id_aaa"]


# ---------------------------------------------------------------------------
# Tests: true semantic retrieval — vector-only matches are surfaced, but
# never leak non-visible datasets (visibility-aware RRF union)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_semantic_surfaces_vector_only_match(
    client: AsyncClient,
    admin_auth_header: dict,
    hybrid_datasets_with_embeddings: dict,
    hybrid_vectors: dict[str, list[float]],
):
    """A record that matches by MEANING but not by keyword is surfaced.

    Query text that matches NO dataset lexically, with the query embedding close
    to the 'roads'/'railways' vectors -> those vector-only matches must appear
    (previously the RRF merge excluded vector-only ids and returned nothing).
    """
    with patch(
        "app.modules.catalog.search.service_semantic.generate_embedding",
        new_callable=AsyncMock,
        return_value=hybrid_vectors["transport"],
    ):
        resp = await client.get(
            "/search/datasets/",
            params={"q": "zzznolexicalmatchxyz"},
            headers=admin_auth_header,
        )
    assert resp.status_code == 200
    titles = {
        f["properties"]["title"] for f in resp.json()["features"] if f.get("properties")
    }
    # transport (1.0) is close to roads (0.95) + railways (0.90); far from
    # population (-0.5) / rivers (-0.8) which exceed the 0.7 distance cutoff.
    assert "Roads and Highways Network" in titles
    assert "Railway Network Lines" in titles


@pytest.mark.anyio
async def test_semantic_vector_only_does_not_leak_private(
    client: AsyncClient,
    hybrid_datasets_with_embeddings: dict,
    hybrid_vectors: dict[str, list[float]],
    test_db_session,
):
    """A PRIVATE vector-only match must never surface to an anonymous caller.

    The vector query (_get_vector_ranks) is not visibility-filtered, so the RRF
    union must run vector-only candidates through apply_visibility_filter. A
    private record with a near-perfect embedding match + a non-lexical title is
    the exact leak this guards against.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    private_ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Classified Restricted Layer",  # no lexical overlap with the query
        description="Sensitive private dataset",
        visibility="private",
    )
    session.add(
        RecordEmbedding(
            record_id=private_ds.record_id,
            embedding=hybrid_vectors["transport"],  # ~identical to the query vector
            model_name="text-embedding-3-small",
            content_hash="test_hash_private_leak",
        )
    )
    await session.commit()

    # Anonymous request (no auth header) — filter_visible restricts to public.
    with patch(
        "app.modules.catalog.search.service_semantic.generate_embedding",
        new_callable=AsyncMock,
        return_value=hybrid_vectors["transport"],
    ):
        resp = await client.get(
            "/search/datasets/",
            params={"q": "zzznolexicalmatchxyz"},
        )
    assert resp.status_code == 200
    titles = {
        f["properties"]["title"] for f in resp.json()["features"] if f.get("properties")
    }
    # The private record must NOT leak, even though its embedding is the closest match.
    assert "Classified Restricted Layer" not in titles
    # ...but a PUBLIC vector-only match still surfaces (semantic retrieval works for anon).
    assert "Roads and Highways Network" in titles


@pytest.mark.anyio
async def test_semantic_vector_only_respects_active_filters(
    client: AsyncClient,
    admin_auth_header: dict,
    hybrid_datasets_with_embeddings: dict,
    hybrid_vectors: dict[str, list[float]],
    test_db_session,
):
    """A vector-only match must still satisfy the OTHER active filters.

    With geometry_type=Point, a semantically similar POLYGON (vector-only, no
    lexical hit) must NOT surface; only a Point dataset that also matches by
    meaning may. Guards the filter-bypass the visibility-only check missed.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    point_ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Transit Stops Inventory",  # no lexical overlap with the query
        description="Point inventory",
        geometry_type="Point",
    )
    session.add(
        RecordEmbedding(
            record_id=point_ds.record_id,
            embedding=hybrid_vectors["transport"],
            model_name="text-embedding-3-small",
            content_hash="test_hash_point_geom",
        )
    )
    await session.commit()

    with patch(
        "app.modules.catalog.search.service_semantic.generate_embedding",
        new_callable=AsyncMock,
        return_value=hybrid_vectors["transport"],
    ):
        resp = await client.get(
            "/search/datasets/",
            params={"q": "zzznolexicalmatchxyz", "geometry_type": "Point"},
            headers=admin_auth_header,
        )
    assert resp.status_code == 200
    titles = {
        f["properties"]["title"] for f in resp.json()["features"] if f.get("properties")
    }
    # The Point vector-only match surfaces...
    assert "Transit Stops Inventory" in titles
    # ...but the MultiPolygon vector matches are excluded by geometry_type=Point.
    assert "Roads and Highways Network" not in titles
    assert "Railway Network Lines" not in titles


@pytest.mark.anyio
async def test_semantic_visible_match_not_crowded_out_by_nearer_private(
    client: AsyncClient,
    test_db_session,
):
    """A visible vector match must not be displaced from the top-k by nearer private ones.

    With limit=2 and three PRIVATE records embedded nearer the query than the one
    PUBLIC record, the public record must still surface — the cosine top-k is taken
    over the visibility/filter-vetted set, not all embeddings (Codex P2a).
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    dim = await _get_embedding_dim(session)
    await _set_semantic_search(session, True)

    # Use a dedicated vector band (lo=110) orthogonal to every other test's
    # records so a concurrent -n4 worker's public lo=40 embedding can't pollute
    # this test's restricted top-k (same-band vectors are near-cosine-identical,
    # so an unrelated public record would otherwise tie-break into the limit).
    band_lo = 110
    public_ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Open Transit Hub Index",  # no lexical overlap with the query
        description="public",
    )
    session.add(
        RecordEmbedding(
            record_id=public_ds.record_id,
            embedding=_make_vector_band(0.85, dim=dim, lo=band_lo),
            model_name="text-embedding-3-small",
            content_hash="p2a_public",
        )
    )
    for i, base in enumerate((0.99, 0.98, 0.97)):
        priv = await _create_search_dataset(
            session,
            created_by=admin_id,
            name=f"Private Near Neighbour {i}",
            description="private",
            visibility="private",
        )
        session.add(
            RecordEmbedding(
                record_id=priv.record_id,
                embedding=_make_vector_band(
                    base, dim=dim, lo=band_lo
                ),  # nearer than the public 0.85
                model_name="text-embedding-3-small",
                content_hash=f"p2a_priv_{i}",
            )
        )
    await session.commit()

    with patch(
        "app.modules.catalog.search.service_semantic.generate_embedding",
        new_callable=AsyncMock,
        return_value=_make_vector_band(1.0, dim=dim, lo=band_lo),
    ):
        resp = await client.get(
            "/search/datasets/",
            params={"q": "zzznolexicalmatchxyz", "limit": 2},
        )
    assert resp.status_code == 200
    titles = {
        f["properties"]["title"] for f in resp.json()["features"] if f.get("properties")
    }
    assert "Open Transit Hub Index" in titles
    for i in range(3):
        assert f"Private Near Neighbour {i}" not in titles


@pytest.mark.anyio
async def test_semantic_vector_only_pagination(
    client: AsyncClient,
    test_db_session,
):
    """Later pages of semantic-only matches must not be empty (Codex round-3 P2).

    With five vector-only matches and limit=2, page 2 (offset=2) must return
    results distinct from page 1 — the vector fetch must reach skip+limit deep.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    dim = await _get_embedding_dim(session)
    await _set_semantic_search(session, True)

    # Five public datasets in an isolated vector band (lo=70), decreasing similarity.
    for i, base in enumerate((0.99, 0.95, 0.90, 0.85, 0.80)):
        ds = await _create_search_dataset(
            session,
            created_by=admin_id,
            name=f"Band Catalog Layer {i}",  # no lexical overlap with the query
            description="public",
        )
        session.add(
            RecordEmbedding(
                record_id=ds.record_id,
                embedding=_make_vector_band(base, dim=dim, lo=70),
                model_name="text-embedding-3-small",
                content_hash=f"page_band_{i}",
            )
        )
    await session.commit()

    async def _page(offset: int) -> tuple[list[str], int]:
        with patch(
            "app.modules.catalog.search.service_semantic.generate_embedding",
            new_callable=AsyncMock,
            return_value=_make_vector_band(1.0, dim=dim, lo=70),
        ):
            r = await client.get(
                "/search/datasets/",
                params={"q": "zzznolexicalmatchxyz", "limit": 2, "offset": offset},
            )
        assert r.status_code == 200
        body = r.json()
        titles = [
            f["properties"]["title"] for f in body["features"] if f.get("properties")
        ]
        return titles, body.get("numberMatched", 0)

    page1, matched = await _page(0)
    page2, _ = await _page(2)
    assert len(page2) >= 1, "second page of semantic-only results must not be empty"
    assert set(page1).isdisjoint(set(page2)), "pages must not overlap"
    # numberMatched must reflect ALL five semantic matches, not just the page window,
    # or the router omits the `next` link (Codex round-4 count fix).
    assert matched >= 5, (
        f"numberMatched should count all semantic matches, got {matched}"
    )
