"""Integration tests for the GET /datasets/{id}/rows endpoint.

These tests run against a real database via httpx ASGITransport. A small test
table is created in the data schema to provide actual rows for pagination tests.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.auth.models import User
from app.datasets.models import Dataset, Record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_id(session, username: str) -> uuid.UUID:
    """Look up a user's ID by username."""
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
    srid: int = 4326,
    geometry_type: str | None = "MultiPolygon",
    feature_count: int = 42,
    description: str | None = "A test dataset",
    column_info: list[dict] | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair directly into the DB."""
    if table_name is None:
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
    if column_info is None:
        column_info = [
            {"name": "gid", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "pop", "type": "integer"},
        ]
    record = Record(
        title=name,
        summary=description,
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
        srid=srid,
        geometry_type=geometry_type,
        feature_count=feature_count,
        column_info=column_info,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_TABLE_NAME = f"test_rows_{uuid.uuid4().hex[:8]}"
TEST_COLUMN_INFO = [
    {"name": "gid", "type": "integer"},
    {"name": "name", "type": "text"},
    {"name": "value", "type": "integer"},
]


@pytest.fixture
async def rows_table(test_db_session):
    """Create a small test table in the data schema with 5 rows."""
    await test_db_session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{TEST_TABLE_NAME} "
            "(gid serial PRIMARY KEY, name text, value integer)"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{TEST_TABLE_NAME} (name, value) VALUES "
            "('a', 1), ('b', 2), ('c', 3), ('d', 4), ('e', 5)"
        )
    )
    # ANALYZE so pg_class.reltuples is populated
    await test_db_session.execute(text(f"ANALYZE data.{TEST_TABLE_NAME}"))
    await test_db_session.commit()

    yield TEST_TABLE_NAME

    # Teardown: drop the test table
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{TEST_TABLE_NAME}"))
    await test_db_session.commit()


@pytest.fixture
async def rows_dataset(test_db_session, rows_table, admin_auth_header):
    """Create a dataset record pointing to the test rows table."""
    # Clean up any leftover dataset record from a previous test run
    leftover = await test_db_session.execute(
        select(Dataset).where(Dataset.table_name == rows_table)
    )
    existing = leftover.scalar_one_or_none()
    if existing:
        await test_db_session.delete(existing)
        await test_db_session.commit()

    admin_id = await _get_user_id(test_db_session, "admin")
    ds = await _create_dataset(
        test_db_session,
        created_by=admin_id,
        name="Rows Test Dataset",
        table_name=rows_table,
        visibility="public",
        column_info=TEST_COLUMN_INFO,
    )

    yield ds

    # Teardown: remove the record (cascades to dataset)
    await test_db_session.execute(
        text(
            f"DELETE FROM catalog.records WHERE id IN "
            f"(SELECT record_id FROM catalog.datasets WHERE table_name = '{rows_table}')"
        )
    )
    await test_db_session.commit()


# ---------------------------------------------------------------------------
# Fixture: table with geometry columns (to test exclusion)
# ---------------------------------------------------------------------------

TEST_GEOM_TABLE_NAME = f"test_rows_geom_{uuid.uuid4().hex[:8]}"
TEST_GEOM_COLUMN_INFO = [
    {"name": "gid", "type": "integer"},
    {"name": "name", "type": "text"},
    {"name": "geom", "type": "USER-DEFINED"},
    {"name": "geom_4326", "type": "USER-DEFINED"},
]


@pytest.fixture
async def geom_rows_table(test_db_session):
    """Create a test table with geometry columns."""
    await test_db_session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{TEST_GEOM_TABLE_NAME} "
            "(gid serial PRIMARY KEY, name text, "
            "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326))"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{TEST_GEOM_TABLE_NAME} (name, geom, geom_4326) VALUES "
            "('p1', ST_MakePoint(0, 0), ST_MakePoint(0, 0)), "
            "('p2', ST_MakePoint(1, 1), ST_MakePoint(1, 1))"
        )
    )
    await test_db_session.execute(text(f"ANALYZE data.{TEST_GEOM_TABLE_NAME}"))
    await test_db_session.commit()

    yield TEST_GEOM_TABLE_NAME

    await test_db_session.execute(
        text(f"DROP TABLE IF EXISTS data.{TEST_GEOM_TABLE_NAME}")
    )
    await test_db_session.commit()


@pytest.fixture
async def geom_rows_dataset(test_db_session, geom_rows_table, admin_auth_header):
    """Create a dataset with geometry columns."""
    leftover = await test_db_session.execute(
        select(Dataset).where(Dataset.table_name == geom_rows_table)
    )
    existing = leftover.scalar_one_or_none()
    if existing:
        await test_db_session.delete(existing)
        await test_db_session.commit()

    admin_id = await _get_user_id(test_db_session, "admin")
    ds = await _create_dataset(
        test_db_session,
        created_by=admin_id,
        name="Geom Rows Test Dataset",
        table_name=geom_rows_table,
        visibility="public",
        column_info=TEST_GEOM_COLUMN_INFO,
    )

    yield ds

    await test_db_session.execute(
        text(
            f"DELETE FROM catalog.records WHERE id IN "
            f"(SELECT record_id FROM catalog.datasets WHERE table_name = '{geom_rows_table}')"
        )
    )
    await test_db_session.commit()


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestRowsAuth:
    @pytest.mark.anyio
    async def test_rows_anonymous_nonexistent_returns_404(self, client: AsyncClient):
        """GET /datasets/{uuid}/rows without token returns 404 for nonexistent dataset."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/datasets/{fake_id}/rows/")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_rows_dataset_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /datasets/{random_uuid}/rows with auth returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/datasets/{fake_id}/rows/", headers=admin_auth_header)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Visibility tests
