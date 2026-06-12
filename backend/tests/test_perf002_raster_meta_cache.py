"""Tests for PERF-002: raster tile metadata caching.

Verifies:
  - _resolve_raster_meta returns the same _RasterMeta object on a second call
    (cache hit), avoiding a DB round trip per tile request.
  - _raster_meta_cache is populated after the first call.
  - Authorization is still evaluated per request: a caller who is denied access
    does not inherit a cached allow decision from a previous authorized caller.
"""

import uuid


from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.raster.models import RasterAsset
from app.processing.tiles.router import (
    _RasterMeta,
    _raster_meta_cache,
    _raster_meta_cache_lock,
    _resolve_raster_meta,
)
from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_public_raster(session, *, created_by: uuid.UUID) -> Dataset:
    """Create a minimal public raster dataset with a RasterAsset."""
    record = Record(
        title=f"PERF-002 Raster {uuid.uuid4().hex[:6]}",
        summary="Cache test raster",
        visibility="public",
        record_status="published",
        created_by=created_by,
        record_type="raster_dataset",
        theme_category=["test"],
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"perf002_{uuid.uuid4().hex[:8]}",
        srid=4326,
        geometry_type=None,
        source_format="geotiff",
        source_filename="perf.tif",
    )
    session.add(dataset)
    await session.flush()

    raster_asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=f"rasters/{dataset.id}/perf.cog.tif",
        storage_backend="local",
        band_count=1,
    )
    session.add(raster_asset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_private_raster(session, *, created_by: uuid.UUID) -> Dataset:
    """Create a minimal PRIVATE raster dataset."""
    record = Record(
        title=f"PERF-002 Private {uuid.uuid4().hex[:6]}",
        summary="Private raster for auth cache test",
        visibility="private",
        record_status="published",
        created_by=created_by,
        record_type="raster_dataset",
        theme_category=["test"],
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"perf002_prv_{uuid.uuid4().hex[:8]}",
        srid=4326,
        geometry_type=None,
        source_format="geotiff",
        source_filename="prv.tif",
    )
    session.add(dataset)
    await session.flush()

    raster_asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=f"rasters/{dataset.id}/prv.cog.tif",
        storage_backend="local",
        band_count=1,
    )
    session.add(raster_asset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Unit-level cache tests (integration with real DB session)
# ---------------------------------------------------------------------------


class TestRasterMetaCache:
    """PERF-002: _resolve_raster_meta populates and hits the TTL cache."""

    async def test_cache_populated_on_first_call(self, test_db_session):
        """After the first call, the cache contains an entry for the dataset."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_public_raster(test_db_session, created_by=admin_id)

        # Clear cache entry if left over from a previous test.
        cache_key = str(dataset.id)
        with _raster_meta_cache_lock:
            _raster_meta_cache.pop(cache_key, None)

        meta = await _resolve_raster_meta(test_db_session, dataset.id)

        assert isinstance(meta, _RasterMeta)
        assert meta.visibility == "public"
        assert meta.asset_uri is not None

        with _raster_meta_cache_lock:
            assert cache_key in _raster_meta_cache

    async def test_cache_hit_returns_same_object(self, test_db_session):
        """A second call returns the identical _RasterMeta from the cache (no DB)."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_public_raster(test_db_session, created_by=admin_id)

        cache_key = str(dataset.id)
        with _raster_meta_cache_lock:
            _raster_meta_cache.pop(cache_key, None)

        meta1 = await _resolve_raster_meta(test_db_session, dataset.id)
        meta2 = await _resolve_raster_meta(test_db_session, dataset.id)

        # Same object identity confirms cache was hit (not a second DB round-trip).
        assert meta1 is meta2

    async def test_cached_meta_has_correct_fields(self, test_db_session):
        """Cached metadata contains the expected field values."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_public_raster(test_db_session, created_by=admin_id)

        cache_key = str(dataset.id)
        with _raster_meta_cache_lock:
            _raster_meta_cache.pop(cache_key, None)

        meta = await _resolve_raster_meta(test_db_session, dataset.id)

        assert meta.record_type == "raster_dataset"
        assert meta.storage_backend == "local"
        assert meta.band_count == 1

    async def test_auth_still_denied_after_metadata_cached(
        self, client, admin_auth_header, test_db_session
    ):
        """PERF-002 safety: cached metadata must NOT bypass per-request auth.

        Scenario:
          1. Admin calls raster-auth-check → metadata is cached.
          2. Anonymous caller (no auth) hits the same endpoint.
          3. The anonymous caller MUST be denied (401), not served the admin's
             cached allow decision.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_private_raster(test_db_session, created_by=admin_id)

        cache_key = str(dataset.id)
        with _raster_meta_cache_lock:
            _raster_meta_cache.pop(cache_key, None)

        # Step 1: admin populates the cache.
        admin_resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers=admin_auth_header,
        )
        assert admin_resp.status_code == 200, (
            f"Admin auth-check failed unexpectedly: {admin_resp.text}"
        )
        # Cache should now be populated.
        with _raster_meta_cache_lock:
            assert cache_key in _raster_meta_cache

        # Step 2: anonymous caller must be rejected.
        anon_resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )
        assert anon_resp.status_code == 401, (
            f"PERF-002 FAIL: cached metadata bypassed auth; got {anon_resp.status_code}"
        )
