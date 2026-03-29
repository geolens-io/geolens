"""Integration test: VRT tile serving via Titiler proxy.

Creates a small test COG on the shared staging volume, builds a VRT pointing at
it using gdalbuildvrt, registers a vrt_dataset Record/Dataset/RasterAsset, then
exercises the raster-auth-check and raster-proxy endpoints.

Requirements:
  - Docker database must be running (docker compose up db)
  - Titiler service must be running (docker compose up titiler)
  - Alembic migrations must be applied (alembic upgrade head)
  - GDAL CLI tools (gdal_create, gdalbuildvrt) must be available in the api container

Note: Tests in this file skip cleanly if Titiler is unreachable.
"""

import os
import subprocess
import uuid

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.config import settings
from app.datasets.models import Dataset, Record
from app.raster.models import RasterAsset


# ---------------------------------------------------------------------------
# Titiler availability check
# ---------------------------------------------------------------------------

_TITILER_AVAILABLE: bool | None = None


def _check_titiler() -> bool:
    """Return True if Titiler responds to /healthz."""
    global _TITILER_AVAILABLE
    if _TITILER_AVAILABLE is not None:
        return _TITILER_AVAILABLE
    try:
        from urllib.request import urlopen

        resp = urlopen("http://titiler:8000/healthz", timeout=3)
        _TITILER_AVAILABLE = resp.getcode() == 200
    except Exception:
        _TITILER_AVAILABLE = False
    return _TITILER_AVAILABLE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Real staging directory shared between api and titiler containers.
# The client fixture overrides settings.upload_staging_dir with tmp_path, but
# Titiler can only read from the shared Docker volume at /app/staging.
# We write test files directly to the real staging dir and override
# settings.upload_staging_dir back to it just for these tests.
_REAL_STAGING_DIR = "/app/staging"


async def _get_admin_id(session) -> uuid.UUID:
    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    return result.scalar_one().id


def _create_test_cog(cog_path: str) -> None:
    """Create a minimal 64x64 3-band GeoTIFF (COG-compatible) using gdal_create."""
    os.makedirs(os.path.dirname(cog_path), exist_ok=True)
    subprocess.run(
        [
            "gdal_create",
            "-ot",
            "Byte",
            "-outsize",
            "64",
            "64",
            "-bands",
            "3",
            "-burn",
            "128",
            "-of",
            "GTiff",
            "-co",
            "TILED=YES",
            "-a_srs",
            "EPSG:4326",
            "-a_ullr",
            "-10",
            "10",
            "10",
            "-10",
            cog_path,
        ],
        check=True,
        capture_output=True,
    )