# ---------------------------------------------------------------------------


class TestRowsVisibility:
    @pytest.mark.anyio
    async def test_rows_private_dataset_hidden_from_viewer(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
        rows_table,
    ):
        """Private dataset owned by admin: viewer gets 404, admin gets 200."""
        # Clean up any leftover dataset record
        leftover = await test_db_session.execute(
            select(Dataset).where(Dataset.table_name == rows_table)
        )
        existing = leftover.scalar_one_or_none()
        if existing:
            await test_db_session.delete(existing)
            await test_db_session.commit()

        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            name="PrivateRowsDS",
            table_name=rows_table,
            column_info=TEST_COLUMN_INFO,
        )

        # Viewer cannot access rows
        resp = await client.get(f"/datasets/{ds.id}/rows/", headers=viewer_auth_header)
        assert resp.status_code == 404

        # Admin can access rows
        resp = await client.get(f"/datasets/{ds.id}/rows/", headers=admin_auth_header)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Successful response tests
# ---------------------------------------------------------------------------


class TestRowsResponse:
    @pytest.mark.anyio
    async def test_rows_response_shape(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """GET /datasets/{id}/rows returns rows, approximate_total, next_cursor, and columns."""
        resp = await client.get(
            f"/datasets/{rows_dataset.id}/rows/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "rows" in data
        assert "approximate_total" in data
        assert "next_cursor" in data
        assert "columns" in data
        assert isinstance(data["rows"], list)
        assert data["approximate_total"] >= 5  # reltuples is approximate
        assert data["columns"] == TEST_COLUMN_INFO

    @pytest.mark.anyio
    async def test_rows_contain_expected_data(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """Rows contain the expected dict keys from the test table."""
        resp = await client.get(
            f"/datasets/{rows_dataset.id}/rows/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["rows"]) == 5
        # Each row should have gid, name, value keys
        for row in data["rows"]:
            assert "gid" in row
            assert "name" in row
            assert "value" in row

    @pytest.mark.anyio
    async def test_rows_exclude_geometry_columns(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        geom_rows_dataset,
    ):
        """Rows must NOT contain geometry columns (geom, geom_4326)."""
        resp = await client.get(
            f"/datasets/{geom_rows_dataset.id}/rows/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["rows"]) == 2
        for row in data["rows"]:
            assert "geom" not in row
            assert "geom_4326" not in row
            assert "gid" in row
            assert "name" in row


# ---------------------------------------------------------------------------
# Keyset pagination tests
# ---------------------------------------------------------------------------


class TestRowsKeysetPagination:
    @pytest.mark.anyio
    async def test_keyset_first_page(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """after=0 returns first page of rows ordered by gid."""
        resp = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={"limit": 2, "after": 0},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rows"]) == 2
        assert data["next_cursor"] is not None
        # Rows should be ordered by gid
        gids = [r["gid"] for r in data["rows"]]
        assert gids == sorted(gids)

    @pytest.mark.anyio
    async def test_keyset_second_page(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """Using next_cursor from page 1 returns page 2 with different rows."""
        # Page 1
        resp1 = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={"limit": 2, "after": 0},
            headers=admin_auth_header,
        )
        data1 = resp1.json()
        cursor = data1["next_cursor"]

        # Page 2
        resp2 = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={"limit": 2, "after": cursor},
            headers=admin_auth_header,
        )
        data2 = resp2.json()
        assert len(data2["rows"]) == 2

        # Pages should have different rows
        gids1 = {r["gid"] for r in data1["rows"]}
        gids2 = {r["gid"] for r in data2["rows"]}
        assert gids1.isdisjoint(gids2)

    @pytest.mark.anyio
    async def test_keyset_last_page(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """Last page returns fewer rows and next_cursor=null."""
        # Get all 5 rows in 3-row pages
        resp1 = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={"limit": 3, "after": 0},
            headers=admin_auth_header,
        )
        data1 = resp1.json()
        assert len(data1["rows"]) == 3
        cursor = data1["next_cursor"]

        # Page 2 should have 2 remaining rows and null cursor
        resp2 = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={"limit": 3, "after": cursor},
            headers=admin_auth_header,
        )
        data2 = resp2.json()
        assert len(data2["rows"]) == 2
        assert data2["next_cursor"] is None

    @pytest.mark.anyio
    async def test_keyset_past_end(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """Cursor past all rows returns empty rows and next_cursor=null."""
        resp = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={"limit": 10, "after": 99999},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rows"]) == 0
        assert data["next_cursor"] is None

    @pytest.mark.anyio
    async def test_keyset_with_filter(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """Filters still work with keyset pagination."""
        resp = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={"limit": 10, "after": 0, "filter[name]": "a"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rows"]) == 1
        assert data["rows"][0]["name"] == "a"


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestRowsValidation:
    @pytest.mark.anyio
    async def test_rows_limit_too_low(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """limit=0 returns 422 (below minimum of 1)."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/datasets/{fake_id}/rows/",
            params={"limit": 0},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_rows_limit_too_high(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """limit=501 returns 422 (above maximum of 500)."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/datasets/{fake_id}/rows/",
            params={"limit": 501},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
