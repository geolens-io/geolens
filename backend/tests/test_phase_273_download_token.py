"""SEC-04: Download endpoint requires a download-scoped JWT on ?token=.

Pins the v13.13 closure of M-66. The session JWT continues to work via the
Authorization header — only the URL-borne ?token= lane is restricted to
typ='download' tokens with explicit dataset scope and ≤2-minute TTL.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from starlette.requests import Request
from unittest.mock import AsyncMock
from urllib.parse import urlencode

from app.core.config import settings
from app.core.db.tenant_session import current_tenant_var
from app.modules.auth.providers import AuthenticatedIdentity
from app.modules.auth.service import AuthService
from app.modules.catalog.datasets.api.router_export import _resolve_download_user
from tests.factories import get_user_id


def _decode(token: str) -> dict:
    return jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )


async def test_create_download_token_has_typ_and_scope(test_db_session):
    """create_download_token emits typ='download', scope='dataset:<id>', exp ≤ 120s."""
    user_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    identity = AuthenticatedIdentity(user_id=user_id, username="alice")
    svc = AuthService(test_db_session)
    token = svc.create_download_token(identity, dataset_id)
    payload = _decode(token)
    assert payload["typ"] == "download"
    assert payload["scope"] == f"dataset:{dataset_id}"
    assert payload["sub"] == str(user_id)
    assert "tid" not in payload
    # exp - iat ≤ 120 seconds
    assert payload["exp"] - payload["iat"] <= 120


async def test_create_download_token_caps_ttl_at_120s(test_db_session):
    """expire_seconds > 120 is silently capped to 120."""
    identity = AuthenticatedIdentity(user_id=uuid.uuid4(), username="alice")
    svc = AuthService(test_db_session)
    token = svc.create_download_token(identity, uuid.uuid4(), expire_seconds=99999)
    payload = _decode(token)
    assert payload["exp"] - payload["iat"] <= 120


async def test_session_jwt_rejected_on_download_query_param(
    client: AsyncClient, admin_auth_header
):
    """A session JWT (no typ='download') presented as ?token= is rejected."""
    # admin_auth_header is "Bearer <session_jwt>" — strip the prefix
    session_jwt = admin_auth_header["Authorization"].removeprefix("Bearer ")
    fake_dataset = uuid.uuid4()
    resp = await client.get(
        f"/datasets/{fake_dataset}/download/cog?token={session_jwt}"
    )
    assert resp.status_code == 401
    detail = resp.json()["detail"].lower()
    assert "download-scoped" in detail or "typ" in detail or "download" in detail


async def test_download_token_for_wrong_dataset_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """A download token scoped to dataset A presented to dataset B's URL fails."""
    admin_id = await get_user_id(test_db_session, settings.geolens_admin_username)
    identity = AuthenticatedIdentity(
        user_id=admin_id, username=settings.geolens_admin_username
    )
    svc = AuthService(test_db_session)
    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()
    token = svc.create_download_token(identity, dataset_a)
    resp = await client.get(f"/datasets/{dataset_b}/download/cog?token={token}")
    assert resp.status_code == 401
    assert "scope" in resp.json()["detail"].lower()


async def test_expired_download_token_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """A download token with exp in the past is rejected."""
    admin_id = await get_user_id(test_db_session, settings.geolens_admin_username)
    expired = jwt.encode(
        {
            "sub": str(admin_id),
            "username": settings.geolens_admin_username,
            "typ": "download",
            "scope": f"dataset:{uuid.uuid4()}",
            "exp": datetime.now(UTC) - timedelta(seconds=10),
            "iat": datetime.now(UTC) - timedelta(seconds=130),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    resp = await client.get(f"/datasets/{uuid.uuid4()}/download/cog?token={expired}")
    assert resp.status_code == 401


async def test_session_jwt_in_authorization_header_still_works(
    client: AsyncClient, admin_auth_header
):
    """Bearer header path continues to accept session JWTs (backward compat).

    The download endpoint will return 404 for a non-existent dataset — but
    that's authorization-passed-then-not-found, NOT a 401 from the validator.
    """
    fake_dataset = uuid.uuid4()
    resp = await client.get(
        f"/datasets/{fake_dataset}/download/cog", headers=admin_auth_header
    )
    # Specifically NOT 401 (auth passed). Likely 404 (dataset not found) or
    # 403 (missing export permission). Both are acceptable outcomes here.
    assert resp.status_code != 401


async def test_multi_tenant_download_token_requires_and_emits_tenant(
    test_db_session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")
    identity = AuthenticatedIdentity(user_id=uuid.uuid4(), username="alice")
    dataset_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    service = AuthService(test_db_session)

    with pytest.raises(ValueError, match="without a tenant id"):
        service.create_download_token(identity, dataset_id)

    payload = _decode(
        service.create_download_token(identity, dataset_id, tenant_id=tenant_id)
    )
    assert payload["tid"] == str(tenant_id)


async def test_multi_tenant_download_token_rejects_wrong_host(
    test_db_session,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")
    dataset_id = uuid.uuid4()
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    token = AuthService(test_db_session).create_download_token(
        AuthenticatedIdentity(user_id=uuid.uuid4(), username="alice"),
        dataset_id,
        tenant_id=tenant_a,
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/datasets/{dataset_id}/download/cog",
            "path_params": {"dataset_id": dataset_id},
            "query_string": urlencode({"token": token}).encode(),
            "headers": [],
        }
    )
    context_token = current_tenant_var.set(str(tenant_b))
    try:
        with pytest.raises(HTTPException) as exc_info:
            await _resolve_download_user(request, AsyncMock(), None)
    finally:
        current_tenant_var.reset(context_token)

    assert exc_info.value.status_code == 401
    assert "invalid or expired" in str(exc_info.value.detail).lower()
