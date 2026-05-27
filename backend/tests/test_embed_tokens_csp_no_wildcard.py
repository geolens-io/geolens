"""SHARE-06 backend pin: CSP frame-ancestors NEVER contains '*'.

This file covers two layers of the wildcard-rejection invariant:

  1. Schema layer (_validate_origins): POST/PATCH with wildcard origin returns 422
     with body detail containing 'Wildcard origin not allowed'.

  2. Canonical-form round-trip (SHARE-06 closure): allowed_origins are normalised
     (lowercased, default-port stripped, trailing slash stripped) before storage,
     matching the frontend Plan 01 normalizeOrigin contract.

The CSP header-level test (defense-in-depth on the _build_frame_ancestors helper)
lives in test_embed_framing_csp.py::test_shared_map_csp_header_drops_wildcard_origin
— added by Task 2 of Phase 1137 Plan 02.

Cross-reference: frontend Plan 01 (1137-01) has a parity test on normalizeOrigin
for the same canonical-form contract (SHARE-06).
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.maps.models import Map, MapShareToken
from app.modules.embed_tokens.models import EmbedToken

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def enterprise_edition(monkeypatch):
    """Enable Enterprise edition for origin-restriction tests."""
    from app.core.edition import init_edition

    monkeypatch.delenv("GEOLENS_EDITION", raising=False)
    init_edition(["enterprise"])
    yield
    init_edition([])


# ---------------------------------------------------------------------------
# Internal helpers (mirror test_embed_framing_csp.py helpers)
# ---------------------------------------------------------------------------


async def _create_public_map(session: AsyncSession, *, created_by: uuid.UUID) -> Map:
    """Insert a public Map row with no layers."""
    map_obj = Map(
        name=f"CSP Wildcard Test Map {uuid.uuid4().hex[:6]}",
        description="csp no-wildcard test",
        visibility="public",
        created_by=created_by,
    )
    session.add(map_obj)
    await session.flush()
    await session.refresh(map_obj)
    return map_obj


async def _create_share_token(
    session: AsyncSession, *, map_id: uuid.UUID, created_by: uuid.UUID
) -> str:
    """Insert a MapShareToken and return the raw (unhashed) token string."""
    raw = secrets.token_urlsafe(32)
    token_obj = MapShareToken(
        map_id=map_id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        token_hint=raw[:8],
        created_by=created_by,
        is_active=True,
    )
    session.add(token_obj)
    await session.flush()
    return raw


async def _create_embed_token_direct(
    session: AsyncSession,
    *,
    map_id: uuid.UUID,
    created_by: uuid.UUID,
    allowed_origins: list[str] | None = None,
) -> EmbedToken:
    """Insert an EmbedToken directly via SQLAlchemy (bypasses service/schema validation).

    Used for tests that need a pre-existing token to PATCH, without requiring
    the map to have layers (the service layer enforces that; the schema does not).
    """
    raw = secrets.token_urlsafe(32)
    token_obj = EmbedToken(
        map_id=map_id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        token_hint=raw[:8],
        scoped_dataset_ids=[],
        allowed_origins=allowed_origins,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        is_active=True,
        created_by=created_by,
    )
    session.add(token_obj)
    await session.flush()
    await session.refresh(token_obj)
    return token_obj


# ---------------------------------------------------------------------------
# Task 1 — Schema-layer wildcard rejection (5 tests)
# ---------------------------------------------------------------------------


async def test_post_embed_token_rejects_wildcard_origin(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    enterprise_edition,
):
    """POST /maps/{id}/embed-tokens with allowed_origins=['*'] returns 422.

    The schema-layer _validate_origins raises ValueError('Wildcard origin not allowed')
    which Pydantic surfaces as a 422 Unprocessable Entity. The response detail must
    contain the substring 'Wildcard origin not allowed' so that frontend Plan 01
    can match it via the WildcardOriginError class.
    """
    user_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_public_map(test_db_session, created_by=user_id)
    await test_db_session.commit()

    resp = await client.post(
        f"/maps/{map_obj.id}/embed-tokens/",
        json={"allowed_origins": ["*"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    detail_str = str(resp.json().get("detail", ""))
    assert "Wildcard origin not allowed" in detail_str, (
        f"Expected 'Wildcard origin not allowed' in detail, got: {detail_str!r}"
    )


async def test_post_embed_token_rejects_wildcard_subdomain(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    enterprise_edition,
):
    """POST with allowed_origins=['*.example.com'] returns 422.

    CSP frame-ancestors does not support leading-* wildcard subdomain patterns.
    The schema must reject them with the same 'Wildcard origin not allowed' message.
    """
    user_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_public_map(test_db_session, created_by=user_id)
    await test_db_session.commit()

    resp = await client.post(
        f"/maps/{map_obj.id}/embed-tokens/",
        json={"allowed_origins": ["*.example.com"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    detail_str = str(resp.json().get("detail", ""))
    assert "Wildcard origin not allowed" in detail_str, (
        f"Expected 'Wildcard origin not allowed' in detail, got: {detail_str!r}"
    )


async def test_post_embed_token_rejects_mixed_list_with_wildcard(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    enterprise_edition,
):
    """POST with allowed_origins=['https://example.com', '*'] returns 422.

    The presence of any wildcard entry taints the entire list. The first valid
    entry does not suppress the rejection.
    """
    user_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_public_map(test_db_session, created_by=user_id)
    await test_db_session.commit()

    resp = await client.post(
        f"/maps/{map_obj.id}/embed-tokens/",
        json={"allowed_origins": ["https://example.com", "*"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    detail_str = str(resp.json().get("detail", ""))
    assert "Wildcard origin not allowed" in detail_str, (
        f"Expected 'Wildcard origin not allowed' in detail, got: {detail_str!r}"
    )


async def test_patch_embed_token_rejects_wildcard_origin(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    enterprise_edition,
):
    """PATCH /maps/{id}/embed-tokens/{token_id} with allowed_origins=['*'] returns 422.

    Wildcard rejection applies equally to PATCH (EmbedTokenUpdate schema) as to
    POST (EmbedTokenCreate schema). The initial token is inserted directly via
    SQLAlchemy to avoid the service-layer "Map has no layers" guard (which is
    irrelevant to the schema-rejection being tested here).
    """
    user_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_public_map(test_db_session, created_by=user_id)
    # Insert a base token directly (bypasses service layer — no layers needed)
    token_obj = await _create_embed_token_direct(
        test_db_session, map_id=map_obj.id, created_by=user_id
    )
    await test_db_session.commit()

    # PATCH with a wildcard origin — must be rejected at the schema layer
    patch_resp = await client.patch(
        f"/maps/{map_obj.id}/embed-tokens/{token_obj.id}/",
        json={"allowed_origins": ["*"]},
        headers=admin_auth_header,
    )
    assert patch_resp.status_code == 422, (
        f"Expected 422, got {patch_resp.status_code}: {patch_resp.text}"
    )
    detail_str = str(patch_resp.json().get("detail", ""))
    assert "Wildcard origin not allowed" in detail_str, (
        f"Expected 'Wildcard origin not allowed' in detail, got: {detail_str!r}"
    )


def test_validate_origins_accepts_non_wildcard_list():
    """Regression pin: _validate_origins accepts a well-formed non-wildcard list.

    Wildcard rejection must not break the happy-path case where allowed_origins
    contains only valid https:// origins. Tests the schema-layer function directly
    to avoid dependency on service-layer guards (map-must-have-layers).
    """
    from app.modules.embed_tokens.schemas import _validate_origins

    result = _validate_origins(["https://example.com"])
    assert result == ["https://example.com"], (
        f"Expected ['https://example.com'] for non-wildcard origin, got: {result!r}"
    )

    # Multiple valid origins — all must pass through unchanged
    result2 = _validate_origins(["https://partner.example", "http://localhost:3000"])
    assert result2 == ["https://partner.example", "http://localhost:3000"], (
        f"Multiple non-wildcard origins should pass unchanged, got: {result2!r}"
    )


# ---------------------------------------------------------------------------
# Task 3 — SHARE-06 canonical-form round-trip pin
# ---------------------------------------------------------------------------


def test_post_embed_token_canonicalizes_origin_storage():
    """SHARE-06 backend round-trip pin: _validate_origins normalises origins before storage.

    Input canonical-form transformations verified:
      - HTTPS://EXAMPLE.COM:443/  →  https://example.com  (lowercase + default port stripped + trailing slash stripped)
      - http://localhost:3000/    →  http://localhost:3000 (trailing slash stripped; non-default port kept)
      - https://other.com        →  https://other.com     (already canonical — unchanged)

    Tests the schema-layer function directly to avoid dependency on service-layer
    guards (map-must-have-layers). The stored canonical form is exactly what the
    DB holds and what the embed token response returns.

    Cross-reference: frontend Plan 01 (Phase 1137-01) has a parity test on
    normalizeOrigin for the same contract (SHARE-06). If either side drifts, both
    this test and the Plan 01 parity test go red.
    """
    from app.modules.embed_tokens.schemas import _validate_origins

    result = _validate_origins([
        "HTTPS://EXAMPLE.COM:443/",
        "http://localhost:3000/",
        "https://other.com",
    ])
    assert result == [
        "https://example.com",
        "http://localhost:3000",
        "https://other.com",
    ], (
        f"Canonical-form mismatch (SHARE-06): expected normalised origins, got: {result!r}"
    )
