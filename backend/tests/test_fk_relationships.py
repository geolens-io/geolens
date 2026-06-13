"""Integration tests for FK relationship endpoints.

Tests cover CRUD operations, auth enforcement, and visibility checks
for the /datasets/{dataset_id}/relationships/ endpoints.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.catalog.datasets.domain.models import (
    AttributeMetadata,
    DatasetRelationship,
)
from app.modules.catalog.datasets.domain.service import auto_detect_relationships
from tests.factories import create_dataset, get_user_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestFKRelationships:
    async def test_create_relationship(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST creates a relationship between two datasets, returns 201."""
        admin_id = await get_user_id(test_db_session, "admin")
        source = await create_dataset(
            test_db_session, created_by=admin_id, name="Source DS"
        )
        target = await create_dataset(
            test_db_session, created_by=admin_id, name="Target DS"
        )

        resp = await client.post(
            f"/datasets/{source.id}/relationships/",
            json={
                "target_dataset_id": str(target.record_id),
                "source_column": "fk_col",
                "target_column": "gid",
                "label": "Links to target",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["source_column"] == "fk_col"
        assert data["target_column"] == "gid"
        assert data["label"] == "Links to target"
        assert "id" in data

    async def test_list_relationships(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """GET returns array of relationships for a dataset."""
        admin_id = await get_user_id(test_db_session, "admin")
        source = await create_dataset(
            test_db_session, created_by=admin_id, name="List Source"
        )
        target = await create_dataset(
            test_db_session, created_by=admin_id, name="List Target"
        )

        # Create a relationship first
        create_resp = await client.post(
            f"/datasets/{source.id}/relationships/",
            json={
                "target_dataset_id": str(target.record_id),
                "source_column": "ref_id",
            },
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201, create_resp.text

        # List relationships
        resp = await client.get(
            f"/datasets/{source.id}/relationships/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        # GAP-033: standard list envelope {relationships: [...], total: N}.
        body = resp.json()
        assert isinstance(body, dict)
        assert "total" in body
        items = body["relationships"]
        assert isinstance(items, list)
        assert len(items) >= 1
        assert body["total"] >= 1
        assert any(r["source_column"] == "ref_id" for r in items)

    async def test_list_relationships_envelope_total_reflects_full_count(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """GAP-033: the envelope `total` is the FULL visible count, not the page.

        With limit=1 over 2 relationships the page holds 1 item but total is 2,
        so a paginating client can detect that more pages exist. FAILS pre-fix
        (the endpoint returned a bare array with no total), PASSES post-fix.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        source = await create_dataset(
            test_db_session, created_by=admin_id, name="Envelope Source"
        )
        target_a = await create_dataset(
            test_db_session, created_by=admin_id, name="Envelope Target A"
        )
        target_b = await create_dataset(
            test_db_session, created_by=admin_id, name="Envelope Target B"
        )
        for target, col in ((target_a, "ref_a"), (target_b, "ref_b")):
            create_resp = await client.post(
                f"/datasets/{source.id}/relationships/",
                json={
                    "target_dataset_id": str(target.record_id),
                    "source_column": col,
                },
                headers=admin_auth_header,
            )
            assert create_resp.status_code == 201, create_resp.text

        resp = await client.get(
            f"/datasets/{source.id}/relationships/?limit=1",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) >= {"relationships", "total"}
        assert len(body["relationships"]) == 1  # page bounded by limit
        assert body["total"] == 2  # total reflects the full visible count

    async def test_list_relationships_hides_private_targets_from_anonymous(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Anonymous source access must not reveal private target metadata."""
        admin_id = await get_user_id(test_db_session, "admin")
        source = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Public Relationship Source",
            visibility="public",
            record_status="published",
        )
        target = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Private Relationship Target",
            visibility="private",
            record_status="published",
        )

        create_resp = await client.post(
            f"/datasets/{source.id}/relationships/",
            json={
                "target_dataset_id": str(target.record_id),
                "source_column": "private_ref_id",
            },
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201, create_resp.text

        resp = await client.get(f"/datasets/{source.id}/relationships/")

        assert resp.status_code == 200, resp.text
        # GAP-033 envelope: private target is filtered out, total reflects the
        # visible count (0), not the raw row count.
        body = resp.json()
        assert body["relationships"] == []
        assert body["total"] == 0

    async def test_related_records_rejects_private_target_for_anonymous(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Related-record reads require access to both source and target datasets."""
        admin_id = await get_user_id(test_db_session, "admin")
        source = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Public Related Source",
            visibility="public",
            record_status="published",
        )
        target = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Private Related Target",
            visibility="private",
            record_status="published",
        )
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{source.table_name} "
                "(gid integer PRIMARY KEY, private_ref_id integer)"
            )
        )
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{target.table_name} "
                "(gid integer PRIMARY KEY, private_ref_id integer, secret text)"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{source.table_name} "
                "(gid, private_ref_id) VALUES (1, 7)"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{target.table_name} "
                "(gid, private_ref_id, secret) VALUES (1, 7, 'hidden')"
            )
        )
        await test_db_session.commit()

        create_resp = await client.post(
            f"/datasets/{source.id}/relationships/",
            json={
                "target_dataset_id": str(target.record_id),
                "source_column": "private_ref_id",
                "target_column": "private_ref_id",
            },
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201, create_resp.text
        rel_id = create_resp.json()["id"]

        resp = await client.get(f"/datasets/{source.id}/features/1/related/{rel_id}/")

        assert resp.status_code == 404, resp.text

    async def test_related_records_rejects_relationship_for_different_source(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Relationship ids cannot be replayed through a different source dataset URL."""
        admin_id = await get_user_id(test_db_session, "admin")
        source = await create_dataset(
            test_db_session, created_by=admin_id, name="Bound Source"
        )
        other_source = await create_dataset(
            test_db_session, created_by=admin_id, name="Wrong Source"
        )
        target = await create_dataset(
            test_db_session, created_by=admin_id, name="Bound Target"
        )

        create_resp = await client.post(
            f"/datasets/{source.id}/relationships/",
            json={
                "target_dataset_id": str(target.record_id),
                "source_column": "target_id",
                "target_column": "target_id",
            },
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201, create_resp.text
        rel_id = create_resp.json()["id"]

        resp = await client.get(
            f"/datasets/{other_source.id}/features/1/related/{rel_id}/",
            headers=admin_auth_header,
        )

        assert resp.status_code == 404, resp.text

    async def test_auto_detect_relationships_skips_private_targets_for_public_source(
        self,
        test_db_session,
    ):
        """Auto-detection must not create public-to-private relationships."""
        admin_id = await get_user_id(test_db_session, "admin")
        source = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Public Auto Source",
            visibility="public",
            record_status="published",
        )
        target = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Private Auto Target",
            visibility="private",
            record_status="published",
        )
        test_db_session.add(
            AttributeMetadata(
                dataset_id=target.id,
                field_name="private_ref_id",
                semantic_role="identifier",
            )
        )
        await test_db_session.commit()

        created = await auto_detect_relationships(
            test_db_session,
            source.id,
            source.record_id,
            [{"name": "private_ref_id"}],
        )
        await test_db_session.commit()

        relationships = (
            (
                await test_db_session.execute(
                    select(DatasetRelationship).where(
                        DatasetRelationship.source_dataset_id == source.record_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert created == []
        assert relationships == []

    async def test_delete_relationship(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """DELETE removes a relationship, returns 204."""
        admin_id = await get_user_id(test_db_session, "admin")
        source = await create_dataset(
            test_db_session, created_by=admin_id, name="Del Source"
        )
        target = await create_dataset(
            test_db_session, created_by=admin_id, name="Del Target"
        )

        create_resp = await client.post(
            f"/datasets/{source.id}/relationships/",
            json={
                "target_dataset_id": str(target.record_id),
                "source_column": "del_col",
            },
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        rel_id = create_resp.json()["id"]

        # Delete the relationship
        resp = await client.delete(
            f"/datasets/relationships/{rel_id}/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 204

    async def test_list_relationships_private_dataset_anonymous(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Anonymous user cannot list relationships on a private dataset."""
        admin_id = await get_user_id(test_db_session, "admin")
        private_ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Private DS",
            visibility="private",
        )

        resp = await client.get(f"/datasets/{private_ds.id}/relationships/")
        assert resp.status_code in (403, 404), resp.text

    async def test_create_relationship_requires_auth(
        self,
        client: AsyncClient,
        test_db_session,
    ):
        """Unauthenticated POST returns 401/403."""
        admin_id = await get_user_id(test_db_session, "admin")
        source = await create_dataset(
            test_db_session, created_by=admin_id, name="Auth Source"
        )
        target = await create_dataset(
            test_db_session, created_by=admin_id, name="Auth Target"
        )

        resp = await client.post(
            f"/datasets/{source.id}/relationships/",
            json={
                "target_dataset_id": str(target.record_id),
                "source_column": "test_col",
            },
        )
        assert resp.status_code in (401, 403), resp.text

    async def test_delete_nonexistent_relationship(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        """DELETE unknown UUID returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.delete(
            f"/datasets/relationships/{fake_id}/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404
