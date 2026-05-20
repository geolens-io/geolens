"""Tests for SEC-S05 — /datasets/{id}/related/ visibility bypass (Phase 1061).

Verifies that anonymous and non-owner authenticated requests on a private
dataset's /related/ endpoint return 404, preventing the cosine-similarity
oracle on the seed's RecordEmbedding.

Also covers Phase 1061 WR-02: /datasets/{id}/maps/ dataset-existence oracle
(anonymous callers should not be able to confirm a private dataset UUID exists
by probing the maps endpoint).

All tests follow the factory + auth pattern established in
test_ogc_public_access.py.
"""

import uuid

import pytest
from httpx import AsyncClient

from .conftest import _create_test_user, get_auth_header
from tests.factories import create_dataset, get_user_id
from app.core.config import settings


# ---------------------------------------------------------------------------
# 1. Anonymous GET on private dataset → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_related_anonymous_private_returns_404(
    client: AsyncClient,
    test_db_session,
):
    """Anonymous GET /datasets/{private_id}/related/ returns 404."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    priv = await create_dataset(
        session,
        created_by=admin_id,
        name="S05 private seed",
        visibility="private",
    )
    resp = await client.get(f"/datasets/{priv.id}/related/")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2. Anonymous GET on nonexistent UUID → 404  (timing-uniform pin)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_related_anonymous_nonexistent_returns_404(
    client: AsyncClient,
):
    """Anonymous GET /datasets/{random_uuid}/related/ returns 404 (timing-uniform pin)."""
    resp = await client.get(f"/datasets/{uuid.uuid4()}/related/")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3. Anonymous GET on public dataset → 200  (existing behaviour preserved)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_related_anonymous_public_returns_200(
    client: AsyncClient,
    test_db_session,
):
    """Anonymous GET /datasets/{public_id}/related/ returns 200 (no embeddings → empty list)."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    pub = await create_dataset(
        session,
        created_by=admin_id,
        name="S05 public seed",
        visibility="public",
    )
    resp = await client.get(f"/datasets/{pub.id}/related/")
    assert resp.status_code == 200
    body = resp.json()
    # No embedding model running in test env — items is empty list, total >= 0
    assert "items" in body
    assert "total" in body
    assert body["total"] >= 0


# ---------------------------------------------------------------------------
# 4. Authenticated owner GET on their private dataset → 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_related_owner_private_returns_200(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Authenticated owner GET /datasets/{owned_private_id}/related/ returns 200."""
    session = test_db_session

    # Create editor_a (the owner)
    editor_a_headers, editor_a_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    editor_a_id = uuid.UUID(editor_a_id_str)

    priv = await create_dataset(
        session,
        created_by=editor_a_id,
        name="S05 owner private",
        visibility="private",
    )

    resp = await client.get(
        f"/datasets/{priv.id}/related/",
        headers=editor_a_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert body["total"] >= 0


# ---------------------------------------------------------------------------
# 5. Authenticated non-owner GET on another user's private dataset → 404
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_related_non_owner_private_returns_404(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Authenticated editor_b GET /datasets/{editor_a_private_id}/related/ returns 404."""
    session = test_db_session

    # Create editor_a (the owner) and editor_b (the attacker)
    editor_a_headers, editor_a_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    editor_b_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    editor_a_id = uuid.UUID(editor_a_id_str)

    priv = await create_dataset(
        session,
        created_by=editor_a_id,
        name="S05 non-owner probe",
        visibility="private",
    )

    resp = await client.get(
        f"/datasets/{priv.id}/related/",
        headers=editor_b_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# WR-02: /datasets/{id}/maps/ — anonymous cannot enumerate private dataset
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_maps_anonymous_private_returns_404(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Anonymous GET /datasets/{private_id}/maps/ returns 404.

    Phase 1061 WR-02 regression: without check_dataset_access_or_anonymous,
    an anonymous caller could confirm a private dataset UUID exists by
    probing /maps/ — a dataset-existence oracle analogous to SEC-S05.
    """
    session = test_db_session

    editor_a_headers, editor_a_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    private = await create_dataset(
        session,
        created_by=uuid.UUID(editor_a_id_str),
        name="WR-02 private maps probe",
        visibility="private",
    )

    # Anonymous caller should get 404, not an empty list
    resp = await client.get(f"/datasets/{private.id}/maps/")
    assert resp.status_code == 404
