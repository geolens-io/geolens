"""Tests for the has_quicklook predicate and the reconcile_quicklook_uris sweeper.

Covers four cases:
1. dataset_to_ogc_record reports has_quicklook=False when quicklook_256_uri is None.
2. dataset_to_ogc_record reports has_quicklook=True when quicklook_256_uri is set.
3. reconcile() clears a stale URI (storage.exists() returns False) and then
   dataset_to_ogc_record reports has_quicklook=False.
4. reconcile() preserves a present URI (storage.exists() returns True) and
   dataset_to_ogc_record still reports has_quicklook=True.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.search.service_records import dataset_to_ogc_record
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
