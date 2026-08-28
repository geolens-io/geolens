"""Behavioral tests for the `restrict_public_visibility` setting (feat #1691).

When the instance setting is ON, only admins may set `visibility: public`;
non-admin requests get a 403 from the ONE shared gate
(`check_public_visibility_allowed` in catalog/authorization.py). Default OFF
preserves current behavior, and existing public content is untouched — the
gate fires only on a mutation that REQUESTS public.

Structural coverage (every visibility-writing route calls the gate) lives in
test_visibility_gate_structural.py; this file proves the gate's runtime
behavior on representative surfaces: dataset metadata PATCH, map update, and
the ingest register/bulk-register/VRT-create + STAC-import request-time
checks (which fire before any work happens).
"""

import uuid

import pytest
from httpx import AsyncClient

from .conftest import _create_test_user
from tests.factories import create_dataset, create_map_via_api


@pytest.fixture
def _restrict_public_visibility(monkeypatch):
    """Flip the restrict_public_visibility flag ON for one test.

    Mirrors conftest's `_enable_dataset_editing` stub pattern: the gate
    re-imports `RESTRICT_PUBLIC_VISIBILITY` from the module on each call, so
    replacing the module attribute is picked up and the gate's real
    role-resolution branch still runs.
    """
    import app.core.persistent_config as pc

    import app.modules.settings.router_public as rp

    class _AlwaysOn:
        async def get(self, _db):
            return True

    stub = _AlwaysOn()
    monkeypatch.setattr(pc, "RESTRICT_PUBLIC_VISIBILITY", stub)
    # router_public binds the name at import time (module-level `from` import),
    # so its feature-flags endpoint needs the module-local binding patched too.
    monkeypatch.setattr(rp, "RESTRICT_PUBLIC_VISIBILITY", stub)


# ---------------------------------------------------------------------------
# Dataset metadata PATCH
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_default_off_editor_can_publish_public(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """With the setting at its default (OFF) nothing changes for editors."""
    editor_headers, editor_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    ds = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(editor_id),
        name="editor goes public",
        visibility="private",
    )
    resp = await client.patch(
        f"/datasets/{ds.id}", json={"visibility": "public"}, headers=editor_headers
    )
    assert resp.status_code == 200
    assert resp.json()["visibility"] == "public"


@pytest.mark.anyio
async def test_restricted_editor_public_patch_403(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    _restrict_public_visibility,
):
    editor_headers, editor_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    ds = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(editor_id),
        name="editor blocked from public",
        visibility="private",
    )
    resp = await client.patch(
        f"/datasets/{ds.id}", json={"visibility": "public"}, headers=editor_headers
    )
    assert resp.status_code == 403
    assert "restricted to administrators" in resp.json()["detail"]


@pytest.mark.anyio
async def test_restricted_editor_internal_patch_ok(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    _restrict_public_visibility,
):
    """Only `public` is gated — non-admins keep every narrower visibility."""
    editor_headers, editor_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    ds = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(editor_id),
        name="internal stays available",
        visibility="private",
    )
    resp = await client.patch(
        f"/datasets/{ds.id}", json={"visibility": "internal"}, headers=editor_headers
    )
    assert resp.status_code == 200
    assert resp.json()["visibility"] == "internal"


@pytest.mark.anyio
async def test_restricted_admin_public_patch_ok(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    _restrict_public_visibility,
):
    ds = await create_dataset(
        test_db_session,
        created_by=None,
        name="admin publishes",
        visibility="private",
    )
    resp = await client.patch(
        f"/datasets/{ds.id}", json={"visibility": "public"}, headers=admin_auth_header
    )
    assert resp.status_code == 200
    assert resp.json()["visibility"] == "public"


@pytest.mark.anyio
async def test_restricted_existing_public_content_untouched(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    _restrict_public_visibility,
):
    """A non-admin can still edit OTHER metadata on an already-public dataset
    (no visibility in the body), and the dataset stays public — enabling the
    setting never retroactively narrows anything."""
    editor_headers, editor_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    ds = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(editor_id),
        name="already public",
        visibility="public",
    )
    resp = await client.patch(
        f"/datasets/{ds.id}", json={"summary": "still editable"}, headers=editor_headers
    )
    assert resp.status_code == 200
    assert resp.json()["visibility"] == "public"


