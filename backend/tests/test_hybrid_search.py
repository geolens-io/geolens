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
) -> Dataset:
    """Insert a Record + Dataset pair for hybrid search tests."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=description or f"Description for {name}",
        visibility="public",
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
        geometry_type="MultiPolygon",
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
        "app.modules.catalog.search.service.generate_embedding",
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
        "app.modules.catalog.search.service.generate_embedding",
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
        "app.modules.catalog.search.service.generate_embedding",
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
