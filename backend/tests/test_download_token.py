"""Integration tests for POST /auth/download-token/{dataset_id}.

Covers:
  1. Happy path — authenticated owner of a public dataset receives 200 + valid token.
  2. Invalid dataset — random UUID returns 404.
  3. Private non-owner — non-owner editor hitting private dataset returns 404.
  4. Anonymous public — unauthenticated request to public dataset returns 200.
  5. Anonymous private — unauthenticated request to private dataset returns 404.
"""

import uuid

import jwt
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import _create_test_user, get_auth_header
from tests.factories import create_dataset


class TestDownloadTokenEndpoint:
    async def test_download_token_happy_path(
        self, client: AsyncClient, admin_auth_header, test_db_session
    ):
        """Owner of a public dataset receives 200 + download-scoped JWT."""
        from app.modules.auth.models import User
        from sqlalchemy import select

        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()

        dataset = await create_dataset(
            test_db_session, created_by=admin.id, visibility="public"
        )

        resp = await client.post(
            f"/auth/download-token/{dataset.id}", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "token" in body
        assert body["expires_in"] == 120

        # Decode and validate token claims
        payload = jwt.decode(
            body["token"],
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        assert payload["typ"] == "download"
        assert payload["scope"] == f"dataset:{dataset.id}"
        # exp - iat <= 120s
        assert payload["exp"] - payload["iat"] <= 120

    async def test_download_token_invalid_dataset(
        self, client: AsyncClient, admin_auth_header
    ):
        """A non-existent dataset UUID returns 404."""
        fake_id = uuid.uuid4()
        resp = await client.post(
            f"/auth/download-token/{fake_id}", headers=admin_auth_header
        )
        assert resp.status_code == 404

    async def test_download_token_private_non_owner(
        self, client: AsyncClient, admin_auth_header, test_db_session
    ):
        """An editor who does not own a private dataset gets 404."""
        from app.modules.auth.models import User
        from sqlalchemy import select

        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()

        # Create private dataset owned by admin
        dataset = await create_dataset(
            test_db_session, created_by=admin.id, visibility="private"
        )

        # Create a separate editor user
        editor_headers, _ = await _create_test_user(
            client, admin_auth_header, "editor"
        )

        resp = await client.post(
            f"/auth/download-token/{dataset.id}", headers=editor_headers
        )
        assert resp.status_code == 404

    async def test_download_token_anonymous_public(
        self, client: AsyncClient, test_db_session, admin_auth_header
    ):
        """Anonymous request to a public dataset returns 200 + valid download token."""
        from app.modules.auth.models import User
        from sqlalchemy import select

        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()

        dataset = await create_dataset(
            test_db_session, created_by=admin.id, visibility="public"
        )

        # No auth headers — anonymous
        resp = await client.post(f"/auth/download-token/{dataset.id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "token" in body
        assert body["expires_in"] == 120

        # Anonymous tokens must also be type=download and scope-bound
        payload = jwt.decode(
            body["token"],
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        assert payload["typ"] == "download"
        assert payload["scope"] == f"dataset:{dataset.id}"

    async def test_download_token_anonymous_private(
        self, client: AsyncClient, test_db_session, admin_auth_header
    ):
        """Anonymous request to a private dataset returns 404."""
        from app.modules.auth.models import User
        from sqlalchemy import select

        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()

        dataset = await create_dataset(
            test_db_session, created_by=admin.id, visibility="private"
        )

        resp = await client.post(f"/auth/download-token/{dataset.id}")
        assert resp.status_code == 404
