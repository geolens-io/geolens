"""Record sub-resource edit contracts (fix(#458 E-45/E-46/E-47)).

Covers the update-path gaps the 2026-07-16 editing audit found:
- E-45: DistributionUpdate.url gets the same HTTP(S) validation as create.
- E-46: PATCH clears optional fields with an explicit null (dataset E-04
  contract); non-nullable fields 422 instead of silently dropping the null.
- E-47: sub-resource writes emit metadata.edit audit events into the backing
  dataset's history.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.factories import create_dataset, get_user_id


async def _dataset_and_record(test_db_session, admin_id: uuid.UUID):
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"Subresource Edits {uuid.uuid4().hex[:6]}",
    )
    return ds.id, ds.record_id


async def _create_contact(client: AsyncClient, record_id, headers) -> str:
    resp = await client.post(
        f"/records/{record_id}/contacts/",
        json={
            "role": "pointOfContact",
            "name": "Jane Doe",
            "email": "jane@example.com",
            "organization": "Example Org",
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _create_distribution(client: AsyncClient, record_id, headers) -> str:
    resp = await client.post(
        f"/records/{record_id}/distributions/",
        json={
            "distribution_type": "download",
            "format": "GeoJSON",
            "url": "https://example.com/data.geojson",
            "title": "Download",
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


@pytest.mark.anyio
async def test_distribution_update_rejects_non_http_url(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """fix(#458 E-45): the update path validates URLs like the create path."""
    admin_id = await get_user_id(test_db_session, "admin")
    _, record_id = await _dataset_and_record(test_db_session, admin_id)
    dist_id = await _create_distribution(client, record_id, admin_auth_header)

    resp = await client.patch(
        f"/records/{record_id}/distributions/{dist_id}/",
        json={"url": "javascript:alert(1)"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, resp.text

    resp = await client.patch(
        f"/records/{record_id}/distributions/{dist_id}/",
        json={"url": "https://example.com/updated.geojson"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"] == "https://example.com/updated.geojson"


@pytest.mark.anyio
async def test_contact_patch_clears_optional_field_with_null(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """fix(#458 E-46): an explicit null clears optional fields; it used to be
    silently dropped by double exclude_none."""
    admin_id = await get_user_id(test_db_session, "admin")
    _, record_id = await _dataset_and_record(test_db_session, admin_id)
    contact_id = await _create_contact(client, record_id, admin_auth_header)

    resp = await client.patch(
        f"/records/{record_id}/contacts/{contact_id}/",
        json={"email": None},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] is None

    # Omitted fields stay untouched.
    assert resp.json()["organization"] == "Example Org"


@pytest.mark.anyio
async def test_contact_patch_null_role_is_422(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """fix(#458 E-46): role is NOT NULL — explicit null is a 422, not a drop."""
    admin_id = await get_user_id(test_db_session, "admin")
    _, record_id = await _dataset_and_record(test_db_session, admin_id)
    contact_id = await _create_contact(client, record_id, admin_auth_header)

    resp = await client.patch(
        f"/records/{record_id}/contacts/{contact_id}/",
        json={"role": None},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.anyio
async def test_distribution_patch_null_url_is_422(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """fix(#458 E-46): the NOT NULL trio (type/format/url) rejects explicit null."""
    admin_id = await get_user_id(test_db_session, "admin")
    _, record_id = await _dataset_and_record(test_db_session, admin_id)
    dist_id = await _create_distribution(client, record_id, admin_auth_header)

    resp = await client.patch(
        f"/records/{record_id}/distributions/{dist_id}/",
        json={"url": None},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, resp.text

    # Optional field still clearable.
    resp = await client.patch(
        f"/records/{record_id}/distributions/{dist_id}/",
        json={"title": None},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] is None


@pytest.mark.anyio
async def test_subresource_write_appears_in_dataset_history(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """fix(#458 E-47): sub-resource writes emit metadata.edit audit events into
    the backing dataset's history like top-level metadata PATCHes do."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset_id, record_id = await _dataset_and_record(test_db_session, admin_id)

    resp = await client.post(
        f"/records/{record_id}/keywords/",
        json={"keyword": "audit-trail", "keyword_type": "theme"},
        headers=admin_auth_header,
    )
    assert resp.status_code in (200, 201), resp.text

    resp = await client.get(
        f"/datasets/{dataset_id}/history",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    keyword_events = [
        log
        for log in resp.json()["logs"]
        if log["action"] == "metadata.edit"
        and (log.get("details") or {}).get("resource") == "keyword"
    ]
    assert keyword_events, resp.json()["logs"]
    assert keyword_events[0]["details"]["op"] == "create"
    assert keyword_events[0]["details"]["keyword"] == "audit-trail"
