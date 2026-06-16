"""STOR-06: Render a raster tile from an Azurite blob via /vsiaz/ (Phase 1210 Plan 04).

Proves criterion 3 of the Azure storage seam milestone: a raster tile RENDERS
from an Azurite blob using GDAL's /vsiaz/ driver with the Azure credentials
delivered via environment variables.

Two-tier render proof
---------------------
TIER-1 (always-on, CI-portable, runs whenever Azurite is reachable):
  - Upload a small single-band GeoTIFF to Azurite via the azure-storage-blob SDK
  - Assert resolve_open_path under provider=azure yields /vsiaz/{container}/{key}
  - Assert rasterio.open of that /vsiaz/ path with the Azure env set returns the
    expected band count AND reads a non-empty window of real pixel data
  This proves GDAL renders real pixels from an Azurite blob with NO Titiler
  container required. It is the authoritative CI proof for STOR-06.

TIER-2 (live_stack marker — run when the full cloud-dev Docker stack is up):
  - Requires Titiler reachable at http://titiler:8000 (internal Docker network only)
  - Requires Azurite reachable at http://azurite:10000 (internal Docker network)
  - Requests a tile from the Titiler /cog/tiles endpoint with url=/vsiaz/... and
    asserts HTTP 200 + non-empty PNG body (PNG signature in first 8 bytes)
  - This is the full end-to-end confirmation; when the stack is absent it is
    skipped, not failed.

CI default: pytest backend/tests/test_stor06_render_from_azurite.py
  -> tier-1 runs (Azurite up) / or skips cleanly (Azurite absent)
  -> tier-2 skips (live_stack marker absent)

Live-stack run: pytest -m live_stack tests/test_stor06_render_from_azurite.py
  -> both tiers run (requires Docker cloud-dev stack)
"""

from __future__ import annotations

import os
import socket
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

