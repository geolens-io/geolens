"""SEC-04: Download endpoint requires a download-scoped JWT on ?token=.

Pins the v13.13 closure of M-66. The session JWT continues to work via the
Authorization header — only the URL-borne ?token= lane is restricted to
typ='download' tokens with explicit dataset scope and ≤2-minute TTL.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.modules.auth.providers import AuthenticatedIdentity
from app.modules.auth.service import AuthService
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
    resp = await client.get(f"/datasets/{fake_dataset}/download/cog?token={session_jwt}")
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
