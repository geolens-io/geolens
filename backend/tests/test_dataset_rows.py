"""Integration tests for the GET /datasets/{id}/rows endpoint.

These tests run against a real database via httpx ASGITransport. A small test
table is created in the data schema to provide actual rows for pagination tests.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.catalog.datasets.domain.models import Dataset

from tests.factories import create_dataset, get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    if column_info is None:
        column_info = [
            {"name": "gid", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "pop", "type": "integer"},
        ]
    return await create_dataset(
        session,
        created_by=created_by,
        name=name,
        table_name=table_name,
        visibility=visibility,
        srid=srid,
        geometry_type=geometry_type,
        feature_count=feature_count,
        description=description,
        column_info=column_info,
    )


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

    admin_id = await get_user_id(test_db_session, "admin")
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

    admin_id = await get_user_id(test_db_session, "admin")
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

        admin_id = await get_user_id(test_db_session, "admin")
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
# CQL2 filter tests
# ---------------------------------------------------------------------------


def _cql2_eq(column: str, value: str) -> str:
    """A CQL2-JSON equality filter body for one column and value."""
    return json.dumps({"op": "=", "args": [{"property": column}, value]})


class TestRowsCql2Filter:
    @pytest.mark.anyio
    async def test_cql2_filter_narrows_rows_and_absent_returns_all(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """Without `filter` the unfiltered page comes back; with it, only the
        matching rows. The empty result must not read as the absent case."""
        unfiltered = await client.get(
            f"/datasets/{rows_dataset.id}/rows/", headers=admin_auth_header
        )
        assert unfiltered.status_code == 200
        assert len(unfiltered.json()["rows"]) == 5

        resp = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={"filter": _cql2_eq("name", "b")},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert [row["name"] for row in data["rows"]] == ["b"]
        assert data["next_cursor"] is None

    @pytest.mark.anyio
    async def test_cql2_filter_matches_zero_rows_returns_empty_page(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """A filter matching nothing is 200 with an empty page, not a 400
        and not the unfiltered page."""
        resp = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={
                "filter": json.dumps({"op": ">", "args": [{"property": "value"}, 100]})
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rows"] == []
        assert data["next_cursor"] is None

    @pytest.mark.anyio
    async def test_cql2_filter_combines_with_column_filter(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """The CQL2 expression ANDs with the ILIKE column filter.

        Two requests isolate each limb: value >= 2 AND name ILIKE %b% keeps
        exactly b, and value >= 3 AND name ILIKE %b% keeps nothing — an
        implementation that ignores either limb fails the second request."""
        resp = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={
                "filter": json.dumps({"op": ">=", "args": [{"property": "value"}, 2]}),
                "filter[name]": "b",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert [row["name"] for row in data["rows"]] == ["b"]

        stricter = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={
                "filter": json.dumps({"op": ">=", "args": [{"property": "value"}, 3]}),
                "filter[name]": "b",
            },
            headers=admin_auth_header,
        )
        assert stricter.status_code == 200
        assert stricter.json()["rows"] == []

    @pytest.mark.anyio
    async def test_cql2_filter_combines_with_sort_and_after_cursor(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """Sorted keyset paging continues correctly over the filtered row set.

        value >= 2 leaves b(2), c(3), d(4), e(5); ordered by value desc in
        pages of two: [e, d] then [c, b]."""
        page1 = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={
                "filter": json.dumps({"op": ">=", "args": [{"property": "value"}, 2]}),
                "sort": "value",
                "order": "desc",
                "limit": 2,
            },
            headers=admin_auth_header,
        )
        assert page1.status_code == 200
        data1 = page1.json()
        assert [row["value"] for row in data1["rows"]] == [5, 4]
        assert data1["next_cursor"] is not None

        page2 = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={
                "filter": json.dumps({"op": ">=", "args": [{"property": "value"}, 2]}),
                "sort": "value",
                "order": "desc",
                "limit": 2,
                "after": data1["next_cursor"],
            },
            headers=admin_auth_header,
        )
        assert page2.status_code == 200
        data2 = page2.json()
        assert [row["value"] for row in data2["rows"]] == [3, 2]
        # A full page always carries a cursor (the last row's gid), even with
        # nothing behind it; the filtered end is proven by one more empty page.
        assert data2["next_cursor"] == data2["rows"][-1]["gid"]

        page3 = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={
                "filter": json.dumps({"op": ">=", "args": [{"property": "value"}, 2]}),
                "sort": "value",
                "order": "desc",
                "limit": 2,
                "after": data2["next_cursor"],
            },
            headers=admin_auth_header,
        )
        assert page3.status_code == 200
        assert page3.json()["rows"] == []
        assert page3.json()["next_cursor"] is None

    @pytest.mark.anyio
    async def test_cql2_filter_malformed_returns_400(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """A filter that is not valid JSON is the caller's fault: 400."""
        resp = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={"filter": '{"op": "=", '},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_cql2_filter_parser_depth_failure_returns_400(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
        monkeypatch,
    ):
        """A filter that defeats the JSON parser's own depth limit is the
        caller's bug too: ``json.loads`` raises RecursionError for a deeply
        nested body (on Pythons where that crossover sits below the HTTP
        client's maximum URL length, a literal probe cannot reach the
        server), which is no ValueError and must still answer 400, not
        500."""
        from app.modules.catalog.datasets.api import router_data

        real_loads = router_data.json.loads

        def too_deep(expr: str, **kwargs):
            """json.loads stand-in that hits the parser depth limit on the probe body alone."""
            # Raise only for the probe body; every other parse (the auth
            # token among them) must behave normally.
            if expr == "deep-probe":
                raise RecursionError
            return real_loads(expr, **kwargs)

        monkeypatch.setattr(router_data.json, "loads", too_deep)
        resp = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={"filter": "deep-probe"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_cql2_filter_unknown_column_returns_400(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """A filter naming a column the table lacks is 400, not a silent
        no-op or a 5xx."""
        resp = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={"filter": _cql2_eq("nonexistent_column", "x")},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_cql2_filter_null_is_malformed_not_absent(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        rows_dataset,
    ):
        """A present-but-null filter is a malformed expression, not an
        absent one: the param's absence means unfiltered, `filter=null`
        means the caller sent something that is not an expression."""
        absent = await client.get(
            f"/datasets/{rows_dataset.id}/rows/", headers=admin_auth_header
        )
        assert absent.status_code == 200
        assert len(absent.json()["rows"]) == 5

        null = await client.get(
            f"/datasets/{rows_dataset.id}/rows/",
            params={"filter": "null"},
            headers=admin_auth_header,
        )
        assert null.status_code == 400

    @pytest.mark.anyio
    async def test_cql2_filter_keeps_access_guard(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
        rows_table,
    ):
        """The access guard runs before the filter is ever compiled.

        Pinned in both directions: a VALID filter on a dataset the caller
        cannot see stays 404, and so does an INVALID one — a caller who
        cannot see the dataset must never learn its column set from a
        400 that names the unknown column."""
        leftover = await test_db_session.execute(
            select(Dataset).where(Dataset.table_name == rows_table)
        )
        existing = leftover.scalar_one_or_none()
        if existing:
            await test_db_session.delete(existing)
            await test_db_session.commit()

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            name="PrivateCql2RowsDS",
            table_name=rows_table,
            column_info=TEST_COLUMN_INFO,
        )

        resp = await client.get(
            f"/datasets/{ds.id}/rows/",
            params={"filter": _cql2_eq("name", "b")},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 404

        # The guard-first ordering disagreement row: compiling before the
        # guard would answer 400 here and leak the column set.
        invalid = await client.get(
            f"/datasets/{ds.id}/rows/",
            params={"filter": _cql2_eq("nonexistent_column", "x")},
            headers=viewer_auth_header,
        )
        assert invalid.status_code == 404

        # An unknown dataset with a syntactically valid filter stays 404 too.
        fake = await client.get(
            f"/datasets/{uuid.uuid4()}/rows/",
            params={"filter": _cql2_eq("name", "b")},
            headers=admin_auth_header,
        )
        assert fake.status_code == 404


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


# ---------------------------------------------------------------------------
# Value serialization
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_rows_serialize_bit_and_bytea_values(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """asyncpg hands back BitString and raw bytes, which the JSON response can't
    carry as-is; a non-UTF-8 byte made bytea fail the same way."""
    table = f"test_rows_bits_{uuid.uuid4().hex[:8]}"
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, flags bit(8), "
            "mask bit varying, empty bit varying, gone bit varying, pairs bit(2)[], "
            "raw bytea)"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{table} (flags, mask, empty, gone, pairs, raw) "
            "VALUES (B'10101010', B'00101', B'', NULL, ARRAY[B'01', B'10'], "
            "'\\xff00'::bytea)"
        )
    )
    await test_db_session.commit()
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_dataset(
        test_db_session,
        created_by=admin_id,
        table_name=table,
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "flags", "type": "bit"},
            {"name": "mask", "type": "bit varying"},
            {"name": "empty", "type": "bit varying"},
            {"name": "gone", "type": "bit varying"},
            {"name": "pairs", "type": "ARRAY"},
            {"name": "raw", "type": "bytea"},
        ],
    )
    try:
        url = f"/datasets/{ds.id}/rows/"
        resp = await client.get(url, headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        row = resp.json()["rows"][0]
        assert row["flags"] == "10101010"
        assert row["mask"] == "00101"
        assert row["empty"] == ""
        assert row["gone"] is None
        assert row["pairs"] == ["01", "10"]
        assert row["raw"] == "\\xff00"
        # The returned text is PostgreSQL's own, so filtering by it finds the row.
        for column in ("flags", "mask"):
            found = await client.get(
                url,
                params={f"filter[{column}]": row[column]},
                headers=admin_auth_header,
            )
            assert [r["gid"] for r in found.json()["rows"]] == [row["gid"]]
    finally:
        await test_db_session.execute(
            text(
                "DELETE FROM catalog.records WHERE id IN "
                "(SELECT record_id FROM catalog.datasets WHERE table_name = :t)"
            ).bindparams(t=table)
        )
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
        await test_db_session.commit()