# ---------------------------------------------------------------------------
# Azurite well-known dev connection string (public Microsoft constant, not secret).
# gitleaks:allow
# ---------------------------------------------------------------------------
_AZURITE_CONN = (  # gitleaks:allow
    "DefaultEndpointsProtocol=http;"
    "AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)
_AZURITE_CONTAINER = "geolens-stor06"
_AZURITE_HOST = "127.0.0.1"
_AZURITE_PORT = 10000

# Key for the fixture blob uploaded to Azurite
_FIXTURE_BLOB_KEY = "stor06/render_test/fixture.tif"


def _azurite_reachable() -> bool:
    """Return True if Azurite is listening on the well-known host:port."""
    try:
        with socket.create_connection((_AZURITE_HOST, _AZURITE_PORT), timeout=1):
            return True
    except (OSError, ConnectionRefusedError):
        return False


def _titiler_reachable_internal() -> bool:
    """Return True if Titiler is reachable at its Docker-internal address.

    This only succeeds when the test runs *inside* the Docker network (e.g.
    from inside the api container or a pytest container with the right network).
    From the host, titiler:8000 is not reachable — the live_stack tier skips.
    """
    try:
        with socket.create_connection(("titiler", 8000), timeout=1):
            return True
    except (OSError, ConnectionRefusedError):
        return False


# ---------------------------------------------------------------------------
# Session-scoped fixture: upload the test COG to Azurite once per session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def azurite_fixture_key():
    """Upload a tiny single-band GeoTIFF to Azurite; yield the blob key.

    Skips the session if Azurite is not reachable. The container and blob are
    created once per session and left for cleanup by the emulator restart.
    """
    if not _azurite_reachable():
        pytest.skip(
            "Azurite not running at 127.0.0.1:10000 — STOR-06 tests skipped. "
            "Run: docker compose --profile cloud-dev up -d azurite"
        )

    from azure.storage.blob import BlobServiceClient

    svc = BlobServiceClient.from_connection_string(_AZURITE_CONN)

    # Create the test container (idempotent)
    try:
        svc.create_container(_AZURITE_CONTAINER)
    except Exception:
        pass  # Container already exists

    # Create a tiny single-band GeoTIFF with known pixel values
    # 32x32 pixels, EPSG:4326, all pixels = 77 (a sentinel value checked below)
    data = np.full((1, 32, 32), 77, dtype="uint8")
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as f:
        tmp_path = f.name

    try:
        with rasterio.open(
            tmp_path,
            "w",
            driver="GTiff",
            width=32,
            height=32,
            count=1,
            dtype="uint8",
            crs="EPSG:4326",
            transform=from_origin(-10.0, 10.0, 20.0 / 32, 20.0 / 32),
        ) as dst:
            dst.write(data)

        # Upload to Azurite
        with open(tmp_path, "rb") as fobj:
            svc.get_blob_client(
                container=_AZURITE_CONTAINER, blob=_FIXTURE_BLOB_KEY
            ).upload_blob(fobj, overwrite=True)
    finally:
        os.unlink(tmp_path)

    return _FIXTURE_BLOB_KEY


# ---------------------------------------------------------------------------
# TIER-1: resolve_open_path dispatch + GDAL /vsiaz/ open (always-on)
# ---------------------------------------------------------------------------


class TestTier1ResolveAndGdalOpen:
    """TIER-1 STOR-06: resolve_open_path dispatch + GDAL renders from Azurite blob.

    These tests run whenever Azurite is reachable (session fixture probe).
    They are the authoritative CI proof for STOR-06: GDAL reads real pixels
    from an Azurite blob via /vsiaz/ without requiring Titiler.
    """

    def test_resolve_open_path_yields_vsiaz(self, azurite_fixture_key):
        """resolve_open_path under provider=azure yields /vsiaz/{container}/{key}."""
        from app.platform.storage.titiler_url import resolve_open_path

        mock = MagicMock()
        mock.storage_provider = "azure"
        mock.azure_storage_container = _AZURITE_CONTAINER

        with patch("app.core.config.settings", mock):
            result = resolve_open_path(azurite_fixture_key, tenant_id=None)

        expected = f"/vsiaz/{_AZURITE_CONTAINER}/{azurite_fixture_key}"
        assert result == expected, (
            f"resolve_open_path returned {result!r}, expected {expected!r}"
        )

    def test_gdal_opens_vsiaz_path_and_reads_pixels(self, azurite_fixture_key):
        """GDAL rasterio.open of /vsiaz/{container}/{key} returns real pixel data.

        This is the STOR-06 TIER-1 proof: GDAL opens a raster from an Azurite
        blob via /vsiaz/ with the Azure connection string in the environment.
        The fixture was uploaded with pixel sentinel value 77 — we assert that
        value is present in the read window.
        """
        from app.platform.storage.titiler_url import resolve_open_path

        mock = MagicMock()
        mock.storage_provider = "azure"
        mock.azure_storage_container = _AZURITE_CONTAINER

        with patch("app.core.config.settings", mock):
            vsiaz_path = resolve_open_path(azurite_fixture_key, tenant_id=None)

        assert vsiaz_path.startswith("/vsiaz/"), (
            f"Path does not start with /vsiaz/: {vsiaz_path!r}"
        )

        # Open via GDAL /vsiaz/ with the Azure connection string in the environment.
        # rasterio.Env propagates GDAL config options including AZURE_STORAGE_*.
        with rasterio.Env(AZURE_STORAGE_CONNECTION_STRING=_AZURITE_CONN):
            with rasterio.open(vsiaz_path) as src:
                band_count = src.count
                window = rasterio.windows.Window(0, 0, 4, 4)
                pixel_values = src.read(1, window=window)

        assert band_count == 1, f"Expected 1 band, got {band_count}"
        assert pixel_values.shape == (4, 4), (
            f"Expected (4, 4) window, got {pixel_values.shape}"
        )
        # The sentinel value 77 must appear in the read window
        assert (pixel_values == 77).any(), (
            f"Sentinel value 77 not found in pixel window: {pixel_values}"
        )

    def test_gdal_open_returns_nonempty_read(self, azurite_fixture_key):
        """A full-band read of the Azurite-hosted raster returns a non-empty array."""
        from app.platform.storage.titiler_url import resolve_open_path

        mock = MagicMock()
        mock.storage_provider = "azure"
        mock.azure_storage_container = _AZURITE_CONTAINER

        with patch("app.core.config.settings", mock):
            vsiaz_path = resolve_open_path(azurite_fixture_key, tenant_id=None)

        with rasterio.Env(AZURE_STORAGE_CONNECTION_STRING=_AZURITE_CONN):
            with rasterio.open(vsiaz_path) as src:
                data = src.read(1)

        assert data.size > 0, "Read returned an empty array"
        assert data.dtype == np.uint8
        # The uploaded fixture is all-77; verify the data range
        assert data.min() == 77 and data.max() == 77, (
            f"Expected all pixels = 77, got min={data.min()} max={data.max()}"
        )

    def test_titiler_compose_config_carries_azure_env(self):
        """Titiler service in docker-compose.yml has AZURE_STORAGE env vars.

        This is a config-level assertion (no Azurite needed). Verified by grepping
        the compose file for the AZURE_STORAGE_CONNECTION_STRING env key.
        """
        import subprocess

        project_root = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        compose_path = os.path.join(project_root, "docker-compose.yml")
        result = subprocess.run(
            ["grep", "-n", "AZURE_STORAGE_CONNECTION_STRING", compose_path],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            "AZURE_STORAGE_CONNECTION_STRING not found in docker-compose.yml — "
            "Titiler is not configured to receive the Azure GDAL env."
        )
        assert "AZURE_STORAGE_CONNECTION_STRING" in result.stdout, (
            f"Unexpected grep output: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# TIER-2: Full Titiler /cog/tiles end-to-end (live_stack only)
# ---------------------------------------------------------------------------


@pytest.mark.live_stack
class TestTier2TitilerLiveRender:
    """TIER-2 STOR-06: Full Titiler COG tile render via /vsiaz/.

    Requires the cloud-dev Docker stack (titiler + azurite both running with
    the well-known Azurite Azure env set in Titiler's environment).

    These tests are SKIPPED in default CI runs (no live_stack marker). Run with:
        pytest -m live_stack tests/test_stor06_render_from_azurite.py

    The tier-1 GDAL open tests above are the CI-portable minimum proof for STOR-06.
    """

    def test_titiler_cog_tiles_200_png_from_azurite(self, azurite_fixture_key):
        """GET /cog/tiles/... from Titiler returns HTTP 200 + non-empty PNG.

        End-to-end path:
          Titiler reads /vsiaz/{container}/{key} via GDAL /vsiaz/ driver
          -> authenticates to Azurite using AZURE_STORAGE_CONNECTION_STRING
          -> renders a tile
          -> returns 200 + PNG bytes with real content (PNG signature + Content-Length > 0)
        """
        if not _titiler_reachable_internal():
            pytest.skip(
                "Titiler not reachable at titiler:8000 (tests not running inside "
                "Docker network). Start the cloud-dev stack and run from inside "
                "the api container."
            )

        import urllib.request

        vsiaz_path = f"/vsiaz/{_AZURITE_CONTAINER}/{azurite_fixture_key}"
        from urllib.parse import urlencode

        params = urlencode({"url": vsiaz_path})
        tile_url = f"http://titiler:8000/cog/tiles/WebMercatorQuad/0/0/0.png?{params}"

        try:
            with urllib.request.urlopen(tile_url, timeout=15) as resp:
                status = resp.status
                body = resp.read()
        except Exception as exc:
            pytest.fail(
                f"Titiler request failed: {exc}\n"
                f"URL: {tile_url}\n"
                "Ensure Titiler has AZURE_STORAGE_CONNECTION_STRING set to the "
                "Azurite dev connection string."
            )

        assert status == 200, (
            f"Expected HTTP 200 from Titiler, got {status}. URL: {tile_url}"
        )
        assert len(body) > 0, "Titiler returned HTTP 200 but an empty body"

        # Verify PNG signature: 8-byte magic number
        png_signature = b"\x89PNG\r\n\x1a\n"
        assert body[:8] == png_signature, (
            f"Response body is not a PNG: first 16 bytes = {body[:16]!r}"
        )
        assert len(body) > 100, (
            f"PNG body suspiciously small ({len(body)} bytes) — may be placeholder"
        )