# ---------------------------------------------------------------------------
# Map update
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_restricted_editor_map_public_403(
    client: AsyncClient, admin_auth_header: dict, _restrict_public_visibility
):
    editor_headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    map_obj = await create_map_via_api(client, editor_headers)
    resp = await client.put(
        f"/maps/{map_obj['id']}", json={"visibility": "public"}, headers=editor_headers
    )
    assert resp.status_code == 403
    assert "restricted to administrators" in resp.json()["detail"]


@pytest.mark.anyio
async def test_restricted_editor_map_internal_ok(
    client: AsyncClient, admin_auth_header: dict, _restrict_public_visibility
):
    editor_headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    map_obj = await create_map_via_api(client, editor_headers)
    resp = await client.put(
        f"/maps/{map_obj['id']}",
        json={"visibility": "internal"},
        headers=editor_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["visibility"] == "internal"


@pytest.mark.anyio
async def test_restricted_admin_map_public_ok(
    client: AsyncClient, admin_auth_header: dict, _restrict_public_visibility
):
    map_obj = await create_map_via_api(client, admin_auth_header)
    resp = await client.put(
        f"/maps/{map_obj['id']}",
        json={"visibility": "public"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    assert resp.json()["visibility"] == "public"


# ---------------------------------------------------------------------------
# Ingest surfaces — the gate fires at request time, before any work
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_restricted_editor_register_public_403(
    client: AsyncClient, admin_auth_header: dict, _restrict_public_visibility
):
    """The register gate runs before the table is even looked up, so the
    table does not need to exist for the 403 to prove the surface."""
    editor_headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    resp = await client.post(
        "/ingest/register/",
        json={
            "table_name": "no_such_table_1691",
            "title": "Blocked register",
            "visibility": "public",
        },
        headers=editor_headers,
    )
    assert resp.status_code == 403
    assert "restricted to administrators" in resp.json()["detail"]


@pytest.mark.anyio
async def test_restricted_editor_bulk_register_public_403(
    client: AsyncClient, admin_auth_header: dict, _restrict_public_visibility
):
    """One public item rejects the whole batch up front (403, nothing partial)."""
    editor_headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    resp = await client.post(
        "/ingest/register/bulk/",
        json={
            "tables": [
                {
                    "table_name": "t_private_1691",
                    "title": "Private item",
                    "visibility": "private",
                },
                {
                    "table_name": "t_public_1691",
                    "title": "Public item",
                    "visibility": "public",
                },
            ]
        },
        headers=editor_headers,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_restricted_editor_vrt_create_public_403(
    client: AsyncClient, admin_auth_header: dict, _restrict_public_visibility
):
    editor_headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    resp = await client.post(
        "/ingest/vrt/create",
        json={
            "title": "blocked vrt",
            "source_dataset_ids": [str(uuid.uuid4())],
            "vrt_type": "mosaic",
            "resolution_strategy": "finest",
            "visibility": "public",
        },
        headers=editor_headers,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_restricted_editor_stac_import_public_403(
    client: AsyncClient, admin_auth_header: dict, _restrict_public_visibility
):
    editor_headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    resp = await client.post(
        "/services/stac/import",
        json={
            "url": "https://stac.example.com/api",
            "visibility": "public",
            "items": [
                {
                    "id": "item-1691",
                    "title": "Blocked import",
                    "data_asset_href": "https://stac.example.com/cog.tif",
                }
            ],
        },
        headers=editor_headers,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_restricted_admin_register_public_passes_gate(
    client: AsyncClient, admin_auth_header: dict, _restrict_public_visibility
):
    """Admin passes the gate; the request then fails on the missing table
    with a 400 (NOT the gate's 403), proving the gate is role-sensitive."""
    resp = await client.post(
        "/ingest/register/",
        json={
            "table_name": "no_such_table_1691_admin",
            "title": "Admin register",
            "visibility": "public",
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Feature flag exposure
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_feature_flags_expose_restrict_public_visibility(
    client: AsyncClient, _restrict_public_visibility
):
    resp = await client.get("/settings/feature-flags/")
    assert resp.status_code == 200
    assert resp.json()["restrict_public_visibility"] is True


@pytest.mark.anyio
async def test_feature_flags_default_off(client: AsyncClient):
    resp = await client.get("/settings/feature-flags/")
    assert resp.status_code == 200
    assert resp.json()["restrict_public_visibility"] is False
