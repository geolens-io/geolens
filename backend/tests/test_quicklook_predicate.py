"""Tests for the has_quicklook predicate and the reconcile_quicklook_uris sweeper.

Covers four cases (vector/table, via Dataset.quicklook_256_uri):
1. dataset_to_ogc_record reports has_quicklook=False when quicklook_256_uri is None.
2. dataset_to_ogc_record reports has_quicklook=True when quicklook_256_uri is set.
3. reconcile() clears a stale URI (storage.exists() returns False) and then
   dataset_to_ogc_record reports has_quicklook=False.
4. reconcile() preserves a present URI (storage.exists() returns True) and
   dataset_to_ogc_record still reports has_quicklook=True.

Plus five new cases (raster_dataset / vrt_dataset, via RasterAsset.quicklook_256_uri):
5. has_quicklook=True for raster_dataset when RasterAsset.quicklook_256_uri is set.
6. has_quicklook=False for raster_dataset when RasterAsset.quicklook_256_uri is None.
7. has_quicklook=True for vrt_dataset when RasterAsset.quicklook_256_uri is set.
8. has_quicklook=False for vrt_dataset when RasterAsset.quicklook_256_uri is None.
9. OGC response properties do NOT leak quicklook_256_uri as a public field.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.search.service_records import dataset_to_ogc_record
from app.processing.raster.models import RasterAsset
from app.processing.raster.queries import fetch_raster_meta_one
from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_quicklook_dataset(
    session,
    *,
    created_by: uuid.UUID,
    quicklook_256_uri: str | None = None,
) -> Dataset:
    """Insert a minimal Record + Dataset pair for quicklook predicate tests."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title="Quicklook Test Dataset",
        summary="Test dataset for quicklook predicate",
        visibility="public",
        record_status="published",
        created_by=created_by,
        record_type="vector_dataset",
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="MultiPoint",
        feature_count=10,
        source_format="geojson",
        source_filename="test.geojson",
        quicklook_256_uri=quicklook_256_uri,
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    # Eagerly load the record + its list relationships so dataset_to_ogc_record
    # (a synchronous function) can access them without triggering async lazy I/O.
    await session.refresh(
        record, attribute_names=["keywords", "contacts", "distributions"]
    )
    dataset.record = record
    return dataset


# ---------------------------------------------------------------------------
# Test 1: has_quicklook is False when URI is None
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_has_quicklook_false_when_uri_null(client: AsyncClient, test_db_session):
    """dataset_to_ogc_record reports has_quicklook=False when quicklook_256_uri is None."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    dataset = await _create_quicklook_dataset(
        session,
        created_by=admin_id,
        quicklook_256_uri=None,
    )

    result = dataset_to_ogc_record(dataset, "http://test")
    assert result["properties"]["has_quicklook"] is False


# ---------------------------------------------------------------------------
# Test 2: has_quicklook is True when URI is set
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_has_quicklook_true_when_uri_set(client: AsyncClient, test_db_session):
    """dataset_to_ogc_record reports has_quicklook=True when quicklook_256_uri is set.

    Uses ``is True`` (identity check) to guard against regressions where the
    URI being an empty string would still produce a falsy value via bool(uri).
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    dataset_id_stub = uuid.uuid4()
    uri = f"vectors/{dataset_id_stub}/quicklook_256.png"
    dataset = await _create_quicklook_dataset(
        session,
        created_by=admin_id,
        quicklook_256_uri=uri,
    )

    result = dataset_to_ogc_record(dataset, "http://test")
    assert result["properties"]["has_quicklook"] is True


