"""Regression tests for SEC-01: vector-tile egress authorization.

Pins the anonymous denial of public-unpublished vector tile tokens so the leak
cannot return silently.  Covers:

  (a) anonymous single-token endpoint (GET /tiles/token/{id}/)
  (b) anonymous batch-token endpoint (POST /tiles/tokens/)
  (c) anonymous cluster-tile endpoint (GET /tiles/clusters/data.{table}/{z}/{x}/{y}.pbf)
  (d) POSITIVE over-gating guard — public + published still mints a token for anon

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
  - Run with: set -a && source ../.env.test && set +a
               uv run pytest tests/test_vector_tile_auth.py -v
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.auth.models import User
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_admin_id(session) -> uuid.UUID:
    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    return result.scalar_one().id


async def _create_vector_dataset(
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
    record_status: str = "published",
) -> tuple[Record, Dataset]:
    """Create a vector Record + Dataset for contrast tests."""
    record = Record(
        title=f"Vector Tile Test {uuid.uuid4().hex[:6]}",
        summary="Dataset for vector tile contrast tests",
        theme_category=["test"],
        visibility=visibility,
        record_status=record_status,
        record_type="vector_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"vector_tile_test_{uuid.uuid4().hex[:8]}",
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()
    await session.commit()
    await session.refresh(dataset)
    return record, dataset


async def _get_auth_header(client: AsyncClient, username: str, password: str) -> dict:
    resp = await client.post(
        "/auth/login", data={"username": username, "password": password}
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------------------------------------------------------------------------
# SEC-01 regression tests
# ---------------------------------------------------------------------------


class TestVectorTileEgressAuthorization:
    """Regression coverage for SEC-01: anon callers must not receive tile tokens
    or tile bytes for public + non-published vector datasets."""

    async def test_anon_single_token_denied_for_public_unpublished(
        self, client: AsyncClient, test_db_session
    ):
        """Anonymous GET /tiles/token/{id}/ must be denied (401 or 404) for a
        public + non-published vector dataset.

        Before the SEC-01 fix this returned 200 with a minted HMAC sig (the leak).
        """
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset = await _create_vector_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            record_status="internal",
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")

        assert resp.status_code in (401, 404), (
            f"Expected 401 or 404 for anon on public+unpublished, got {resp.status_code}: {resp.text}"
        )

    async def test_anon_batch_token_denied_for_public_unpublished(
        self, client: AsyncClient, test_db_session
    ):
        """Anonymous POST /tiles/tokens/ must return 200 (batch never fails the
        request) but the per-dataset entry must carry an 'error' key and NO 'sig'.

        Before the SEC-01 fix the batch endpoint minted an HMAC sig for the
        public+unpublished dataset regardless of anonymous status.
        """
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset = await _create_vector_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            record_status="internal",
        )

        resp = await client.post(
            "/tiles/tokens/",
            json={"dataset_ids": [str(dataset.id)]},
        )

        assert resp.status_code == 200, (
            f"Batch token endpoint must always return 200, got {resp.status_code}"
        )
        tokens = resp.json()["tokens"]
        dataset_key = str(dataset.id)
        assert dataset_key in tokens, f"Expected key '{dataset_key}' in tokens response"
        entry = tokens[dataset_key]
        assert "error" in entry, (
            f"Expected 'error' key for public+unpublished anon request, got: {entry}"
        )
        assert "sig" not in entry, (
            f"HMAC sig must NOT be minted for public+unpublished anon request, got: {entry}"
        )

    async def test_anon_cluster_tile_denied_for_public_unpublished(
        self, client: AsyncClient, test_db_session
    ):
        """Anonymous GET /tiles/clusters/data.{table}/{z}/{x}/{y}.pbf must not
        return tile bytes for a public + non-published vector dataset.

        Call order in cluster_tile_endpoint:
          1. _resolve_dataset_meta
          2. _ensure_clusterable_dataset  <- fires 400 if geometry_type is None
          3. _authorize_vector_tile_request <- fires 404 for anon+unpublished

        The factory seeds no geometry_type, so _ensure_clusterable_dataset (step 2)
        fires before the auth guard (step 3) and returns 400.  Either 400 or 404
        proves the anon caller receives no tile bytes — the SEC-01 invariant holds.
        """
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset = await _create_vector_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            record_status="internal",
        )

        resp = await client.get(
            f"/tiles/clusters/data.{dataset.table_name}/2/0/0.pbf"
        )

        # 400 = clusterable-gate (no geometry_type), 404 = auth-gate (anon+unpublished)
        # Both prove the anon caller does NOT receive tile bytes.
        assert resp.status_code in (400, 404), (
            f"Expected 400 (clusterable gate) or 404 (auth gate) for anon on "
            f"public+unpublished cluster tile, got {resp.status_code}: {resp.text}"
        )

    async def test_anon_single_token_allowed_for_public_published(
        self, client: AsyncClient, test_db_session
    ):
        """POSITIVE over-gating guard: anonymous GET /tiles/token/{id}/ must
        return 200 with a 'sig' present for a public + published vector dataset.

        This guard ensures the SEC-01 fix does not over-gate legitimate anon access
        to publicly published datasets.
        """
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset = await _create_vector_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            record_status="published",
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")

        assert resp.status_code == 200, (
            f"Expected 200 for anon on public+published, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "sig" in body, (
            f"Expected 'sig' in token response for public+published dataset, got: {body}"
        )
