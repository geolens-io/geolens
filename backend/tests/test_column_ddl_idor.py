"""Tests for SEC-S03 — column DDL IDOR (Phase 1061).

Verifies that editor B cannot mutate columns on editor A's private dataset
via POST/PATCH/DELETE /layers/{id}/columns/*.
Also verifies that the owner retains full access (no over-restriction).
"""

import uuid

import pytest
from httpx import AsyncClient

from .conftest import _create_test_user
from tests.factories import create_dataset


async def _create_layer_for_user(
    client: AsyncClient,
    user_headers: dict,
    *,
    title: str,
) -> str:
    """Create a layer via the API as a specific user, return dataset id."""
    resp = await client.post(
        "/layers/",
        json={
            "title": title,
            "geometry_type": "Point",
            "columns": [
                {"name": "label", "type": "text"},
                {"name": "score", "type": "real"},
            ],
        },
        headers=user_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# SEC-S03: deny-paths — editor B cannot perform DDL on editor A's dataset
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_add_column_other_user_private_returns_404(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Editor B cannot add a column to editor A's private dataset."""
    editor_a_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    editor_b_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    dataset_id = await _create_layer_for_user(
        client, editor_a_headers, title="S03 add col target"
    )

    resp = await client.post(
        f"/layers/{dataset_id}/columns/",
        json={"column": {"name": "injected_col", "type": "text"}},
        headers=editor_b_headers,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_rename_column_other_user_private_returns_404(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Editor B cannot rename a column on editor A's private dataset."""
    editor_a_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    editor_b_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    dataset_id = await _create_layer_for_user(
        client, editor_a_headers, title="S03 rename col target"
    )

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/label/name",
        json={"new_name": "hacked_label"},
        headers=editor_b_headers,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_alter_column_type_other_user_private_returns_404(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Editor B cannot alter a column type on editor A's private dataset."""
    editor_a_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    editor_b_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    dataset_id = await _create_layer_for_user(
        client, editor_a_headers, title="S03 alter type target"
    )

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/score/type",
        json={"new_type": "text"},
        headers=editor_b_headers,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_drop_column_other_user_private_returns_404(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Editor B cannot drop a column from editor A's private dataset."""
    editor_a_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    editor_b_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    dataset_id = await _create_layer_for_user(
        client, editor_a_headers, title="S03 drop col target"
    )

    resp = await client.delete(
        f"/layers/{dataset_id}/columns/label",
        headers=editor_b_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# SEC-S03: owner-allow-paths — editor A retains DDL on their own dataset
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_add_column_owner_returns_201(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Editor A can add a column to their own dataset (no over-restriction regression)."""
    editor_a_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    dataset_id = await _create_layer_for_user(
        client, editor_a_headers, title="S03 owner add col"
    )

    resp = await client.post(
        f"/layers/{dataset_id}/columns/",
        json={"column": {"name": "extra_col", "type": "text"}},
        headers=editor_a_headers,
    )
    assert resp.status_code == 201


@pytest.mark.anyio
async def test_rename_column_owner_returns_200(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Editor A can rename a column on their own dataset (no over-restriction regression)."""
    editor_a_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    dataset_id = await _create_layer_for_user(
        client, editor_a_headers, title="S03 owner rename col"
    )

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/label/name",
        json={"new_name": "renamed_label"},
        headers=editor_a_headers,
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_alter_column_type_owner_returns_200(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Editor A can alter a column type on their own dataset (no over-restriction regression)."""
    editor_a_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    dataset_id = await _create_layer_for_user(
        client, editor_a_headers, title="S03 owner alter type"
    )

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/score/type",
        json={"new_type": "integer"},
        headers=editor_a_headers,
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_drop_column_owner_returns_200(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Editor A can drop a column from their own dataset (no over-restriction regression)."""
    editor_a_headers, _ = await _create_test_user(
        client, admin_auth_header, "editor"
    )

    dataset_id = await _create_layer_for_user(
        client, editor_a_headers, title="S03 owner drop col"
    )

    resp = await client.delete(
        f"/layers/{dataset_id}/columns/score",
        headers=editor_a_headers,
    )
    assert resp.status_code == 200
