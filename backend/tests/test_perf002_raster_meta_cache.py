"""Tests for PERF-002: raster tile metadata caching.

Verifies:
  - _resolve_raster_meta returns the same _RasterMeta object on a second call
    (cache hit), avoiding a DB round trip per tile request.
  - _raster_meta_cache is populated after the first call.
  - Authorization is still evaluated per request: a caller who is denied access
    does not inherit a cached allow decision from a previous authorized caller.
  - fix(#1329): the cache key carries the request's `v` (tile_cache_version), so
    a pointer swap that bumps the version is missed by every api process on the
    first request that carries the new value — while an absent or malformed `v`
    keeps the pre-#1329 unversioned key and its 60s-bounded staleness.
"""

import uuid

from sqlalchemy import text

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


# ---------------------------------------------------------------------------
# fix(#1329): version-keyed cache entries
# ---------------------------------------------------------------------------


async def _swap_raster_pointer(session, dataset_id: uuid.UUID) -> str:
    """Swap the asset pointer and bump tile_cache_version in one transaction.

    Mirrors what raster reupload (#1290), VRT regeneration, and the STAC
    moved-asset refresh (#1326) each already do: the new href and the bumped
    counter commit together, so a request carrying the new `v` can never read
    the old pointer back out of the database.
    """
    new_uri = f"rasters/{dataset_id}/swapped-{uuid.uuid4().hex[:8]}.cog.tif"
    await session.execute(
        text(
            "UPDATE catalog.raster_assets SET asset_uri = :uri WHERE dataset_id = :id"
        ),
        {"uri": new_uri, "id": dataset_id},
    )
    await session.execute(
        text(
            "UPDATE catalog.datasets "
            "SET tile_cache_version = tile_cache_version + 1 WHERE id = :id"
        ),
        {"id": dataset_id},
    )
    await session.commit()
    return new_uri


def _forget(*cache_keys: str) -> None:
    """Drop cache entries left over from an earlier test."""
    with _raster_meta_cache_lock:
        for key in cache_keys:
            _raster_meta_cache.pop(key, None)


