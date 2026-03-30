"""Performance regression tests for critical API paths.

These tests lock in latency gains from Phases 178-181 by asserting
wall-clock time stays under generous thresholds (3x p95 baselines).

Run with: pytest -m perf -v
Excluded from default runs via pyproject.toml addopts.
"""

import time
import uuid

import asyncpg
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

import app.tiles.pool as pool_module
from app.auth.models import User
from app.config import settings
from app.datasets.models import Dataset, Record

# ---------------------------------------------------------------------------
# Thresholds: 3x Phase 181 p95 values (generous to avoid flake)
# Source: tests/load/results/baseline_stats.csv
# ---------------------------------------------------------------------------
SEARCH_THRESHOLD_MS = 200  # p95=12ms, p50=3ms
TILE_THRESHOLD_MS = 500  # p95=38ms, p50=11ms
ROWS_THRESHOLD_MS = 500  # p95=37ms, p50=17ms
DETAIL_THRESHOLD_MS = 500  # p95=43ms, p50=16ms
BROWSE_THRESHOLD_MS = 500  # p95=33ms, p50=16ms


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def _perf_dataset(client: AsyncClient, test_db_session):
    """Create a dataset with a data table for perf tests.

    Function-scoped to match client/test_db_session scope.
    The small overhead is acceptable for a 5-test suite.
    """
    table_name = f"perf_test_{uuid.uuid4().hex[:8]}"

    # Get admin user ID
    result = await test_db_session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    user = result.scalar_one()

    # Create Record + Dataset
    record = Record(
        title="Perf Test Dataset",
        summary="Dataset for performance regression tests",
        theme_category=["test"],
        visibility="public",
        record_status="published",
        created_by=user.id,
    )
    test_db_session.add(record)
    await test_db_session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="Point",
        feature_count=1,
        source_format="geojson",
        source_filename="test.geojson",
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "geom", "type": "geometry"},
            {"name": "geom_4326", "type": "geometry"},
        ],
    )
    test_db_session.add(dataset)
    await test_db_session.commit()
    await test_db_session.refresh(dataset)

    # Create actual data table with geometry and spatial index
    await test_db_session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  name TEXT,"
            f"  geom GEOMETRY(Point, 3857),"
            f"  geom_4326 GEOMETRY(Point, 4326)"
            f")"
        )
    )
    await test_db_session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_geom_4326 "
            f"ON data.{table_name} USING GIST (geom_4326)"
        )
    )
    # Insert a point at (0, 0)
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{table_name} (name, geom, geom_4326) VALUES ("
            f"  'perf_test_point',"
            f"  ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857),"
            f"  ST_SetSRID(ST_MakePoint(0, 0), 4326)"
            f")"
        )
    )
    await test_db_session.commit()

    yield (str(dataset.id), table_name)

    # Cleanup
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await test_db_session.commit()


@pytest.fixture
async def _perf_tile_pool(_perf_dataset):
    """Initialize asyncpg pool for tile endpoint tests.

    Depends on _perf_dataset (which depends on client) to ensure the test DB
    is fully set up before the raw asyncpg pool connects.

    Derives the DSN from the active test engine (patched by client fixture)
    rather than settings, because other test modules may pollute env vars
    during collection.
    """
    import app.database as db_module

    sa_url = db_module.engine.url.render_as_string(hide_password=False)
    dsn = sa_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(
        dsn=dsn, min_size=1, max_size=3, command_timeout=10
    )
    original_pool = pool_module._tile_pool
    pool_module._tile_pool = pool
    yield
    await pool.close()
    pool_module._tile_pool = original_pool


# ---------------------------------------------------------------------------
# Performance regression tests
# ---------------------------------------------------------------------------


@pytest.mark.perf
async def test_search_latency(
    client: AsyncClient, admin_auth_header: dict, _perf_dataset
):
    """GET /search/datasets/?q=test completes under threshold."""
    url = "/search/datasets/?q=test"

    # Warm-up
    await client.get(url, headers=admin_auth_header)

    # Measured request
    start = time.perf_counter()
    resp = await client.get(url, headers=admin_auth_header)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert resp.status_code == 200
    assert elapsed_ms < SEARCH_THRESHOLD_MS, (
        f"Search took {elapsed_ms:.1f}ms (threshold: {SEARCH_THRESHOLD_MS}ms)"
    )


@pytest.mark.perf
async def test_tile_latency(
    client: AsyncClient,
    admin_auth_header: dict,
    _perf_dataset,
    _perf_tile_pool,
):
    """GET /tiles/data.{table}/0/0/0.pbf completes under threshold."""
    _, table_name = _perf_dataset
    url = f"/tiles/data.{table_name}/0/0/0.pbf"

    # Warm-up
    await client.get(url, headers=admin_auth_header)

    # Measured request
    start = time.perf_counter()
    resp = await client.get(url, headers=admin_auth_header)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert resp.status_code == 200
    assert elapsed_ms < TILE_THRESHOLD_MS, (
        f"Tile took {elapsed_ms:.1f}ms (threshold: {TILE_THRESHOLD_MS}ms)"
    )


@pytest.mark.perf
async def test_dataset_rows_latency(
    client: AsyncClient, admin_auth_header: dict, _perf_dataset
):
    """GET /datasets/{id}/rows completes under threshold."""
    dataset_id, _ = _perf_dataset
    url = f"/datasets/{dataset_id}/rows/"

    # Warm-up
    await client.get(url, headers=admin_auth_header)

    # Measured request
    start = time.perf_counter()
    resp = await client.get(url, headers=admin_auth_header)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert resp.status_code == 200
    assert elapsed_ms < ROWS_THRESHOLD_MS, (
        f"Rows took {elapsed_ms:.1f}ms (threshold: {ROWS_THRESHOLD_MS}ms)"
    )


@pytest.mark.perf
async def test_dataset_detail_latency(
    client: AsyncClient, admin_auth_header: dict, _perf_dataset
):
    """GET /datasets/{id} completes under threshold."""
    dataset_id, _ = _perf_dataset
    url = f"/datasets/{dataset_id}"

    # Warm-up
    await client.get(url, headers=admin_auth_header)

    # Measured request
    start = time.perf_counter()
    resp = await client.get(url, headers=admin_auth_header)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert resp.status_code == 200
    assert elapsed_ms < DETAIL_THRESHOLD_MS, (
        f"Detail took {elapsed_ms:.1f}ms (threshold: {DETAIL_THRESHOLD_MS}ms)"
    )


@pytest.mark.perf
async def test_browse_latency(
    client: AsyncClient, admin_auth_header: dict, _perf_dataset
):
    """GET /datasets/?limit=50 completes under threshold."""
    url = "/datasets/?limit=50"

    # Warm-up
    await client.get(url, headers=admin_auth_header)

    # Measured request
    start = time.perf_counter()
    resp = await client.get(url, headers=admin_auth_header)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert resp.status_code == 200
    assert elapsed_ms < BROWSE_THRESHOLD_MS, (
        f"Browse took {elapsed_ms:.1f}ms (threshold: {BROWSE_THRESHOLD_MS}ms)"
    )
