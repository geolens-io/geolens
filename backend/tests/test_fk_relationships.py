"""Integration tests for FK relationship endpoints.

Tests cover CRUD operations, auth enforcement, and visibility checks
for the /datasets/{dataset_id}/relationships/ endpoints.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.models import User
from app.datasets.models import Dataset, Record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_id(session, username: str) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


async def _create_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str = "Test Dataset",
    table_name: str | None = None,
    visibility: str = "public",
) -> Dataset:
    if table_name is None:
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary="Test",
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
        feature_count=10,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


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
        admin_id = await _get_user_id(test_db_session, "admin")
        source = await _create_dataset(
            test_db_session, created_by=admin_id, name="Source DS"
        )
        target = await _create_dataset(
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
        admin_id = await _get_user_id(test_db_session, "admin")
        source = await _create_dataset(
            test_db_session, created_by=admin_id, name="List Source"
        )
        target = await _create_dataset(
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
        items = resp.json()
        assert isinstance(items, list)
        assert len(items) >= 1
        assert any(r["source_column"] == "ref_id" for r in items)

    async def test_delete_relationship(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """DELETE removes a relationship, returns 204."""
        admin_id = await _get_user_id(test_db_session, "admin")
        source = await _create_dataset(
            test_db_session, created_by=admin_id, name="Del Source"
        )
        target = await _create_dataset(
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
        admin_id = await _get_user_id(test_db_session, "admin")
        private_ds = await _create_dataset(
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
        admin_id = await _get_user_id(test_db_session, "admin")
        source = await _create_dataset(
            test_db_session, created_by=admin_id, name="Auth Source"
        )
        target = await _create_dataset(
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