class TestRasterMetaCacheVersionKey:
    """fix(#1329): the request's `v` partitions the per-process meta cache."""

    async def test_cache_key_includes_requested_version(self, test_db_session):
        """A request carrying `v` is cached under a version-scoped key."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_public_raster(test_db_session, created_by=admin_id)

        bare_key = str(dataset.id)
        versioned_key = f"{dataset.id}:v1"
        _forget(bare_key, versioned_key)

        meta = await _resolve_raster_meta(test_db_session, dataset.id, "1")

        assert isinstance(meta, _RasterMeta)
        with _raster_meta_cache_lock:
            assert versioned_key in _raster_meta_cache
            # The unversioned key is NOT written, so a request carrying a
            # different `v` can never be served this entry.
            assert bare_key not in _raster_meta_cache

    async def test_bumped_version_misses_the_pre_swap_entry(self, test_db_session):
        """The bump alone invalidates: no TTL expiry, no coordination channel."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_public_raster(test_db_session, created_by=admin_id)
        dataset_id = dataset.id

        _forget(str(dataset_id), f"{dataset_id}:v1", f"{dataset_id}:v2")

        before = await _resolve_raster_meta(test_db_session, dataset_id, "1")
        assert before.tile_cache_version == 1
        old_uri = before.asset_uri

        new_uri = await _swap_raster_pointer(test_db_session, dataset_id)
        assert new_uri != old_uri

        # Requests still carrying the OLD `v` keep their entry: stale but
        # well-formed, bounded by the TTL and self-healing. That is the window
        # #1329 accepts, and it is what the shared nginx cache does with the
        # same `$arg_v` segment.
        stale = await _resolve_raster_meta(test_db_session, dataset_id, "1")
        assert stale is before
        assert stale.asset_uri == old_uri

        # The new `v` misses in this process and re-reads the swapped pointer.
        fresh = await _resolve_raster_meta(test_db_session, dataset_id, "2")
        assert fresh.asset_uri == new_uri
        assert fresh.tile_cache_version == 2

    async def test_absent_version_serves_from_the_unversioned_key(
        self, test_db_session
    ):
        """No `v` at all (copied connect URLs) keeps the pre-#1329 behavior."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_public_raster(test_db_session, created_by=admin_id)

        bare_key = str(dataset.id)
        _forget(bare_key)

        meta1 = await _resolve_raster_meta(test_db_session, dataset.id)
        meta2 = await _resolve_raster_meta(test_db_session, dataset.id)

        assert meta1 is meta2
        with _raster_meta_cache_lock:
            assert bare_key in _raster_meta_cache

    async def test_malformed_version_degrades_to_the_unversioned_key(
        self, test_db_session
    ):
        """A junk `v` degrades to the old key, never to an error."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_public_raster(test_db_session, created_by=admin_id)

        bare_key = str(dataset.id)
        _forget(bare_key)

        # Empty, non-numeric, signed, fractional, non-ASCII digits, and an
        # absurdly long run: none of them shapes a tile_cache_version.
        for raw in ("", "abc", "-1", "2.0", "٧", "9" * 11):
            meta = await _resolve_raster_meta(test_db_session, dataset.id, raw)
            assert isinstance(meta, _RasterMeta)
            with _raster_meta_cache_lock:
                assert bare_key in _raster_meta_cache
                assert f"{dataset.id}:v{raw}" not in _raster_meta_cache

    async def test_auth_check_reads_the_swapped_pointer_for_the_new_version(
        self, client, admin_auth_header, test_db_session
    ):
        """End to end: the `v` on the tile URL reaches the cache key.

        Primes the entry through the real request path, swaps the pointer, then
        checks that a request carrying the bumped `v` resolves the NEW open path
        while one carrying the old `v` still resolves the old one.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_public_raster(test_db_session, created_by=admin_id)
        dataset_id = dataset.id
        _forget(str(dataset_id), f"{dataset_id}:v1", f"{dataset_id}:v2")

        primed = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset_id), "v": "1"},
            headers=admin_auth_header,
        )
        assert primed.status_code == 200, primed.text
        old_path = primed.headers["X-GeoLens-Asset-OpenPath"]

        new_uri = await _swap_raster_pointer(test_db_session, dataset_id)

        stale = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset_id), "v": "1"},
            headers=admin_auth_header,
        )
        assert stale.status_code == 200, stale.text
        assert stale.headers["X-GeoLens-Asset-OpenPath"] == old_path

        fresh = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset_id), "v": "2"},
            headers=admin_auth_header,
        )
        assert fresh.status_code == 200, fresh.text
        assert new_uri in fresh.headers["X-GeoLens-Asset-OpenPath"]
        # The #1372 shared-cache guard still passes on the new key: `v` matches
        # the version of the snapshot the bytes are built from.
        assert fresh.headers["X-GeoLens-Cache-Status"] == "public"

    async def test_future_version_request_cannot_pre_warm_the_next_key(
        self, client, test_db_session
    ):
        """fix(#1329 codex P1): a predictable future `v` cannot poison a swap.

        The counter is public and increments by one, so an anonymous caller on
        a public raster can ask for the version the next swap will produce. If
        the entry were filed under the value the request asked for, that call
        would park the CURRENT snapshot on the key the swap is about to make
        legitimate, and the swap would land on an occupied key. Filing it under
        the snapshot's own version is what makes that impossible.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_public_raster(test_db_session, created_by=admin_id)
        dataset_id = dataset.id
        _forget(str(dataset_id), f"{dataset_id}:v1", f"{dataset_id}:v2")

        # The row is at version 1; ask anonymously for the NEXT one.
        primed = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset_id), "v": "2"},
        )
        assert primed.status_code == 200, primed.text
        pre_swap_path = primed.headers["X-GeoLens-Asset-OpenPath"]
        # The mismatched request is still served, and never as shared-cacheable
        # (#1372) — which defends nginx only, hence the key rule below.
        assert primed.headers["X-GeoLens-Cache-Status"] == "private"

        # It was filed under the row's own version, so the key the swap is
        # about to make legitimate is still empty.
        with _raster_meta_cache_lock:
            assert f"{dataset_id}:v1" in _raster_meta_cache
            assert f"{dataset_id}:v2" not in _raster_meta_cache

        new_uri = await _swap_raster_pointer(test_db_session, dataset_id)

        # The first genuine v=2 request resolves fresh rather than inheriting
        # the pre-swap snapshot.
        after = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset_id), "v": "2"},
        )
        assert after.status_code == 200, after.text
        after_path = after.headers["X-GeoLens-Asset-OpenPath"]
        assert new_uri in after_path
        assert after_path != pre_swap_path
        assert after.headers["X-GeoLens-Cache-Status"] == "public"
