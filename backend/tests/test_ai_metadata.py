"""Integration tests for AI metadata generation endpoints.

Tests cover: summary/keywords/lineage draft generation, auth gates,
feature toggle, API key guards, and invalid dataset handling.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.processing.ai.metadata_schemas import (
    KeywordSuggestionsResponse,
    LineageDraftResponse,
    MetadataAssistRequest,
    SummaryDraftResponse,
)
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record

from app.core.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_test_dataset(session, created_by: uuid.UUID) -> Dataset:
    """Insert a Record + Dataset pair with realistic metadata."""

    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title="NYC Parks",
        summary="Public parks and recreational areas in New York City",
        lineage_summary="Sourced from NYC Open Data",
        source_organization="NYC DPR",
        visibility="public",
        record_status="draft",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="MULTIPOLYGON",
        feature_count=2000,
        column_info=[
            {"name": "park_name", "type": "text"},
            {"name": "borough", "type": "text"},
            {"name": "acres", "type": "numeric"},
        ],
        sample_values={"park_name": ["Central Park", "Prospect Park"]},
        source_format="shapefile",
        source_filename="nyc_parks.shp",
        original_srid=2263,
    )
    session.add(dataset)
    await session.flush()
    return dataset


async def _get_admin_user_id(session) -> uuid.UUID:
    from sqlalchemy import select

    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    user = result.scalar_one()
    return user.id


# ---------------------------------------------------------------------------
# Schema import tests
# ---------------------------------------------------------------------------


def test_schema_models_importable():
    """Verify all schema models can be imported and instantiated."""
    req = MetadataAssistRequest(dataset_id=str(uuid.uuid4()))
    assert req.dataset_id

    summary = SummaryDraftResponse(draft="A test summary.")
    assert summary.draft

    keywords = KeywordSuggestionsResponse(
        keywords=[
            {"keyword": "water", "keyword_type": "theme"},
            {"keyword": "rivers", "keyword_type": "theme"},
        ]
    )
    assert len(keywords.keywords) == 2

    lineage = LineageDraftResponse(draft="Sourced from open data.")
    assert lineage.draft


# ---------------------------------------------------------------------------
# Service function tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_functions_importable():
    """Verify service functions can be imported."""
    from app.processing.ai.metadata_service import (
        generate_keyword_suggestions,
        generate_lineage_draft,
        generate_summary_draft,
    )

    assert callable(generate_summary_draft)
    assert callable(generate_keyword_suggestions)
    assert callable(generate_lineage_draft)


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_summary_endpoint_returns_draft(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """POST /ai/metadata/summary/ returns a draft summary."""
    user_id = await _get_admin_user_id(test_db_session)
    ds = await _create_test_dataset(test_db_session, user_id)
    await test_db_session.commit()

    mock_response = SummaryDraftResponse(draft="NYC Parks is a dataset...")

    with (
        patch(
            "app.processing.ai.router.generate_summary_draft",
            new_callable=AsyncMock,
            return_value=mock_response,
        ),
        patch(
            "app.processing.ai.router._check_ai_available",
            new_callable=AsyncMock,
        ),
    ):
        resp = await client.post(
            "/ai/metadata/summary/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "draft" in data
    assert len(data["draft"]) > 0


@pytest.mark.anyio
async def test_keywords_endpoint_returns_suggestions(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """POST /ai/metadata/keywords/ returns keyword suggestions."""
    user_id = await _get_admin_user_id(test_db_session)
    ds = await _create_test_dataset(test_db_session, user_id)
    await test_db_session.commit()

    mock_response = KeywordSuggestionsResponse(
        keywords=[
            {"keyword": "parks", "keyword_type": "theme"},
            {"keyword": "recreation", "keyword_type": "theme"},
            {"keyword": "nyc", "keyword_type": "place"},
        ]
    )

    with (
        patch(
            "app.processing.ai.router.generate_keyword_suggestions",
            new_callable=AsyncMock,
            return_value=mock_response,
        ),
        patch(
            "app.processing.ai.router._check_ai_available",
            new_callable=AsyncMock,
        ),
    ):
        resp = await client.post(
            "/ai/metadata/keywords/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "keywords" in data
    assert isinstance(data["keywords"], list)
    assert len(data["keywords"]) > 0


@pytest.mark.anyio
async def test_lineage_endpoint_returns_draft(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """POST /ai/metadata/lineage/ returns a lineage draft."""
    user_id = await _get_admin_user_id(test_db_session)
    ds = await _create_test_dataset(test_db_session, user_id)
    await test_db_session.commit()

    mock_response = LineageDraftResponse(draft="Data was sourced from...")

    with (
        patch(
            "app.processing.ai.router.generate_lineage_draft",
            new_callable=AsyncMock,
            return_value=mock_response,
        ),
        patch(
            "app.processing.ai.router._check_ai_available",
            new_callable=AsyncMock,
        ),
    ):
        resp = await client.post(
            "/ai/metadata/lineage/",
            json={"dataset_id": str(ds.id)},
            headers=admin_auth_header,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "draft" in data
    assert len(data["draft"]) > 0


@pytest.mark.anyio
async def test_returns_403_when_ai_disabled(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """All metadata endpoints return 403 when AI toggle is disabled."""
    from fastapi import HTTPException, status

    async def _raise_ai_disabled(*args, **kwargs):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI features are disabled by administrator",
        )

    with patch(
        "app.processing.ai.router._check_ai_available",
        new_callable=AsyncMock,
        side_effect=_raise_ai_disabled,
    ):
        resp = await client.post(
            "/ai/metadata/summary/",
            json={"dataset_id": str(uuid.uuid4())},
            headers=admin_auth_header,
        )

    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_returns_503_when_no_api_key(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """All metadata endpoints return 503 when no API key is configured."""
    from fastapi import HTTPException, status

    async def _raise_not_configured(*args, **kwargs):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI is not configured (missing API key)",
        )

    with patch(
        "app.processing.ai.router._check_ai_available",
        new_callable=AsyncMock,
        side_effect=_raise_not_configured,
    ):
        resp = await client.post(
            "/ai/metadata/summary/",
            json={"dataset_id": str(uuid.uuid4())},
            headers=admin_auth_header,
        )

    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_returns_401_unauthenticated(client: AsyncClient):
    """POST without auth token returns 401."""
    resp = await client.post(
        "/ai/metadata/summary/",
        json={"dataset_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_returns_422_invalid_dataset(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """POST with nonexistent dataset_id returns 422."""
    fake_id = str(uuid.uuid4())

    with (
        patch(
            "app.processing.ai.router._check_ai_available",
            new_callable=AsyncMock,
        ),
        patch(
            "app.processing.ai.router.generate_summary_draft",
            new_callable=AsyncMock,
            side_effect=ValueError("Dataset not found"),
        ),
    ):
        resp = await client.post(
            "/ai/metadata/summary/",
            json={"dataset_id": fake_id},
            headers=admin_auth_header,
        )

    assert resp.status_code == 422
    assert "not found" in resp.json()["detail"].lower()
