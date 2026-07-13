"""DB-backed regression tests for record sub-resource read authorization (SEC-001).

SEC-001 (HIGH; public-repo Critical): the three `GET /records/{id}/{contacts,
keywords,distributions}` endpoints gated read access only on `user is None`, so
ANY authenticated user — including the lowest-privilege viewer — could read any
PRIVATE record's contact PII (name/email/phone/organization), keywords, and
distribution URLs by record UUID. The fix delegates to the dataset's per-dataset
RBAC (`check_dataset_access_or_anonymous`), mirroring the dataset read endpoints.

The ATTACK tests fail on main (a non-owner viewer gets 200 + the seeded PII); the
anonymous CONTROL and the owner/admin/public GUARD tests pass before and after.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from httpx import AsyncClient

from app.modules.catalog.datasets.domain.models import RecordContact
from tests.factories import create_dataset

from .conftest import _create_test_user

_SUBRESOURCES = ["contacts", "keywords", "distributions", "translations"]
_LEAK_EMAIL = "jane.private@internal.example"


async def _seed_contact(session, record_id: uuid.UUID) -> None:
    session.add(
        RecordContact(
            record_id=record_id,
            role="owner",
            name="Jane Confidential",
            email=_LEAK_EMAIL,
            phone="+1-555-0100",
            organization="Internal Only Org",
        )
    )
    await session.flush()


async def _private_record(test_db_session, owner_id: str) -> uuid.UUID:
    ds = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(owner_id),
        name="Owner private dataset",
        visibility="private",
        record_status="draft",
    )
    return ds.record_id


# ---------------------------------------------------------------------------
# ATTACK — a non-owner authenticated user cannot read a private record
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("sub", _SUBRESOURCES)
async def test_private_record_subresource_rejects_non_owner(
    client: AsyncClient, admin_auth_header: dict, test_db_session, sub: str
):
    """A `viewer` who is not the owner is denied (404). Fails on main (200)."""
    _owner_headers, owner_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    attacker_headers, _ = await _create_test_user(client, admin_auth_header, "viewer")
    record_id = await _private_record(test_db_session, owner_id)
    await _seed_contact(test_db_session, record_id)

    resp = await client.get(f"/records/{record_id}/{sub}/", headers=attacker_headers)

    assert resp.status_code == 404, (
        f"{sub}: a non-owner viewer read another user's PRIVATE record, got "
        f"{resp.status_code}: {resp.text}"
    )
    assert _LEAK_EMAIL not in resp.text


@pytest.mark.anyio
async def test_private_record_contacts_does_not_leak_pii(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Concrete PII-leak guard: the seeded contact email never reaches a
    non-owner. Mirrors the live SEC-001 reproduction."""
    _owner_headers, owner_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    attacker_headers, _ = await _create_test_user(client, admin_auth_header, "viewer")
    record_id = await _private_record(test_db_session, owner_id)
    await _seed_contact(test_db_session, record_id)

    resp = await client.get(f"/records/{record_id}/contacts/", headers=attacker_headers)

    assert resp.status_code == 404
    assert _LEAK_EMAIL not in resp.text
    assert "Internal Only Org" not in resp.text


# ---------------------------------------------------------------------------
# CONTROL + GUARDs — anon stays denied; owner/admin/public stay allowed
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("sub", _SUBRESOURCES)
async def test_private_record_subresource_rejects_anonymous(
    client: AsyncClient, admin_auth_header: dict, test_db_session, sub: str
):
    """CONTROL: anonymous remains denied on a private record (404)."""
    _owner_headers, owner_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    record_id = await _private_record(test_db_session, owner_id)

    resp = await client.get(f"/records/{record_id}/{sub}/")

    assert resp.status_code == 404


@pytest.mark.anyio
@pytest.mark.parametrize("sub", _SUBRESOURCES)
async def test_private_record_subresource_allows_owner(
    client: AsyncClient, admin_auth_header: dict, test_db_session, sub: str
):
    """GUARD: the owner reads their OWN private record's sub-resources (200)."""
    owner_headers, owner_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    record_id = await _private_record(test_db_session, owner_id)

    resp = await client.get(f"/records/{record_id}/{sub}/", headers=owner_headers)

    assert resp.status_code == 200, (
        f"{sub}: owner blocked from their OWN record, got "
        f"{resp.status_code}: {resp.text}"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("sub", _SUBRESOURCES)
async def test_private_record_subresource_allows_admin(
    client: AsyncClient, admin_auth_header: dict, test_db_session, sub: str
):
    """GUARD: admin reads any private record's sub-resources (200)."""
    _owner_headers, owner_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    record_id = await _private_record(test_db_session, owner_id)

    resp = await client.get(f"/records/{record_id}/{sub}/", headers=admin_auth_header)

    assert resp.status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize("sub", _SUBRESOURCES)
async def test_public_record_subresource_allows_anonymous(
    client: AsyncClient, admin_auth_header: dict, test_db_session, sub: str
):
    """GUARD: a public+published record's sub-resources stay world-readable."""
    _owner_headers, owner_id = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    ds = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(owner_id),
        name="Public dataset",
        visibility="public",
        record_status="published",
    )

    resp = await client.get(f"/records/{ds.record_id}/{sub}/")

    assert resp.status_code == 200
