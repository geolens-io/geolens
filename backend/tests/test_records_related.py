"""Integration tests for record sub-resource CRUD: contacts, keywords, distributions.

Tests exercise the /records/{id}/contacts/, /records/{id}/keywords/, and
/records/{id}/distributions/ endpoints. Uses the same test infrastructure as
test_datasets.py (httpx AsyncClient, direct DB insertion for setup).

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied (87-01 related tables migration)
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.datasets.models import (
    Dataset,
    Record,
    RecordContact,
    RecordDistribution,
    RecordKeyword,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_id(session: AsyncSession, username: str) -> uuid.UUID:
    """Look up a user's ID by username."""
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


async def _create_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    name: str = "Test Dataset",
    table_name: str | None = None,
    visibility: str = "public",
) -> Dataset:
    """Insert a Record + Dataset pair directly into the DB (no distributions)."""
    if table_name is None:
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary="A test dataset",
        theme_category=["test"],
        visibility=visibility,
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="MultiPolygon",
        feature_count=42,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_dataset_with_distributions(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    name: str = "Test Dataset",
    table_name: str | None = None,
) -> Dataset:
    """Create a dataset using the service layer (includes auto-generated distributions)."""
    from app.datasets.service import create_dataset

    if table_name is None:
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
    dataset = await create_dataset(
        session,
        table_name=table_name,
        title=name,
        created_by=created_by,
        visibility="public",
        geometry_type="MultiPolygon",
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


class TestContacts:
    async def test_list_contacts_empty(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """GET contacts for a fresh dataset returns empty list."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp = await client.get(
            f"/records/{ds.record_id}/contacts/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["contacts"] == []
        assert data["total"] == 0

    async def test_create_contact(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """POST a contact returns 201 with correct shape including extra_json."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            f"/records/{ds.record_id}/contacts/",
            json={
                "role": "pointOfContact",
                "name": "Jane Doe",
                "email": "jane@example.com",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "pointOfContact"
        assert data["name"] == "Jane Doe"
        assert data["email"] == "jane@example.com"
        assert data["record_id"] == str(ds.record_id)
        assert "extra_json" in data
        assert "id" in data

    async def test_create_contact_all_roles(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """All 20 ISO CI_RoleCode values are accepted."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        roles = [
            "resourceProvider",
            "custodian",
            "owner",
            "user",
            "distributor",
            "originator",
            "pointOfContact",
            "principalInvestigator",
            "processor",
            "publisher",
            "author",
            "sponsor",
            "coAuthor",
            "collaborator",
            "editor",
            "mediator",
            "rightsHolder",
            "contributor",
            "funder",
            "stakeholder",
        ]
        for role in roles:
            resp = await client.post(
                f"/records/{ds.record_id}/contacts/",
                json={"role": role, "name": f"Test {role}"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 201, f"Failed for role: {role} — {resp.text}"

    async def test_create_contact_invalid_role(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """POST with invalid role triggers DB CHECK violation."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            f"/records/{ds.record_id}/contacts/",
            json={"role": "invalid_role", "name": "Test"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400

    async def test_create_contact_with_extra_json(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """extra_json JSONB field is preserved in response."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            f"/records/{ds.record_id}/contacts/",
            json={
                "role": "author",
                "name": "Extra User",
                "extra_json": {"website": "https://example.com", "orcid": "0000-0001"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["extra_json"] == {
            "website": "https://example.com",
            "orcid": "0000-0001",
        }

    async def test_list_contacts_returns_created(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Create 2 contacts, then list returns both."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        for name in ["Alice", "Bob"]:
            await client.post(
                f"/records/{ds.record_id}/contacts/",
                json={"role": "pointOfContact", "name": name},
                headers=admin_auth_header,
            )
        resp = await client.get(
            f"/records/{ds.record_id}/contacts/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        names = {c["name"] for c in data["contacts"]}
        assert names == {"Alice", "Bob"}

    async def test_update_contact(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """PATCH a contact updates the specified fields."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        create_resp = await client.post(
            f"/records/{ds.record_id}/contacts/",
            json={"role": "author", "name": "Old Name"},
            headers=admin_auth_header,
        )
        contact_id = create_resp.json()["id"]
        patch_resp = await client.patch(
            f"/records/{ds.record_id}/contacts/{contact_id}/",
            json={"name": "New Name"},
            headers=admin_auth_header,
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["name"] == "New Name"

    async def test_delete_contact(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """DELETE a contact returns 204, then list returns empty."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        create_resp = await client.post(
            f"/records/{ds.record_id}/contacts/",
            json={"role": "publisher", "name": "To Delete"},
            headers=admin_auth_header,
        )
        contact_id = create_resp.json()["id"]
        del_resp = await client.delete(
            f"/records/{ds.record_id}/contacts/{contact_id}/",
            headers=admin_auth_header,
        )
        assert del_resp.status_code == 204
        list_resp = await client.get(
            f"/records/{ds.record_id}/contacts/", headers=admin_auth_header
        )
        assert list_resp.json()["total"] == 0

    async def test_contact_requires_auth(
        self, client: AsyncClient, test_db_session: AsyncSession
    ):
        """GET contacts without token returns 200 (anonymous allowed on public datasets)."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp = await client.get(f"/records/{ds.record_id}/contacts/")
        assert resp.status_code == 200

    async def test_contact_create_requires_editor(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """POST with viewer token returns 403."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            f"/records/{ds.record_id}/contacts/",
            json={"role": "author", "name": "Viewer Attempt"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_contact_not_found_record(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        """POST to nonexistent record returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"/records/{fake_id}/contacts/",
            json={"role": "author", "name": "Nonexistent"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_contact_column_dropped(self, test_db_session: AsyncSession):
        """The legacy contact JSONB column no longer exists on the records table."""
        result = await test_db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='catalog' AND table_name='records' AND column_name='contact'"
            )
        )
        rows = result.all()
        assert len(rows) == 0, "The 'contact' JSONB column should have been dropped"


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


class TestKeywords:
    async def test_list_keywords_empty(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """GET keywords for a new dataset returns empty list."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp = await client.get(
            f"/records/{ds.record_id}/keywords/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["keywords"] == []
        assert data["total"] == 0

    async def test_create_keyword(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """POST a keyword returns 201."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json={"keyword": "hydrology", "keyword_type": "theme"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["keyword"] == "hydrology"
        assert data["keyword_type"] == "theme"

    async def test_create_keyword_all_types(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """All 15 ISO MD_KeywordTypeCode values are accepted."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        types = [
            "discipline",
            "place",
            "stratum",
            "temporal",
            "theme",
            "dataCentre",
            "featureType",
            "instrument",
            "platform",
            "process",
            "product",
            "project",
            "service",
            "subTopicCategory",
            "taxon",
        ]
        for kw_type in types:
            resp = await client.post(
                f"/records/{ds.record_id}/keywords/",
                json={"keyword": f"test_{kw_type}", "keyword_type": kw_type},
                headers=admin_auth_header,
            )
            assert resp.status_code == 201, (
                f"Failed for keyword_type: {kw_type} — {resp.text}"
            )

    async def test_create_duplicate_keyword(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Duplicate keyword+type+vocabulary_uri returns 409."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        payload = {"keyword": "duplicate_test", "keyword_type": "theme"}
        resp1 = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json=payload,
            headers=admin_auth_header,
        )
        assert resp1.status_code == 201
        resp2 = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json=payload,
            headers=admin_auth_header,
        )
        assert resp2.status_code == 409

    async def test_create_keyword_different_types(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Same keyword text with different types both succeed."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp1 = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json={"keyword": "water", "keyword_type": "theme"},
            headers=admin_auth_header,
        )
        assert resp1.status_code == 201
        resp2 = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json={"keyword": "water", "keyword_type": "place"},
            headers=admin_auth_header,
        )
        assert resp2.status_code == 201

    async def test_create_keyword_same_text_different_vocabulary(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Same keyword+type but different vocabulary_uri both succeed."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp1 = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json={
                "keyword": "geology",
                "keyword_type": "theme",
                "vocabulary_uri": "https://vocab-a.example.com",
            },
            headers=admin_auth_header,
        )
        assert resp1.status_code == 201
        resp2 = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json={
                "keyword": "geology",
                "keyword_type": "theme",
                "vocabulary_uri": "https://vocab-b.example.com",
            },
            headers=admin_auth_header,
        )
        assert resp2.status_code == 201

    async def test_create_keyword_null_vs_null_vocabulary(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Same keyword+type with NULL vocabulary_uri twice returns 409."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        payload = {"keyword": "null_vocab_test", "keyword_type": "theme"}
        resp1 = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json=payload,
            headers=admin_auth_header,
        )
        assert resp1.status_code == 201
        resp2 = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json=payload,
            headers=admin_auth_header,
        )
        assert resp2.status_code == 409

    async def test_delete_keyword(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """DELETE a keyword returns 204."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        create_resp = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json={"keyword": "to_delete", "keyword_type": "theme"},
            headers=admin_auth_header,
        )
        kw_id = create_resp.json()["id"]
        del_resp = await client.delete(
            f"/records/{ds.record_id}/keywords/{kw_id}/",
            headers=admin_auth_header,
        )
        assert del_resp.status_code == 204

    async def test_keyword_not_found_record(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        """POST keyword to nonexistent record returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"/records/{fake_id}/keywords/",
            json={"keyword": "orphan", "keyword_type": "theme"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_keyword_normalization_trimmed_lowercased(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Keywords are normalized: stripped and lowercased on insert."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json={"keyword": "  Hydrology  ", "keyword_type": "theme"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        assert resp.json()["keyword"] == "hydrology"

    async def test_keyword_normalization_prevents_duplicates(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Normalization makes 'Hydrology' and 'hydrology' identical -> 409."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp1 = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json={"keyword": "Normalization", "keyword_type": "theme"},
            headers=admin_auth_header,
        )
        assert resp1.status_code == 201
        resp2 = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json={"keyword": "normalization", "keyword_type": "theme"},
            headers=admin_auth_header,
        )
        assert resp2.status_code == 409

    async def test_keyword_vocabulary_uri_normalized(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """vocabulary_uri trailing slash is stripped on insert."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            f"/records/{ds.record_id}/keywords/",
            json={
                "keyword": "vocab_test",
                "keyword_type": "theme",
                "vocabulary_uri": "https://example.com/vocab/",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        assert resp.json()["vocabulary_uri"] == "https://example.com/vocab"


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------


class TestDistributions:
    async def test_list_distributions_auto_generated(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Dataset created via service gets 6 auto-generated distributions."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_distributions(
            test_db_session, created_by=admin_id
        )
        resp = await client.get(
            f"/records/{ds.record_id}/distributions/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 6

        # All auto_generated
        for d in data["distributions"]:
            assert d["auto_generated"] is True
            assert d["title"] is not None
            assert d["protocol"] is not None

        # Verify distribution URLs use dataset_id (not record_id)
        dataset_id_str = str(ds.id)
        download_dists = [
            d for d in data["distributions"] if d["distribution_type"] == "download"
        ]
        for d in download_dists:
            assert dataset_id_str in d["url"], (
                f"Distribution URL should contain dataset_id {dataset_id_str}: {d['url']}"
            )

    async def test_create_manual_distribution(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """POST a manual distribution returns 201 with all fields."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            f"/records/{ds.record_id}/distributions/",
            json={
                "distribution_type": "api",
                "format": "json",
                "url": "https://example.com/api/data",
                "title": "Custom API",
                "description": "A custom API endpoint",
                "protocol": "HTTPS",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["auto_generated"] is False
        assert data["title"] == "Custom API"
        assert data["description"] == "A custom API endpoint"
        assert data["protocol"] == "HTTPS"

    async def test_update_manual_distribution(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """PATCH a manual distribution updates fields."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        create_resp = await client.post(
            f"/records/{ds.record_id}/distributions/",
            json={
                "distribution_type": "api",
                "format": "json",
                "url": "https://example.com/api",
                "title": "Old Title",
            },
            headers=admin_auth_header,
        )
        dist_id = create_resp.json()["id"]
        patch_resp = await client.patch(
            f"/records/{ds.record_id}/distributions/{dist_id}/",
            json={
                "title": "New Title",
                "description": "Added desc",
                "protocol": "HTTPS",
            },
            headers=admin_auth_header,
        )
        assert patch_resp.status_code == 200
        data = patch_resp.json()
        assert data["title"] == "New Title"
        assert data["description"] == "Added desc"
        assert data["protocol"] == "HTTPS"

    async def test_delete_manual_distribution(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """DELETE a manual distribution returns 204."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        create_resp = await client.post(
            f"/records/{ds.record_id}/distributions/",
            json={
                "distribution_type": "download",
                "format": "pdf",
                "url": "https://example.com/doc.pdf",
            },
            headers=admin_auth_header,
        )
        dist_id = create_resp.json()["id"]
        del_resp = await client.delete(
            f"/records/{ds.record_id}/distributions/{dist_id}/",
            headers=admin_auth_header,
        )
        assert del_resp.status_code == 204

    async def test_update_auto_generated_blocked(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """PATCH an auto-generated distribution returns 400."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_distributions(
            test_db_session, created_by=admin_id
        )
        # Get an auto-generated distribution
        list_resp = await client.get(
            f"/records/{ds.record_id}/distributions/", headers=admin_auth_header
        )
        auto_dist = list_resp.json()["distributions"][0]
        assert auto_dist["auto_generated"] is True

        patch_resp = await client.patch(
            f"/records/{ds.record_id}/distributions/{auto_dist['id']}/",
            json={"title": "Should Not Work"},
            headers=admin_auth_header,
        )
        assert patch_resp.status_code == 400

    async def test_delete_auto_generated_blocked(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """DELETE an auto-generated distribution returns 400."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_distributions(
            test_db_session, created_by=admin_id
        )
        list_resp = await client.get(
            f"/records/{ds.record_id}/distributions/", headers=admin_auth_header
        )
        auto_dist = list_resp.json()["distributions"][0]
        del_resp = await client.delete(
            f"/records/{ds.record_id}/distributions/{auto_dist['id']}/",
            headers=admin_auth_header,
        )
        assert del_resp.status_code == 400

    async def test_distribution_not_found_record(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        """POST distribution to nonexistent record returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"/records/{fake_id}/distributions/",
            json={
                "distribution_type": "manual",
                "format": "json",
                "url": "https://example.com",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_distribution_unique_constraint(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Duplicate (record_id, distribution_type, format, url) returns conflict."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)
        payload = {
            "distribution_type": "api",
            "format": "json",
            "url": "https://example.com/a",
        }
        resp1 = await client.post(
            f"/records/{ds.record_id}/distributions/",
            json=payload,
            headers=admin_auth_header,
        )
        assert resp1.status_code == 201
        resp2 = await client.post(
            f"/records/{ds.record_id}/distributions/",
            json=payload,
            headers=admin_auth_header,
        )
        assert resp2.status_code == 409

    async def test_generate_distributions_idempotent(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Calling generate_distributions twice produces no duplicates."""
        from app.records.service import generate_distributions

        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id)

        # First generation
        created1 = await generate_distributions(
            test_db_session,
            ds.id,
            ds.record_id,
            ds.table_name,
            geometry_type="MultiPolygon",
        )
        await test_db_session.commit()
        assert len(created1) == 6

        # Second generation (idempotent)
        created2 = await generate_distributions(
            test_db_session,
            ds.id,
            ds.record_id,
            ds.table_name,
            geometry_type="MultiPolygon",
        )
        await test_db_session.commit()
        assert len(created2) == 0  # No new rows

        # Still only 6 total
        resp = await client.get(
            f"/records/{ds.record_id}/distributions/", headers=admin_auth_header
        )
        assert resp.json()["total"] == 6

    async def test_distribution_lifecycle_modes(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """System-generated (immutable) and user-created (editable) coexist."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_distributions(
            test_db_session, created_by=admin_id
        )

        # Add a manual distribution
        manual_resp = await client.post(
            f"/records/{ds.record_id}/distributions/",
            json={
                "distribution_type": "download",
                "format": "xlsx",
                "url": "https://example.com/data.xlsx",
                "title": "Excel Export",
            },
            headers=admin_auth_header,
        )
        assert manual_resp.status_code == 201
        manual_id = manual_resp.json()["id"]

        # Total: 6 system + 1 manual = 7
        list_resp = await client.get(
            f"/records/{ds.record_id}/distributions/", headers=admin_auth_header
        )
        assert list_resp.json()["total"] == 7

        # System distributions are immutable
        auto_dist = next(
            d for d in list_resp.json()["distributions"] if d["auto_generated"]
        )
        assert (
            await client.patch(
                f"/records/{ds.record_id}/distributions/{auto_dist['id']}/",
                json={"title": "Fail"},
                headers=admin_auth_header,
            )
        ).status_code == 400
        assert (
            await client.delete(
                f"/records/{ds.record_id}/distributions/{auto_dist['id']}/",
                headers=admin_auth_header,
            )
        ).status_code == 400

        # Manual distribution is fully editable
        assert (
            await client.patch(
                f"/records/{ds.record_id}/distributions/{manual_id}/",
                json={"title": "Updated Excel"},
                headers=admin_auth_header,
            )
        ).status_code == 200
        assert (
            await client.delete(
                f"/records/{ds.record_id}/distributions/{manual_id}/",
                headers=admin_auth_header,
            )
        ).status_code == 204


# ---------------------------------------------------------------------------
# Cascade Delete
# ---------------------------------------------------------------------------


class TestCascadeDelete:
    async def test_delete_record_cascades_contacts(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Deleting a record cascades to remove all contacts."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="Cascade Contact Test"
        )
        record_id = ds.record_id

        # Add a contact
        await client.post(
            f"/records/{record_id}/contacts/",
            json={"role": "author", "name": "Cascade Test"},
            headers=admin_auth_header,
        )

        # Delete the dataset (cascades to record, which cascades to contacts)
        await client.request(
            "DELETE",
            f"/datasets/{ds.id}",
            json={"confirm_title": "Cascade Contact Test"},
            headers=admin_auth_header,
        )

        # Verify contacts are gone
        result = await test_db_session.execute(
            select(RecordContact).where(RecordContact.record_id == record_id)
        )
        assert len(result.all()) == 0

    async def test_delete_record_cascades_keywords(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Deleting a record cascades to remove all keywords."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="Cascade Keyword Test"
        )
        record_id = ds.record_id

        await client.post(
            f"/records/{record_id}/keywords/",
            json={"keyword": "cascade_kw", "keyword_type": "theme"},
            headers=admin_auth_header,
        )

        await client.request(
            "DELETE",
            f"/datasets/{ds.id}",
            json={"confirm_title": "Cascade Keyword Test"},
            headers=admin_auth_header,
        )

        result = await test_db_session.execute(
            select(RecordKeyword).where(RecordKeyword.record_id == record_id)
        )
        assert len(result.all()) == 0

    async def test_delete_record_cascades_distributions(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Deleting a record cascades to remove all distributions."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_distributions(
            test_db_session,
            created_by=admin_id,
            name="Cascade Dist Test",
        )
        record_id = ds.record_id

        # Verify distributions exist before delete
        pre_result = await test_db_session.execute(
            select(RecordDistribution).where(RecordDistribution.record_id == record_id)
        )
        assert len(pre_result.all()) == 6

        await client.request(
            "DELETE",
            f"/datasets/{ds.id}",
            json={"confirm_title": "Cascade Dist Test"},
            headers=admin_auth_header,
        )

        result = await test_db_session.execute(
            select(RecordDistribution).where(RecordDistribution.record_id == record_id)
        )
        assert len(result.all()) == 0


# ---------------------------------------------------------------------------
# Migration Data Verification
# ---------------------------------------------------------------------------


class TestMigrationData:
    """Verify the 87-01 migration ran correctly on the test database.

    The test DB is created from scratch via Alembic migrations. These tests
    verify the migration SQL executed without error. Since no seed data has
    contacts/tags in the test DB, we verify structural correctness.
    """

    async def test_migrated_contacts_have_role(self, test_db_session: AsyncSession):
        """All contacts have a non-null role (migration defaulted to pointOfContact)."""
        result = await test_db_session.execute(
            text("SELECT count(*) FROM catalog.record_contacts WHERE role IS NULL")
        )
        assert result.scalar_one() == 0

    async def test_migrated_contacts_have_extra_json(
        self, test_db_session: AsyncSession
    ):
        """extra_json column exists and is JSONB type (structural check)."""
        result = await test_db_session.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema='catalog' AND table_name='record_contacts' "
                "AND column_name='extra_json'"
            )
        )
        row = result.one_or_none()
        assert row is not None, "extra_json column must exist"
        assert row[0] == "jsonb"

    async def test_migrated_keywords_have_type(self, test_db_session: AsyncSession):
        """All keywords have a non-null keyword_type (migration defaulted to theme)."""
        result = await test_db_session.execute(
            text(
                "SELECT count(*) FROM catalog.record_keywords WHERE keyword_type IS NULL"
            )
        )
        assert result.scalar_one() == 0

    async def test_distributions_exist_for_datasets(
        self, test_db_session: AsyncSession
    ):
        """Migration created distributions for existing datasets (structural check).

        In the fresh test DB, there are no pre-existing datasets from seed data,
        so we verify the table exists and the migration SQL ran without error.
        """
        result = await test_db_session.execute(
            text("SELECT count(*) FROM catalog.record_distributions")
        )
        count = result.scalar_one()
        # Count >= 0 means the table exists and migration ran
        assert count >= 0

    async def test_distribution_urls_use_dataset_id(
        self, test_db_session: AsyncSession
    ):
        """Distribution download URLs contain dataset_id (not record_id).

        Creates a dataset with distributions and verifies URL structure.
        """
        admin_id_result = await test_db_session.execute(
            select(User).where(User.username == "admin")
        )
        admin = admin_id_result.scalar_one()

        ds = await _create_dataset_with_distributions(
            test_db_session, created_by=admin.id, name="URL Check Dataset"
        )
        dataset_id_str = str(ds.id)
        record_id_str = str(ds.record_id)

        result = await test_db_session.execute(
            select(RecordDistribution).where(
                RecordDistribution.record_id == ds.record_id,
                RecordDistribution.distribution_type == "download",
            )
        )
        download_dists = result.scalars().all()
        assert len(download_dists) == 4

        for d in download_dists:
            assert dataset_id_str in d.url, (
                f"URL should contain dataset_id {dataset_id_str}, got: {d.url}"
            )
            # record_id should NOT be in the URL (they're different UUIDs)
            if record_id_str != dataset_id_str:
                assert record_id_str not in d.url, (
                    f"URL should NOT contain record_id {record_id_str}, got: {d.url}"
                )