def _build_vrt(vrt_path: str, cog_path: str) -> None:
    """Build a VRT from a COG using gdalbuildvrt."""
    os.makedirs(os.path.dirname(vrt_path), exist_ok=True)
    subprocess.run(
        ["gdalbuildvrt", vrt_path, cog_path],
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVrtTitilerProxy:
    """VRT tile serving via the raster proxy endpoint."""

    async def test_vrt_served_via_tile_proxy(self, client, test_db_session):
        """A VRT file pointing at a COG on the staging volume is served via the tile proxy.

        This test exercises the full end-to-end VRT serving path:
        1. Create a real COG file on the shared staging volume
        2. Build a VRT pointing at that COG using gdalbuildvrt
        3. Register a vrt_dataset in the database with asset_uri -> VRT path
        4. Call raster-auth-check to get the open-path
        5. Call the tile proxy; assert HTTP 200 with valid PNG bytes (or 204 no tile)
        """
        if not _check_titiler():
            pytest.skip("Titiler not reachable at http://titiler:8000")

        admin_id = await _get_admin_id(test_db_session)

        # Create the DB record
        record = Record(
            title=f"VRT Titiler Test {uuid.uuid4().hex[:6]}",
            summary="Integration test for VRT tile serving",
            theme_category=["test"],
            visibility="public",
            record_status="published",
            record_type="vrt_dataset",
            created_by=admin_id,
        )
        test_db_session.add(record)
        await test_db_session.flush()

        dataset = Dataset(
            record_id=record.id,
            table_name=f"vrt_titiler_{uuid.uuid4().hex[:8]}",
            source_format="geotiff",
            source_filename="source.vrt",
        )
        test_db_session.add(dataset)
        await test_db_session.flush()

        # Paths relative to staging — same structure as real ingest
        hash_prefix = uuid.uuid4().hex[:8]
        rel_cog = f"rasters/{dataset.id}/{hash_prefix}/source.cog.tif"
        rel_vrt = f"rasters/{dataset.id}/{hash_prefix}/source.vrt"

        abs_cog = f"{_REAL_STAGING_DIR}/{rel_cog}"
        abs_vrt = f"{_REAL_STAGING_DIR}/{rel_vrt}"

        # Create the COG and VRT on the shared staging volume
        _create_test_cog(abs_cog)
        _build_vrt(abs_vrt, abs_cog)

        # Register the RasterAsset pointing to the VRT
        raster_asset = RasterAsset(
            dataset_id=dataset.id,
            asset_uri=rel_vrt,
            storage_backend="local",
            band_count=3,
            dtype="uint8",
            vrt_type="mosaic",
        )
        test_db_session.add(raster_asset)
        await test_db_session.flush()
        await test_db_session.commit()
        await test_db_session.refresh(dataset)
        await test_db_session.refresh(raster_asset)

        # Override settings so auth-check builds the correct path for Titiler
        original_staging = settings.upload_staging_dir
        settings.upload_staging_dir = _REAL_STAGING_DIR
        try:
            # Step 1: Verify raster-auth-check returns 200 with open-path
            auth_resp = await client.get(
                "/tiles/raster-auth-check/",
                params={"dataset_id": str(dataset.id)},
            )
            assert auth_resp.status_code == 200, (
                f"raster-auth-check failed: {auth_resp.status_code} {auth_resp.text}"
            )
            open_path = auth_resp.headers.get("x-geolens-asset-openpath")
            assert open_path is not None, "Missing X-GeoLens-Asset-OpenPath header"
            assert open_path.endswith(rel_vrt), (
                f"open_path {open_path!r} does not end with {rel_vrt!r}"
            )

            # Step 2: Request a tile — zoom 0 is world tile, always valid
            tile_resp = await client.get(
                f"/tiles/raster-proxy/{dataset.id}/0/0/0.png",
            )
            # Titiler returns 200 (tile) or 204 (no data at this zoom level)
            assert tile_resp.status_code in (200, 204), (
                f"Unexpected tile proxy status: {tile_resp.status_code} {tile_resp.text}"
            )

            if tile_resp.status_code == 200:
                # Must be a valid PNG
                png_magic = b"\x89PNG\r\n\x1a\n"
                assert tile_resp.content[:8] == png_magic, (
                    f"Response is not a valid PNG: {tile_resp.content[:16]!r}"
                )
            else:
                # 204 is acceptable — tile has no data at this zoom, but Titiler responded
                # Try a slightly higher zoom to get actual tile data
                tile_resp2 = await client.get(
                    f"/tiles/raster-proxy/{dataset.id}/1/0/0.png",
                )
                assert tile_resp2.status_code in (200, 204), (
                    f"Unexpected tile proxy status at z=1: {tile_resp2.status_code}"
                )

        finally:
            # Restore staging dir override
            settings.upload_staging_dir = original_staging

            # Clean up test files from shared staging volume
            try:
                import shutil

                parent_dir = f"{_REAL_STAGING_DIR}/rasters/{dataset.id}"
                if os.path.exists(parent_dir):
                    shutil.rmtree(parent_dir)
            except Exception:
                pass

    async def test_auth_check_recognizes_vrt_dataset(self, client, test_db_session):
        """raster-auth-check returns 200 for a vrt_dataset record type."""
        if not _check_titiler():
            pytest.skip("Titiler not reachable at http://titiler:8000")

        admin_id = await _get_admin_id(test_db_session)

        record = Record(
            title=f"VRT Auth Check Test {uuid.uuid4().hex[:6]}",
            theme_category=["test"],
            visibility="public",
            record_status="published",
            record_type="vrt_dataset",
            created_by=admin_id,
        )
        test_db_session.add(record)
        await test_db_session.flush()

        dataset = Dataset(
            record_id=record.id,
            table_name=f"vrt_auth_{uuid.uuid4().hex[:8]}",
            source_format="geotiff",
            source_filename="source.vrt",
        )
        test_db_session.add(dataset)
        await test_db_session.flush()

        raster_asset = RasterAsset(
            dataset_id=dataset.id,
            asset_uri=f"rasters/{dataset.id}/abc123/source.vrt",
            storage_backend="local",
            vrt_type="mosaic",
        )
        test_db_session.add(raster_asset)
        await test_db_session.flush()
        await test_db_session.commit()
        await test_db_session.refresh(dataset)
        await test_db_session.refresh(raster_asset)

        # The auth-check should return 200 regardless of whether the file exists
        # (it only checks DB records + auth, not file existence)
        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )
        # The raster-auth-check accepts both 'raster_dataset' and 'vrt_dataset'
        # only if the router checks for either — let's see the actual behavior.
        # If it returns 404, the router rejects vrt_dataset record type.
        assert resp.status_code == 200, (
            f"raster-auth-check should accept vrt_dataset record_type, "
            f"got {resp.status_code}: {resp.text}"
        )
        open_path = resp.headers.get("x-geolens-asset-openpath")
        assert open_path is not None
        assert raster_asset.asset_uri in open_path