# ---------------------------------------------------------------------------
# Test 3: reconcile() clears a stale URI
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reconcile_clears_stale_uri(
    client: AsyncClient, test_db_session, monkeypatch
):
    """reconcile() NULLs quicklook_256_uri when storage.exists() returns False.

    After reconciliation, dataset_to_ogc_record reports has_quicklook=False.
    """
    from scripts.reconcile_quicklook_uris import reconcile

    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    dataset_id_stub = uuid.uuid4()
    stale_uri = f"vectors/{dataset_id_stub}/quicklook_256.png"
    dataset = await _create_quicklook_dataset(
        session,
        created_by=admin_id,
        quicklook_256_uri=stale_uri,
    )
    assert dataset.quicklook_256_uri == stale_uri

    class _FakeStorage:
        async def exists(self, key: str) -> bool:
            return False  # storage miss — URI is stale

    monkeypatch.setattr("app.platform.storage.get_storage", lambda: _FakeStorage())

    cleared, kept = await reconcile(session)

    # The sweeper should have cleared at least this one row; there may be
    # additional stale rows from other tests sharing the session DB.
    assert cleared >= 1
    assert kept == 0

    # Refresh to pick up the SQL UPDATE via SQLAlchemy's identity map.
    await session.refresh(dataset)
    assert dataset.quicklook_256_uri is None

    # Re-load record + list relationships so the synchronous call has no lazy I/O.
    await session.refresh(
        dataset.record, attribute_names=["keywords", "contacts", "distributions"]
    )

    result = dataset_to_ogc_record(dataset, "http://test")
    assert result["properties"]["has_quicklook"] is False


# ---------------------------------------------------------------------------
# Test 4: reconcile() preserves a present URI
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reconcile_preserves_present_uri(
    client: AsyncClient, test_db_session, monkeypatch
):
    """reconcile() leaves quicklook_256_uri unchanged when storage.exists() returns True.

    After reconciliation, dataset_to_ogc_record still reports has_quicklook=True.
    """
    from scripts.reconcile_quicklook_uris import reconcile

    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    dataset_id_stub = uuid.uuid4()
    present_uri = f"vectors/{dataset_id_stub}/quicklook_256.png"
    dataset = await _create_quicklook_dataset(
        session,
        created_by=admin_id,
        quicklook_256_uri=present_uri,
    )
    assert dataset.quicklook_256_uri == present_uri

    class _FakeStorage:
        async def exists(self, key: str) -> bool:
            return True  # storage hit — URI is valid

    monkeypatch.setattr("app.platform.storage.get_storage", lambda: _FakeStorage())

    cleared, kept = await reconcile(session)

    assert cleared == 0
    assert kept >= 1

    await session.refresh(dataset)
    assert dataset.quicklook_256_uri == present_uri

    # Re-load record + list relationships so the synchronous call has no lazy I/O.
    await session.refresh(
        dataset.record, attribute_names=["keywords", "contacts", "distributions"]
    )

    result = dataset_to_ogc_record(dataset, "http://test")
    assert result["properties"]["has_quicklook"] is True


# ---------------------------------------------------------------------------
# Raster helper
# ---------------------------------------------------------------------------


async def _create_raster_quicklook_dataset(
    session,
    *,
    created_by: uuid.UUID,
    record_type: str,
    raster_quicklook_uri: str | None = None,
) -> Dataset:
    """Insert a minimal Record + Dataset + RasterAsset triple for raster predicate tests."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title="Raster Quicklook Test Dataset",
        summary="Test dataset for raster quicklook predicate",
        visibility="public",
        record_status="published",
        created_by=created_by,
        record_type=record_type,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type=None,
        feature_count=None,
        source_format="geotiff",
        source_filename="test.tif",
        quicklook_256_uri=None,  # always None for raster records; URI lives on RasterAsset
    )
    session.add(dataset)
    await session.flush()
    raster_asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=f"rasters/{dataset.id}/source.cog.tif",
        storage_backend="local",
        quicklook_256_uri=raster_quicklook_uri,
    )
    session.add(raster_asset)
    await session.commit()
    await session.refresh(dataset)
    # Eagerly load the record + its list relationships so dataset_to_ogc_record
    # (a synchronous function) can access them without triggering async lazy I/O.
    await session.refresh(
        record, attribute_names=["keywords", "contacts", "distributions"]
    )
    dataset.record = record
    return dataset


# ---------------------------------------------------------------------------
# Test 5: has_quicklook is True for raster_dataset when RasterAsset URI is set
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_has_quicklook_true_for_raster_dataset_when_raster_asset_uri_set(
    client: AsyncClient, test_db_session
):
    """dataset_to_ogc_record reports has_quicklook=True for raster_dataset with a set RasterAsset.quicklook_256_uri."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    dataset = await _create_raster_quicklook_dataset(
        session,
        created_by=admin_id,
        record_type="raster_dataset",
        raster_quicklook_uri=f"rasters/{uuid.uuid4()}/quicklook_256.png",
    )

    raster_meta = await fetch_raster_meta_one(session, dataset.id)
    result = dataset_to_ogc_record(dataset, "http://test", raster_meta=raster_meta)
    assert result["properties"]["has_quicklook"] is True


