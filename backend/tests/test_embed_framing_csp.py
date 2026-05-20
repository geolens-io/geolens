"""Tests for SEC-S08 — embed-token frame-ancestors CSP on the shared-map response.

Phase 1062-05: the shared-map endpoint must emit a per-token
Content-Security-Policy: frame-ancestors header derived from the active
EmbedToken.allowed_origins. SecurityHeadersMiddleware must skip X-Frame-Options
when a route already set CSP with frame-ancestors.

Task 1 tests: API response CSP header (default and dynamic allowed_origins).
Task 2 tests: Middleware coexistence (XFO dropped when route sets CSP).
Task 3 test:  E2E file-presence assertion (documents that the nginx test exists in
              sec-audit.spec.ts and requires SEC_AUDIT_SHARE_TOKEN).
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.maps.models import Map, MapShareToken
from app.modules.embed_tokens.models import EmbedToken

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _create_public_map(session: AsyncSession, *, created_by: uuid.UUID) -> Map:
    """Insert a public Map row with no layers."""
    map_obj = Map(
        name=f"CSP Test Map {uuid.uuid4().hex[:6]}",
        description="embed framing CSP test",
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


async def _create_embed_token(
    session: AsyncSession,
    *,
    map_id: uuid.UUID,
    created_by: uuid.UUID,
    allowed_origins: list[str] | None = None,
    is_active: bool = True,
    expires_days: int = 30,
) -> EmbedToken:
    """Insert an EmbedToken for the given map."""
    raw = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)
    token_obj = EmbedToken(
        map_id=map_id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        token_hint=raw[:8],
        scoped_dataset_ids=[],
        expires_at=expires_at,
        is_active=is_active,
        created_by=created_by,
        allowed_origins=allowed_origins,
    )
    session.add(token_obj)
    await session.flush()
    return token_obj


# ---------------------------------------------------------------------------
# Task 1 — API response CSP header
# ---------------------------------------------------------------------------


async def test_shared_map_with_no_embed_token_returns_frame_ancestors_self(
    client: AsyncClient,
    test_db_session: AsyncSession,
):
    """GET /maps/shared/{token} with no EmbedToken returns frame-ancestors 'self'."""
    admin_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_public_map(test_db_session, created_by=admin_id)
    raw_token = await _create_share_token(
        test_db_session, map_id=map_obj.id, created_by=admin_id
    )
    await test_db_session.commit()

    resp = await client.get(f"/maps/shared/{raw_token}")
    assert resp.status_code == 200
    csp = resp.headers.get("content-security-policy", "")
    assert "frame-ancestors" in csp, f"Expected frame-ancestors in CSP, got: {csp!r}"
    assert "'self'" in csp, f"Expected 'self' in CSP when no allowed_origins, got: {csp!r}"


async def test_shared_map_with_embed_token_returns_frame_ancestors_from_allowed_origins(
    client: AsyncClient,
    test_db_session: AsyncSession,
):
    """GET /maps/shared/{token} with active EmbedToken carrying allowed_origins returns
    dynamic frame-ancestors CSP that includes both origins."""
    admin_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_public_map(test_db_session, created_by=admin_id)
    raw_token = await _create_share_token(
        test_db_session, map_id=map_obj.id, created_by=admin_id
    )
    await _create_embed_token(
        test_db_session,
        map_id=map_obj.id,
        created_by=admin_id,
        allowed_origins=["https://partner.example", "https://other.example"],
    )
    await test_db_session.commit()

    resp = await client.get(f"/maps/shared/{raw_token}")
    assert resp.status_code == 200
    csp = resp.headers.get("content-security-policy", "")
    assert "frame-ancestors" in csp, f"Expected frame-ancestors in CSP, got: {csp!r}"
    assert "https://partner.example" in csp, f"Expected partner.example in CSP, got: {csp!r}"
    assert "https://other.example" in csp, f"Expected other.example in CSP, got: {csp!r}"
    assert "'self'" in csp, f"Expected 'self' always included, got: {csp!r}"


async def test_shared_map_with_embed_token_empty_origins_returns_frame_ancestors_self(
    client: AsyncClient,
    test_db_session: AsyncSession,
):
    """GET /maps/shared/{token} with active EmbedToken but empty/None allowed_origins
    returns the default 'self' frame-ancestors CSP."""
    admin_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_public_map(test_db_session, created_by=admin_id)
    raw_token = await _create_share_token(
        test_db_session, map_id=map_obj.id, created_by=admin_id
    )
    # Empty allowed_origins
    await _create_embed_token(
        test_db_session,
        map_id=map_obj.id,
        created_by=admin_id,
        allowed_origins=[],
    )
    await test_db_session.commit()

    resp = await client.get(f"/maps/shared/{raw_token}")
    assert resp.status_code == 200
    csp = resp.headers.get("content-security-policy", "")
    assert "frame-ancestors" in csp, f"Expected frame-ancestors in CSP, got: {csp!r}"
    assert "'self'" in csp, f"Expected 'self' in CSP when allowed_origins=[], got: {csp!r}"
    # Must NOT include any other origins beyond 'self'
    assert "http" not in csp.replace("'self'", ""), (
        f"Unexpected origins in CSP for empty allowed_origins, got: {csp!r}"
    )


# ---------------------------------------------------------------------------
# Task 2 — Middleware coexistence: XFO dropped when route sets CSP
# ---------------------------------------------------------------------------


async def test_shared_map_response_no_xfo_header(
    client: AsyncClient,
    test_db_session: AsyncSession,
):
    """GET /maps/shared/{token} must NOT carry X-Frame-Options after CSP is set."""
    admin_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_public_map(test_db_session, created_by=admin_id)
    raw_token = await _create_share_token(
        test_db_session, map_id=map_obj.id, created_by=admin_id
    )
    await _create_embed_token(
        test_db_session,
        map_id=map_obj.id,
        created_by=admin_id,
        allowed_origins=["https://partner.example"],
    )
    await test_db_session.commit()

    resp = await client.get(f"/maps/shared/{raw_token}")
    assert resp.status_code == 200
    assert "x-frame-options" not in resp.headers, (
        f"X-Frame-Options must be absent when route sets CSP, got: {resp.headers.get('x-frame-options')!r}"
    )


async def test_other_endpoint_still_has_xfo_deny(
    client: AsyncClient,
):
    """Public endpoint without route-level CSP still gets X-Frame-Options: DENY
    from SecurityHeadersMiddleware."""
    resp = await client.get("/auth/config/")
    # May 200 or 404 depending on the env; what matters is the header is present
    xfo = resp.headers.get("x-frame-options", "")
    assert xfo.upper() == "DENY", (
        f"Expected X-Frame-Options: DENY on non-CSP route, got: {xfo!r}"
    )


# ---------------------------------------------------------------------------
# Task 3 — E2E documentation: S08 test exists in sec-audit.spec.ts
# ---------------------------------------------------------------------------


def test_e2e_sec_audit_s08_skips_when_no_share_token():
    """Pin that e2e/sec-audit.spec.ts:182 contains the S08 block.

    The Playwright test requires SEC_AUDIT_SHARE_TOKEN to be set; pytest does
    not test the SPA HTML response (that is Playwright's job). This assertion
    documents the existence of the e2e coverage and guards against accidental
    deletion of the S08 test block.
    """
    import pathlib

    e2e_path = pathlib.Path(__file__).parents[2] / "e2e" / "sec-audit.spec.ts"
    assert e2e_path.exists(), f"sec-audit.spec.ts not found at {e2e_path}"
    content = e2e_path.read_text()
    assert "S08" in content, "S08 test block missing from e2e/sec-audit.spec.ts"
    assert "frame-ancestors" in content, (
        "frame-ancestors assertion missing from S08 block in sec-audit.spec.ts"
    )
