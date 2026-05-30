"""Regression tests for SEC-01: vector-tile egress authorization.

Pins the anonymous denial of public-unpublished vector tile tokens AND tile
bytes so the leak cannot return silently.  Covers:

  (a) anonymous single-token endpoint (GET /tiles/token/{id}/)
  (b) anonymous batch-token endpoint (POST /tiles/tokens/)
  (c) anonymous raw tile endpoint (GET /tiles/data.{table}/{z}/{x}/{y}.pbf)
      — the literal leak path that served 1842 bytes of MVT to anon
  (d) anonymous cluster-tile endpoint (GET /tiles/clusters/data.{table}/...pbf)
  (e) POSITIVE over-gating guards — public + published still mints a token AND
      serves raw tile bytes for anon

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
  - Run with: set -a && source ../.env.test && set +a
               uv run pytest tests/test_vector_tile_auth.py -v
"""

import uuid

import asyncpg
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.auth.models import User
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.conftest import _run_with_too_many_clients_retry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_admin_id(session) -> uuid.UUID:
    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    return result.scalar_one().id


async def _create_vector_dataset(
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
    record_status: str = "published",
    geometry_type: str | None = None,
) -> tuple[Record, Dataset]:
    """Create a vector Record + Dataset for contrast tests.

    When ``geometry_type`` is provided the Dataset is given the point-family
    metadata (srid + column_info) needed for the raw/cluster .pbf serving path
    to reach the authorization gate rather than failing earlier on a
    null geometry type.
    """
    record = Record(
        title=f"Vector Tile Test {uuid.uuid4().hex[:6]}",
        summary="Dataset for vector tile contrast tests",
        theme_category=["test"],
        visibility=visibility,
        record_status=record_status,
        record_type="vector_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset_kwargs: dict = {
        "record_id": record.id,
        "table_name": f"vector_tile_test_{uuid.uuid4().hex[:8]}",
        "source_format": "geojson",
        "source_filename": "test.geojson",
    }
    if geometry_type is not None:
        dataset_kwargs.update(
            srid=4326,
            geometry_type=geometry_type,
            feature_count=1,
            column_info=[
                {"name": "gid", "type": "integer"},
                {"name": "name", "type": "text"},
                {"name": "value", "type": "integer"},
                {"name": "geom", "type": "geometry"},
                {"name": "geom_4326", "type": "geometry"},
            ],
        )
    dataset = Dataset(**dataset_kwargs)
    session.add(dataset)
    await session.flush()
    await session.commit()
    await session.refresh(dataset)
    return record, dataset


async def _create_point_data_table(session, table_name: str) -> None:
    """Create a PostGIS point data table with one feature inside tile 0/0/0."""
    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  name TEXT,"
            f"  value INTEGER,"
            f"  geom GEOMETRY(Point, 3857),"
            f"  geom_4326 GEOMETRY(Point, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_geom_4326 "
            f"ON data.{table_name} USING GIST (geom_4326)"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (name, value, geom, geom_4326) VALUES ("
            f"  'test_point', 42,"
            f"  ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857),"
            f"  ST_SetSRID(ST_MakePoint(0, 0), 4326)"
            f")"
        )
    )
    await session.commit()


async def _cleanup_data_table(session, table_name: str) -> None:
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await session.commit()


async def _get_auth_header(client: AsyncClient, username: str, password: str) -> dict:
    resp = await client.post(
        "/auth/login", data={"username": username, "password": password}
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def _init_tile_pool_for_tests():
    """Initialize a real asyncpg pool pointing at the test database for tile tests.

    The test client uses ASGITransport which does not run the app lifespan,
    so the tile serving pool must be created manually.  Mirrors the fixture in
    test_tiles.py.  The denial tests short-circuit at the auth gate (404) before
    the pool is touched; the positive serving guard needs the pool live.
    """
    import app.processing.tiles.pool as pool_module

    dsn = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await _run_with_too_many_clients_retry(
        lambda: asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3, command_timeout=10)
    )
    pool_module._tile_pool = pool
    yield
    await pool.close()
    pool_module._tile_pool = None