# ---------------------------------------------------------------------------
# Test 6: has_quicklook is False for raster_dataset when RasterAsset URI is null
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_has_quicklook_false_for_raster_dataset_when_raster_asset_uri_null(
    client: AsyncClient, test_db_session
):
    """dataset_to_ogc_record reports has_quicklook=False for raster_dataset with no RasterAsset.quicklook_256_uri."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    dataset = await _create_raster_quicklook_dataset(
        session,
        created_by=admin_id,
        record_type="raster_dataset",
        raster_quicklook_uri=None,
    )

    raster_meta = await fetch_raster_meta_one(session, dataset.id)
    result = dataset_to_ogc_record(dataset, "http://test", raster_meta=raster_meta)
    assert result["properties"]["has_quicklook"] is False


# ---------------------------------------------------------------------------
# Test 7: has_quicklook is True for vrt_dataset when RasterAsset URI is set
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_has_quicklook_true_for_vrt_dataset_when_raster_asset_uri_set(
    client: AsyncClient, test_db_session
):
    """dataset_to_ogc_record reports has_quicklook=True for vrt_dataset with a set RasterAsset.quicklook_256_uri."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    dataset = await _create_raster_quicklook_dataset(
        session,
        created_by=admin_id,
        record_type="vrt_dataset",
        raster_quicklook_uri=f"rasters/{uuid.uuid4()}/quicklook_256.png",
    )

    raster_meta = await fetch_raster_meta_one(session, dataset.id)
    result = dataset_to_ogc_record(dataset, "http://test", raster_meta=raster_meta)
    assert result["properties"]["has_quicklook"] is True


# ---------------------------------------------------------------------------
# Test 8: has_quicklook is False for vrt_dataset when RasterAsset URI is null
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_has_quicklook_false_for_vrt_dataset_when_raster_asset_uri_null(
    client: AsyncClient, test_db_session
):
    """dataset_to_ogc_record reports has_quicklook=False for vrt_dataset with no RasterAsset.quicklook_256_uri."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    dataset = await _create_raster_quicklook_dataset(
        session,
        created_by=admin_id,
        record_type="vrt_dataset",
        raster_quicklook_uri=None,
    )

    raster_meta = await fetch_raster_meta_one(session, dataset.id)
    result = dataset_to_ogc_record(dataset, "http://test", raster_meta=raster_meta)
    assert result["properties"]["has_quicklook"] is False


# ---------------------------------------------------------------------------
# Test 9: OGC response properties must NOT leak quicklook_256_uri as a field
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_raster_response_does_not_leak_quicklook_uri_property(
    client: AsyncClient, test_db_session
):
    """The quicklook_256_uri storage key must not appear in the OGC response properties dict."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    dataset = await _create_raster_quicklook_dataset(
        session,
        created_by=admin_id,
        record_type="raster_dataset",
        raster_quicklook_uri=f"rasters/{uuid.uuid4()}/quicklook_256.png",
    )

    raster_meta = await fetch_raster_meta_one(session, dataset.id)
    result = dataset_to_ogc_record(dataset, "http://test", raster_meta=raster_meta)
    assert "quicklook_256_uri" not in result["properties"]
