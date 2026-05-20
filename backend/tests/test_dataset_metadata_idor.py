"""Tests for SEC-S02 — dataset metadata mutation IDOR (Phase 1061).

Verifies that editor B cannot mutate editor A's private dataset metadata
via PATCH /datasets/{id}, DELETE /datasets/{id}, or POST /datasets/bulk-delete/.
Also verifies that the owner and admin retain full access (no over-restriction).
"""

import json
import uuid

import pytest
from httpx import AsyncClient

from .conftest import _create_test_user
from tests.factories import create_dataset


# ---------------------------------------------------------------------------
# SEC-S02: PATCH /datasets/{id} — unauthorized editor B is denied
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_patch_dataset_other_user_private_returns_404(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Editor B cannot PATCH editor A's private dataset."""
    session = test_db_session

    editor_a_headers, editor_a_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    editor_b_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    private = await create_dataset(
        session,
        created_by=uuid.UUID(editor_a_id_str),
        name="A private dataset",
        visibility="private",
    )

    resp = await client.patch(
        f"/datasets/{private.id}",
        json={"title": "compromised"},
        headers=editor_b_headers,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_patch_dataset_owner_private_returns_200(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Editor A can PATCH their own private dataset (no over-restriction regression)."""
    session = test_db_session

    editor_a_headers, editor_a_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    private = await create_dataset(
        session,
        created_by=uuid.UUID(editor_a_id_str),
        name="Owner private dataset",
        visibility="private",
    )

    resp = await client.patch(
        f"/datasets/{private.id}",
        json={"title": "Updated by owner"},
        headers=editor_a_headers,
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# SEC-S02: DELETE /datasets/{id} — unauthorized editor B is denied
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_dataset_other_user_private_returns_404(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Editor B cannot DELETE editor A's private dataset."""
    session = test_db_session

    editor_a_headers, editor_a_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    editor_b_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    private = await create_dataset(
        session,
        created_by=uuid.UUID(editor_a_id_str),
        name="A private dataset to protect",
        visibility="private",
    )

    resp = await client.request(
        "DELETE",
        f"/datasets/{private.id}",
        content=json.dumps({"confirm_title": "A private dataset to protect"}),
        headers={**editor_b_headers, "Content-Type": "application/json"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_delete_dataset_other_user_public_returns_403(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Editor B cannot DELETE editor A's PUBLIC dataset (owner-or-admin gate)."""
    session = test_db_session

    editor_a_headers, editor_a_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    editor_b_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    public_ds = await create_dataset(
        session,
        created_by=uuid.UUID(editor_a_id_str),
        name="A public dataset to protect",
        visibility="public",
    )

    resp = await client.request(
        "DELETE",
        f"/datasets/{public_ds.id}",
        content=json.dumps({"confirm_title": "A public dataset to protect"}),
        headers={**editor_b_headers, "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_delete_dataset_owner_returns_204(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Editor A can DELETE their own dataset (no over-restriction regression)."""
    session = test_db_session

    editor_a_headers, editor_a_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    ds = await create_dataset(
        session,
        created_by=uuid.UUID(editor_a_id_str),
        name="Owner deletes own dataset",
        visibility="private",
    )

    resp = await client.request(
        "DELETE",
        f"/datasets/{ds.id}",
        content=json.dumps({"confirm_title": "Owner deletes own dataset"}),
        headers={**editor_a_headers, "Content-Type": "application/json"},
    )
    assert resp.status_code == 204


@pytest.mark.anyio
async def test_delete_dataset_admin_returns_204(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Admin can DELETE any user's dataset (admin override preserved)."""
    session = test_db_session

    editor_a_headers, editor_a_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    ds = await create_dataset(
        session,
        created_by=uuid.UUID(editor_a_id_str),
        name="Admin deletes other dataset",
        visibility="private",
    )

    resp = await client.request(
        "DELETE",
        f"/datasets/{ds.id}",
        content=json.dumps({"confirm_title": "Admin deletes other dataset"}),
        headers={**admin_auth_header, "Content-Type": "application/json"},
    )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# SEC-S02: POST /datasets/bulk-delete/ — unauthorized items yield per-item error
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_bulk_delete_skips_unauthorized_items(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Editor B bulk-deletes with editor A's private dataset id — deleted=0, per-item error."""
    session = test_db_session

    editor_a_headers, editor_a_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    editor_b_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    private = await create_dataset(
        session,
        created_by=uuid.UUID(editor_a_id_str),
        name="Bulk protected dataset",
        visibility="private",
    )

    resp = await client.post(
        "/datasets/bulk-delete/",
        json={
            "datasets": [
                {
                    "dataset_id": str(private.id),
                    "confirm_title": "Bulk protected dataset",
                }
            ]
        },
        headers=editor_b_headers,
    )
    # Accepted with per-item error (not a batch abort) OR rejected entirely
    assert resp.status_code in (200, 207)
    body = resp.json()
    assert body["deleted"] == 0
    assert body["errors"] >= 1


# ---------------------------------------------------------------------------
# SEC-S02 / CR-01: PATCH /datasets/{id}/status/ and /{id}/target-status/ IDOR
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_publication_status_other_user_private_returns_404(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Editor B cannot promote editor A's private dataset via /status/ endpoint.

    Phase 1061 CR-01 regression: require_permission("edit_metadata") is
    role-level only.  Without check_dataset_access any editor could publish
    another user's private dataset.
    """
    session = test_db_session

    editor_a_headers, editor_a_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    editor_b_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    private = await create_dataset(
        session,
        created_by=uuid.UUID(editor_a_id_str),
        name="A private status dataset",
        visibility="private",
    )

    resp = await client.patch(
        f"/datasets/{private.id}/status/",
        json={"status": "ready"},
        headers=editor_b_headers,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_set_target_status_other_user_private_returns_404(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Editor B cannot walk editor A's private dataset to published via /target-status/.

    Phase 1061 CR-01 regression: without check_dataset_access the full
    draft→published chain would execute without ownership verification.
    """
    session = test_db_session

    editor_a_headers, editor_a_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    editor_b_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    private = await create_dataset(
        session,
        created_by=uuid.UUID(editor_a_id_str),
        name="A private target-status dataset",
        visibility="private",
    )

    resp = await client.patch(
        f"/datasets/{private.id}/target-status/",
        json={"status": "published"},
        headers=editor_b_headers,
    )
    assert resp.status_code == 404