# ---------------------------------------------------------------------------
# SEC-01 regression tests
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestVectorTileEgressAuthorization:
    """Regression coverage for SEC-01: anon callers must not receive tile tokens
    or tile bytes for public + non-published vector datasets."""

    async def test_anon_single_token_denied_for_public_unpublished(
        self, client: AsyncClient, test_db_session
    ):
        """Anonymous GET /tiles/token/{id}/ must be denied (401 or 404) for a
        public + non-published vector dataset.

        Before the SEC-01 fix this returned 200 with a minted HMAC sig (the leak).
        """
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset = await _create_vector_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            record_status="internal",
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")

        assert resp.status_code in (401, 404), (
            f"Expected 401 or 404 for anon on public+unpublished, got {resp.status_code}: {resp.text}"
        )

    async def test_anon_batch_token_denied_for_public_unpublished(
        self, client: AsyncClient, test_db_session
    ):
        """Anonymous POST /tiles/tokens/ must return 200 (batch never fails the
        request) but the per-dataset entry must carry an 'error' key and NO 'sig'.

        Before the SEC-01 fix the batch endpoint minted an HMAC sig for the
        public+unpublished dataset regardless of anonymous status.
        """
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset = await _create_vector_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            record_status="internal",
        )

        resp = await client.post(
            "/tiles/tokens/",
            json={"dataset_ids": [str(dataset.id)]},
        )

        assert resp.status_code == 200, (
            f"Batch token endpoint must always return 200, got {resp.status_code}"
        )
        tokens = resp.json()["tokens"]
        dataset_key = str(dataset.id)
        assert dataset_key in tokens, f"Expected key '{dataset_key}' in tokens response"
        entry = tokens[dataset_key]
        assert "error" in entry, (
            f"Expected 'error' key for public+unpublished anon request, got: {entry}"
        )
        assert "sig" not in entry, (
            f"HMAC sig must NOT be minted for public+unpublished anon request, got: {entry}"
        )

    async def test_anon_raw_pbf_denied_for_public_unpublished(
        self, client: AsyncClient, test_db_session
    ):
        """Anonymous GET /tiles/data.{table}/{z}/{x}/{y}.pbf must be denied (404)
        for a public + non-published vector dataset.

        This is the LITERAL leak path measured at "200 + 1842 bytes of MVT".  The
        dataset is given a real point backing table so the request reaches the
        authorization gate in _authorize_vector_tile_request rather than failing
        earlier on a missing table / null geometry.  Before the SEC-01 fix this
        returned 200 with MVT feature bytes.
        """
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset = await _create_vector_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            record_status="internal",
            geometry_type="Point",
        )
        await _create_point_data_table(test_db_session, dataset.table_name)
        try:
            resp = await client.get(f"/tiles/data.{dataset.table_name}/0/0/0.pbf")
            assert resp.status_code == 404, (
                f"Expected 404 (auth gate) for anon raw .pbf on public+unpublished, "
                f"got {resp.status_code} ({len(resp.content)} bytes): {resp.text[:200]}"
            )
        finally:
            await _cleanup_data_table(test_db_session, dataset.table_name)

    async def test_anon_cluster_tile_denied_for_public_unpublished(
        self, client: AsyncClient, test_db_session
    ):
        """Anonymous GET /tiles/clusters/data.{table}/{z}/{x}/{y}.pbf must be
        denied (404) for a public + non-published vector dataset.

        With a real point backing table the clusterable gate
        (_ensure_clusterable_dataset) passes, so the request reaches the SEC-01
        authorization gate (_authorize_vector_tile_request) and must return 404 —
        not a 400 from the clusterable gate.  This pins the cluster auth path
        directly (a null-geometry 400 would pass regardless of the fix).
        """
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset = await _create_vector_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            record_status="internal",
            geometry_type="Point",
        )
        await _create_point_data_table(test_db_session, dataset.table_name)
        try:
            resp = await client.get(
                f"/tiles/clusters/data.{dataset.table_name}/0/0/0.pbf"
            )
            assert resp.status_code == 404, (
                f"Expected 404 (auth gate) for anon cluster .pbf on public+unpublished, "
                f"got {resp.status_code}: {resp.text[:200]}"
            )
        finally:
            await _cleanup_data_table(test_db_session, dataset.table_name)

    async def test_anon_single_token_allowed_for_public_published(
        self, client: AsyncClient, test_db_session
    ):
        """POSITIVE over-gating guard: anonymous GET /tiles/token/{id}/ must
        return 200 with a 'sig' present for a public + published vector dataset.

        This guard ensures the SEC-01 fix does not over-gate legitimate anon access
        to publicly published datasets.
        """
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset = await _create_vector_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            record_status="published",
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")

        assert resp.status_code == 200, (
            f"Expected 200 for anon on public+published, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "sig" in body, (
            f"Expected 'sig' in token response for public+published dataset, got: {body}"
        )

    async def test_anon_raw_pbf_allowed_for_public_published(
        self, client: AsyncClient, test_db_session
    ):
        """POSITIVE over-gating guard for the serving path: anonymous raw .pbf on a
        public + published vector dataset must still return 200 with MVT bytes.

        Ensures the SEC-01 status gate does not break legitimate anonymous tile
        serving for published public data.
        """
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset = await _create_vector_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            record_status="published",
            geometry_type="Point",
        )
        await _create_point_data_table(test_db_session, dataset.table_name)
        try:
            resp = await client.get(f"/tiles/data.{dataset.table_name}/0/0/0.pbf")
            assert resp.status_code == 200, (
                f"Expected 200 for anon raw .pbf on public+published, "
                f"got {resp.status_code}: {resp.text[:200]}"
            )
            assert len(resp.content) > 0, "Expected non-empty MVT body for published public tile"
        finally:
            await _cleanup_data_table(test_db_session, dataset.table_name)
