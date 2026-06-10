"""DB-backed regression tests for AI metadata endpoint authorization (Phase 1173, SEC-D).

SEC-D (HIGH): the four `POST /ai/metadata/{summary,keywords,lineage,quality-statement}/`
endpoints are gated only by `require_permission("use_ai_chat")` — which the default
editor role has (`core/permissions.py:42`). The attacker-controlled `body.dataset_id`
flowed to `_build_dataset_context` with no visibility filter, rendering ANY dataset's
title/summary/source_url/filename/columns/sample-values into the LLM prompt (echoed in
the response). The fix authorizes the requested dataset in each handler
(`_authorize_metadata_dataset` → `check_dataset_access` → 404 on denial) before the
generation service runs.

The four ATTACK tests fail on main `2c031da8` (an editor gets a 200 draft for another
user's private dataset); the owner/admin GUARD tests pass before and after.

In every test `_check_ai_available` is patched (so the AI-availability gate never 503s)
and the generation service is patched to a valid response (so no real LLM call, and so
UNFIXED main returns a clean 200 to demonstrate the leak; the fix 404s before the
service is reached).

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from .conftest import _create_test_user
from tests.factories import create_dataset
from app.processing.ai.metadata_schemas import (
    KeywordSuggestion,
    KeywordSuggestionsResponse,
    LineageDraftResponse,
    QualityStatementDraftResponse,
    SummaryDraftResponse,
)


# (url, router service attr to patch, valid mock response for that endpoint)
_ENDPOINTS = [
    (
        "/ai/metadata/summary/",
        "generate_summary_draft",
        SummaryDraftResponse(draft="A drafted summary."),
    ),
    (
        "/ai/metadata/keywords/",
        "generate_keyword_suggestions",
        KeywordSuggestionsResponse(
            keywords=[KeywordSuggestion(keyword="parks", keyword_type="theme")]
        ),
    ),
    (
        "/ai/metadata/lineage/",
        "generate_lineage_draft",
        LineageDraftResponse(draft="A drafted lineage."),
    ),
    (
        "/ai/metadata/quality-statement/",
        "generate_quality_statement_draft",
        QualityStatementDraftResponse(draft="A drafted quality statement."),
    ),
]
_IDS = ["summary", "keywords", "lineage", "quality-statement"]


def _patches(generate_fn_name: str, mock_response):
    """Patch the AI-availability gate (no 503) and the generation service (no real
    LLM, valid 200 body). The service is what UNFIXED main reaches after the missing
    authz; the fix 404s in `_authorize_metadata_dataset` before it is ever invoked."""
    return (
        patch("app.processing.ai.router._check_ai_available", new=AsyncMock()),
        patch(
            f"app.processing.ai.router.{generate_fn_name}",
            new=AsyncMock(return_value=mock_response),
        ),
    )


# ---------------------------------------------------------------------------
# SEC-D — attack: non-admin editor cannot read another user's private dataset
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("url,fn,mock_resp", _ENDPOINTS, ids=_IDS)
async def test_metadata_rejects_foreign_private_dataset(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    url: str,
    fn: str,
    mock_resp,
):
    """Editor B requests AI metadata for editor A's PRIVATE dataset → 403/404.

    Fails on main (200): the handler authorizes no dataset.
    """
    _owner_headers, owner_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    attacker_headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    private = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(owner_id),
        name="Owner private dataset",
        visibility="private",
    )

    p_avail, p_svc = _patches(fn, mock_resp)
    with p_avail, p_svc:
        resp = await client.post(
            url, json={"dataset_id": str(private.id)}, headers=attacker_headers
        )

    assert resp.status_code in (403, 404), (
        f"{url}: editor read ANOTHER user's private dataset metadata, got "
        f"{resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# GUARDs — owner and admin must NOT be over-blocked
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("url,fn,mock_resp", _ENDPOINTS, ids=_IDS)
async def test_metadata_allows_owner(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    url: str,
    fn: str,
    mock_resp,
):
    """GUARD: the owning editor CAN draft metadata for their OWN private dataset —
    authorization is by ownership, not admin-ness. Must stay 200 after the fix."""
    owner_headers, owner_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    private = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(owner_id),
        name="Owner private dataset",
        visibility="private",
    )

    p_avail, p_svc = _patches(fn, mock_resp)
    with p_avail, p_svc:
        resp = await client.post(
            url, json={"dataset_id": str(private.id)}, headers=owner_headers
        )

    assert resp.status_code == 200, (
        f"{url}: owner blocked from their OWN dataset, got "
        f"{resp.status_code}: {resp.text}"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("url,fn,mock_resp", _ENDPOINTS, ids=_IDS)
async def test_metadata_allows_admin(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    url: str,
    fn: str,
    mock_resp,
):
    """GUARD: admin is never over-blocked (admins access all datasets)."""
    _owner_headers, owner_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    private = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(owner_id),
        name="Owner private dataset",
        visibility="private",
    )

    p_avail, p_svc = _patches(fn, mock_resp)
    with p_avail, p_svc:
        resp = await client.post(
            url, json={"dataset_id": str(private.id)}, headers=admin_auth_header
        )

    assert resp.status_code == 200, (
        f"{url}: admin over-blocked, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_metadata_invalid_uuid_returns_422(
    client: AsyncClient, admin_auth_header: dict
):
    """A non-UUID dataset_id is rejected with 422 (not a 500 from the loader)."""
    with patch("app.processing.ai.router._check_ai_available", new=AsyncMock()):
        resp = await client.post(
            "/ai/metadata/summary/",
            json={"dataset_id": "not-a-uuid"},
            headers=admin_auth_header,
        )
    assert resp.status_code == 422, f"got {resp.status_code}: {resp.text}"
