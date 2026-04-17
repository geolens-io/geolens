"""Integration tests for attribute metadata CRUD: list, get, patch, reset.

Tests exercise the /datasets/{id}/attributes/ endpoints. Uses the same test
infrastructure as test_records_related.py (httpx AsyncClient, direct DB
insertion for setup).

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied (88-01 attribute_metadata migration)
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import AttributeMetadata, Dataset

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_dataset_with_attributes(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    name: str = "Attr Test",
    visibility: str = "public",
) -> Dataset:
    """Create a dataset with column_info so attribute metadata is auto-generated."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"

    # Create a simple data table
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  name TEXT,"
            f"  pop_2020 INTEGER,"
            f"  area_sqkm DOUBLE PRECISION,"
            f"  created_date DATE,"
            f"  geom GEOMETRY(Point, 4326)"
            f")"
        )
    )
    # Insert sample rows
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (name, pop_2020, area_sqkm, created_date, geom) VALUES "
            f"('City A', 100000, 45.5, '2020-01-01', ST_MakePoint(-73.9, 40.7)),"
            f"('City B', 200000, 88.2, '2021-06-15', ST_MakePoint(-118.2, 34.0)),"
            f"('City C', 50000, 12.3, '2022-03-20', ST_MakePoint(-87.6, 41.8))"
        )
    )
    await session.commit()

    column_info = [
        {"name": "name", "type": "text", "ordinal_position": 2, "is_nullable": True},
        {
            "name": "pop_2020",
            "type": "integer",
            "ordinal_position": 3,
            "is_nullable": True,
        },
        {
            "name": "area_sqkm",
            "type": "double precision",
            "ordinal_position": 4,
            "is_nullable": True,
        },
        {
            "name": "created_date",
            "type": "date",
            "ordinal_position": 5,
            "is_nullable": True,
        },
    ]

    sample_values = {
        "name": ["City A", "City B", "City C"],
        "pop_2020": [100000, 200000, 50000],
        "area_sqkm": [45.5, 88.2, 12.3],
        "created_date": ["2020-01-01", "2021-06-15", "2022-03-20"],
    }

    from app.modules.catalog.datasets.domain.service import create_dataset

    dataset = await create_dataset(
        session,
        table_name=table_name,
        title=name,
        created_by=created_by,
        column_info=column_info,
        sample_values=sample_values,
        geometry_type="POINT",
        srid=4326,
        visibility=visibility,
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Auto-population tests
# ---------------------------------------------------------------------------


class TestAttributeAutoPopulation:
    async def test_auto_populated_after_create(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Create dataset with column_info, verify attributes are auto-generated."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        # 4 columns + 1 geometry = 5
        assert data["total"] == 5
        field_names = {a["field_name"] for a in data["attributes"]}
        assert "name" in field_names
        assert "pop_2020" in field_names
        assert "area_sqkm" in field_names
        assert "created_date" in field_names
        assert "geom" in field_names

    async def test_geometry_column_included(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Verify geom row exists with correct semantic_role and domain_type."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attrs = resp.json()["attributes"]
        geom = next(a for a in attrs if a["field_name"] == "geom")
        assert geom["semantic_role"] == "geometry"
        assert geom["domain_type"] == "geometry"

    async def test_semantic_role_inference(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Verify semantic roles inferred correctly for different column types."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attrs_by_name = {a["field_name"]: a for a in resp.json()["attributes"]}
        assert attrs_by_name["pop_2020"]["semantic_role"] == "measure"
        assert attrs_by_name["name"]["semantic_role"] == "label"
        assert attrs_by_name["created_date"]["semantic_role"] == "temporal"

    async def test_domain_type_inference(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Verify domain types inferred correctly from PostgreSQL data types."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attrs_by_name = {a["field_name"]: a for a in resp.json()["attributes"]}
        assert attrs_by_name["pop_2020"]["domain_type"] == "discrete"
        assert attrs_by_name["area_sqkm"]["domain_type"] == "continuous"
        assert attrs_by_name["created_date"]["domain_type"] == "temporal"
        assert attrs_by_name["name"]["domain_type"] == "text"

    async def test_unit_suffix_inference(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Verify area_sqkm gets units='square kilometers' from suffix."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attrs_by_name = {a["field_name"]: a for a in resp.json()["attributes"]}
        assert attrs_by_name["area_sqkm"]["units"] == "square kilometers"

    async def test_title_humanization(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Verify column names are humanized into titles."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attrs_by_name = {a["field_name"]: a for a in resp.json()["attributes"]}
        assert attrs_by_name["pop_2020"]["title"] == "Pop 2020"
        assert attrs_by_name["area_sqkm"]["title"] == "Area Sqkm"
        assert attrs_by_name["created_date"]["title"] == "Created Date"

    async def test_example_values_populated(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Verify non-geometry columns have example_values populated."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attrs_by_name = {a["field_name"]: a for a in resp.json()["attributes"]}
        assert attrs_by_name["name"]["example_values"] is not None
        assert isinstance(attrs_by_name["name"]["example_values"], list)
        assert len(attrs_by_name["name"]["example_values"]) > 0

    async def test_geometry_example_values_null(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Verify geom row has example_values=None."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attrs_by_name = {a["field_name"]: a for a in resp.json()["attributes"]}
        assert attrs_by_name["geom"]["example_values"] is None

    async def test_ordinal_position_populated(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Verify ordinal_position is set from column_info."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attrs_by_name = {a["field_name"]: a for a in resp.json()["attributes"]}
        assert attrs_by_name["name"]["ordinal_position"] == 2
        assert attrs_by_name["pop_2020"]["ordinal_position"] == 3
        assert attrs_by_name["area_sqkm"]["ordinal_position"] == 4
        assert attrs_by_name["created_date"]["ordinal_position"] == 5


# ---------------------------------------------------------------------------
# API CRUD tests
# ---------------------------------------------------------------------------


class TestAttributeAPI:
    async def test_list_attributes(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """GET /datasets/{id}/attributes/ returns correct total and all fields."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        # Verify response shape
        attr = data["attributes"][0]
        assert "id" in attr
        assert "dataset_id" in attr
        assert "field_name" in attr
        assert "user_modified_fields" in attr

    async def test_get_single_attribute(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """GET /datasets/{id}/attributes/{attr_id}/ returns the correct attribute."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        list_resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attr = list_resp.json()["attributes"][0]
        resp = await client.get(
            f"/datasets/{ds.id}/attributes/{attr['id']}/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == attr["id"]
        assert resp.json()["field_name"] == attr["field_name"]

    async def test_get_attribute_not_found(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """GET with fake attr_id returns 404."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/datasets/{ds.id}/attributes/{fake_id}/", headers=admin_auth_header
        )
        assert resp.status_code == 404

    async def test_patch_sets_user_modified_fields(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """PATCH with title adds 'title' to user_modified_fields."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        list_resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attr = next(
            a for a in list_resp.json()["attributes"] if a["field_name"] == "name"
        )
        resp = await client.patch(
            f"/datasets/{ds.id}/attributes/{attr['id']}/",
            json={"title": "Custom Name"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Custom Name"
        assert "title" in data["user_modified_fields"]

    async def test_patch_attribute_description(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """PATCH with description works."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        list_resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attr = next(
            a for a in list_resp.json()["attributes"] if a["field_name"] == "pop_2020"
        )
        resp = await client.patch(
            f"/datasets/{ds.id}/attributes/{attr['id']}/",
            json={"description": "Total population in 2020"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "Total population in 2020"
        assert "description" in resp.json()["user_modified_fields"]

    async def test_patch_attribute_units(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """PATCH with units works."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        list_resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attr = next(
            a for a in list_resp.json()["attributes"] if a["field_name"] == "pop_2020"
        )
        resp = await client.patch(
            f"/datasets/{ds.id}/attributes/{attr['id']}/",
            json={"units": "people"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["units"] == "people"

    async def test_reset_attribute(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """After PATCH + POST reset, user_modified_fields is empty and title reverts."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        list_resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attr = next(
            a for a in list_resp.json()["attributes"] if a["field_name"] == "pop_2020"
        )
        original_title = attr["title"]

        # PATCH to change title and add description
        await client.patch(
            f"/datasets/{ds.id}/attributes/{attr['id']}/",
            json={"title": "Population", "description": "Total population"},
            headers=admin_auth_header,
        )

        # Reset
        reset_resp = await client.post(
            f"/datasets/{ds.id}/attributes/{attr['id']}/reset/",
            headers=admin_auth_header,
        )
        assert reset_resp.status_code == 200
        data = reset_resp.json()
        assert data["user_modified_fields"] == []
        assert data["title"] == original_title
        assert data["description"] is None

    async def test_list_requires_auth(
        self,
        client: AsyncClient,
        test_db_session: AsyncSession,
    ):
        """GET without token on public dataset returns 200 (anonymous allowed)."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        resp = await client.get(f"/datasets/{ds.id}/attributes/")
        assert resp.status_code == 200

    async def test_patch_requires_editor(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """PATCH with viewer token returns 403."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        list_resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attr = list_resp.json()["attributes"][0]
        resp = await client.patch(
            f"/datasets/{ds.id}/attributes/{attr['id']}/",
            json={"title": "Should Fail"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_reset_requires_editor(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """POST reset with viewer token returns 403."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        list_resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attr = list_resp.json()["attributes"][0]
        resp = await client.post(
            f"/datasets/{ds.id}/attributes/{attr['id']}/reset/",
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_attribute_not_found_dataset(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        """GET attributes for nonexistent dataset returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/datasets/{fake_id}/attributes/", headers=admin_auth_header
        )
        assert resp.status_code == 404

    async def test_patch_checks_dataset_access(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Editor on private dataset they don't own gets 404."""
        # Create editor user
        from tests.conftest import _create_test_user

        editor_header, editor_user_id = await _create_test_user(
            client, admin_auth_header, "editor"
        )

        # Create private dataset owned by admin
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(
            test_db_session, created_by=admin_id, visibility="private"
        )

        # Get attribute ID (via admin)
        list_resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attr = list_resp.json()["attributes"][0]

        # Editor tries to patch - should get 404 (access denied)
        resp = await client.patch(
            f"/datasets/{ds.id}/attributes/{attr['id']}/",
            json={"title": "Should Fail"},
            headers=editor_header,
        )
        assert resp.status_code == 404

    async def test_reset_checks_dataset_access(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Editor on private dataset they don't own cannot reset."""
        from tests.conftest import _create_test_user

        editor_header, _ = await _create_test_user(client, admin_auth_header, "editor")

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(
            test_db_session, created_by=admin_id, visibility="private"
        )

        list_resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attr = list_resp.json()["attributes"][0]

        resp = await client.post(
            f"/datasets/{ds.id}/attributes/{attr['id']}/reset/",
            headers=editor_header,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Null and validation tests
# ---------------------------------------------------------------------------


class TestAttributeNullAndValidation:
    async def test_patch_clear_field_to_null(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Send {"title": null}, verify title is None in response."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        list_resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attr = next(
            a for a in list_resp.json()["attributes"] if a["field_name"] == "name"
        )
        resp = await client.patch(
            f"/datasets/{ds.id}/attributes/{attr['id']}/",
            json={"title": None},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] is None

    async def test_patch_omitted_field_unchanged(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Send {"description": "x"}, verify title is unchanged."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        list_resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attr = next(
            a for a in list_resp.json()["attributes"] if a["field_name"] == "name"
        )
        original_title = attr["title"]
        resp = await client.patch(
            f"/datasets/{ds.id}/attributes/{attr['id']}/",
            json={"description": "A description"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == original_title
        assert resp.json()["description"] == "A description"

    async def test_patch_invalid_semantic_role_422(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Send bad semantic_role value, expect 422."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        list_resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attr = list_resp.json()["attributes"][0]
        resp = await client.patch(
            f"/datasets/{ds.id}/attributes/{attr['id']}/",
            json={"semantic_role": "invalid_role"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_patch_invalid_domain_type_422(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Send bad domain_type value, expect 422."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)
        list_resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        attr = list_resp.json()["attributes"][0]
        resp = await client.patch(
            f"/datasets/{ds.id}/attributes/{attr['id']}/",
            json={"domain_type": "nonexistent_type"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# is_current flag tests
# ---------------------------------------------------------------------------


class TestAttributeCurrentFlag:
    async def test_list_excludes_removed_by_default(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Rows with is_current=false are excluded from default list."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)

        # Mark one attribute as removed
        result = await test_db_session.execute(
            select(AttributeMetadata).where(
                AttributeMetadata.dataset_id == ds.id,
                AttributeMetadata.field_name == "name",
            )
        )
        attr = result.scalar_one()
        attr.is_current = False
        await test_db_session.commit()

        resp = await client.get(
            f"/datasets/{ds.id}/attributes/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        field_names = {a["field_name"] for a in resp.json()["attributes"]}
        assert "name" not in field_names
        assert resp.json()["total"] == 4

    async def test_list_include_removed_param(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """include_removed=true returns all rows including removed."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)

        # Mark one attribute as removed
        result = await test_db_session.execute(
            select(AttributeMetadata).where(
                AttributeMetadata.dataset_id == ds.id,
                AttributeMetadata.field_name == "name",
            )
        )
        attr = result.scalar_one()
        attr.is_current = False
        await test_db_session.commit()

        resp = await client.get(
            f"/datasets/{ds.id}/attributes/?include_removed=true",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        field_names = {a["field_name"] for a in resp.json()["attributes"]}
        assert "name" in field_names
        assert resp.json()["total"] == 5

    async def test_reupload_marks_removed_columns(
        self,
        test_db_session: AsyncSession,
    ):
        """Remove column from refresh, verify is_current=false."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)

        # Simulate re-upload with a subset of columns (name column removed)
        from app.processing.ingest.metadata import refresh_attribute_metadata

        new_column_info = [
            {
                "name": "pop_2020",
                "type": "integer",
                "ordinal_position": 2,
                "is_nullable": True,
            },
            {
                "name": "area_sqkm",
                "type": "double precision",
                "ordinal_position": 3,
                "is_nullable": True,
            },
            {
                "name": "created_date",
                "type": "date",
                "ordinal_position": 4,
                "is_nullable": True,
            },
        ]
        await refresh_attribute_metadata(
            test_db_session,
            ds.id,
            new_column_info,
            geometry_type="POINT",
        )
        await test_db_session.commit()

        # Check that "name" is now is_current=false
        result = await test_db_session.execute(
            select(AttributeMetadata).where(
                AttributeMetadata.dataset_id == ds.id,
                AttributeMetadata.field_name == "name",
            )
        )
        attr = result.scalar_one()
        assert attr.is_current is False


# ---------------------------------------------------------------------------
# Cascade delete tests
# ---------------------------------------------------------------------------


class TestAttributeCascadeDelete:
    async def test_delete_dataset_cascades_attributes(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Delete dataset, verify no attribute_metadata rows remain."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(
            test_db_session, created_by=admin_id, name="Cascade Attr Test"
        )
        dataset_id = ds.id

        # Verify attributes exist
        result = await test_db_session.execute(
            select(AttributeMetadata).where(AttributeMetadata.dataset_id == dataset_id)
        )
        assert len(result.all()) > 0

        # Delete the dataset
        await client.request(
            "DELETE",
            f"/datasets/{dataset_id}",
            json={"confirm_title": "Cascade Attr Test"},
            headers=admin_auth_header,
        )

        # Verify attributes are gone
        result = await test_db_session.execute(
            select(AttributeMetadata).where(AttributeMetadata.dataset_id == dataset_id)
        )
        assert len(result.all()) == 0


# ---------------------------------------------------------------------------
# Unique constraint tests
# ---------------------------------------------------------------------------


class TestAttributeUniqueConstraint:
    async def test_unique_dataset_field_name(
        self,
        test_db_session: AsyncSession,
    ):
        """Verify unique constraint prevents duplicate (dataset_id, field_name)."""
        from sqlalchemy.exc import IntegrityError

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset_with_attributes(test_db_session, created_by=admin_id)

        # Try to insert a duplicate field_name for same dataset
        duplicate = AttributeMetadata(
            dataset_id=ds.id,
            field_name="name",  # already exists
            title="Duplicate",
            is_current=True,
        )
        test_db_session.add(duplicate)
        with pytest.raises(IntegrityError):
            await test_db_session.flush()
        await test_db_session.rollback()
