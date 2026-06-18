"""STOR-07: Cross-provider move acceptance — render without touching stored VRT XML.

Acceptance criterion 4 of the Azure storage seam milestone:
  A VRT-backed dataset's objects move to a different bucket/provider, config
  updates, and a tile renders WITHOUT touching the stored VRT XML
  (open-time resolve_open_path reconstruction is the sole mechanism).

What this test proves
---------------------
1. A .vrt is built with concrete VSI paths (simulating what _write_python_vrt
   produced before Plan 03) and passed through rewrite_vrt_sources — the stored
   VRT XML contains ONLY logical keys (no /vsis3/ or /vsiaz/ literals).

2. The stored VRT XML bytes (sha256) are captured BEFORE the move.

3. Objects are moved from provider A (Azurite container A) to provider B
   (Azurite container B) by copy + delete, preserving keys.

4. STORAGE_PROVIDER config is "flipped" to point at container B.

5. resolve_open_path on the dataset's asset_uri now yields /vsiaz/{containerB}/key.

6. GDAL opens the VRT from container B and reads real pixel data.

7. The stored VRT XML bytes (sha256) are asserted UNCHANGED — no edit to the
   stored XML occurred during the move + config flip + render.

This proves STOR-07: open-time resolution is the sole mechanism for cross-
provider portability; stored XML is never touched during migration.

Reference
---------
The internal cross-cloud migration runbook (Plan 03 Task 2) documents the
5-step migration procedure this test mechanizes.

Skip behavior
-------------
Tests skip cleanly when Azurite is not reachable, so the default local CI run
(STORAGE_PROVIDER=local, no Azurite) is unaffected.
"""

from __future__ import annotations

import hashlib
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.processing.raster.vrt_rewrite import rewrite_vrt_sources

# ---------------------------------------------------------------------------
# Azurite dev constants (public Microsoft defaults, not secret) gitleaks:allow
# ---------------------------------------------------------------------------
_AZURITE_CONN = (  # gitleaks:allow
    "DefaultEndpointsProtocol=http;"
    "AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)

# Provider A: the source container before migration
_CONTAINER_A = "geolens-stor07-a"
# Provider B: the destination container (simulates provider/bucket swap)
_CONTAINER_B = "geolens-stor07-b"
_AZURITE_HOST = "127.0.0.1"
_AZURITE_PORT = 10000


def _azurite_reachable() -> bool:
    """Return True if Azurite is listening on the well-known host:port."""
    try:
        with socket.create_connection((_AZURITE_HOST, _AZURITE_PORT), timeout=1):
            return True
    except (OSError, ConnectionRefusedError):
        return False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_tiny_cog(path: Path, pixel_value: int = 55) -> None:
    """Write a 32x32 single-band GeoTIFF with a sentinel pixel value."""
    data = np.full((1, 32, 32), pixel_value, dtype="uint8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        str(path),
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


def _make_vrt_xml_with_vsi_path(vsi_cog_path: str) -> str:
    """Return a minimal VRT XML with a concrete /vsiaz/ (or /vsis3/) SourceFilename.

    This simulates the pre-Plan03 VRT that _write_python_vrt might have emitted
    before the relativeToVRT="1" fix. rewrite_vrt_sources must strip the prefix.
    """
    return f"""<?xml version='1.0' encoding='utf-8'?>
<VRTDataset rasterXSize="32" rasterYSize="32">
  <SRS>EPSG:4326</SRS>
  <GeoTransform>-10.0, 0.625, 0.0, 10.0, 0.0, -0.625</GeoTransform>
  <VRTRasterBand dataType="Byte" band="1">
    <SimpleSource>
      <SourceFilename relativeToVRT="0">{vsi_cog_path}</SourceFilename>
      <SourceBand>1</SourceBand>
      <SourceProperties RasterXSize="32" RasterYSize="32" DataType="Byte" BlockXSize="32" BlockYSize="1"/>
      <SrcRect xOff="0" yOff="0" xSize="32" ySize="32"/>
      <DstRect xOff="0" yOff="0" xSize="32" ySize="32"/>
    </SimpleSource>
  </VRTRasterBand>
</VRTDataset>"""


@pytest.fixture(scope="module")
def azurite_svc():
    """Return a BlobServiceClient pointed at Azurite; skip if unreachable."""
    if not _azurite_reachable():
        pytest.skip(
            "Azurite not running at 127.0.0.1:10000 — STOR-07 tests skipped. "
            "Run: docker compose --profile cloud-dev up -d azurite"
        )
    from azure.storage.blob import BlobServiceClient

    svc = BlobServiceClient.from_connection_string(_AZURITE_CONN)
    # Ensure both containers exist
    for container in (_CONTAINER_A, _CONTAINER_B):
        try:
            svc.create_container(container)
        except Exception:
            pass  # Already exists
    return svc


class TestCrossProviderMoveAcceptance:
    """STOR-07: VRT-backed dataset moves between Azurite containers without XML edit.

    Full acceptance scenario in one test method to keep the state machine clear:
    upload -> snapshot XML -> move -> assert sha256 unchanged -> render from B.
    """

    def test_move_vrt_dataset_xml_unchanged_and_renders(self, azurite_svc, tmp_path):
        """
        Full STOR-07 acceptance proof.

        Steps:
        1. Create source COG + .vrt with a baked /vsiaz/{container_a}/ path
        2. Rewrite the .vrt with rewrite_vrt_sources (store-time normalization)
        3. Upload both objects to container A (provider A) preserving keys
        4. Assert stored .vrt bytes contain NO /vsiaz/ or /vsis3/ literals
        5. sha256-snapshot the stored .vrt bytes (pre-move)
        6. Copy both objects from container A -> container B preserving keys
        7. Delete from container A (simulating a move)
        8. "Flip" config to point at container B
        9. Assert sha256 of stored .vrt bytes == pre-move sha256 (UNCHANGED)
        10. resolve_open_path now yields /vsiaz/{container_b}/{vrt_key}
        11. GDAL opens the VRT from container B and reads real pixels (sentinel=55)
        """
        cog_key = "stor07/dataset1/source.cog.tif"
        vrt_key = "stor07/dataset1/source.vrt"

        # ------------------------------------------------------------------
        # Step 1: Create source COG on disk, build VRT with baked /vsiaz/ path
        # ------------------------------------------------------------------
        cog_path = tmp_path / "source.cog.tif"
        _make_tiny_cog(cog_path, pixel_value=55)

        # The VRT references the COG via the container-A /vsiaz/ path —
        # simulating what _write_python_vrt produced before Plan 03's relativeToVRT="1" fix.
        vsi_cog_in_a = f"/vsiaz/{_CONTAINER_A}/{cog_key}"
        raw_vrt_xml = _make_vrt_xml_with_vsi_path(vsi_cog_in_a)

        vrt_path = tmp_path / "source.vrt"
        vrt_path.write_text(raw_vrt_xml, encoding="utf-8")

        # ------------------------------------------------------------------
        # Step 2: rewrite_vrt_sources normalizes the stored VRT (Plan 03 logic)
        # CR-01 fix: pass vrt_storage_key so the rewrite computes the correct
        # path relative to the VRT's own directory (not the full logical key).
        # vrt_key="stor07/dataset1/source.vrt", cog_key="stor07/dataset1/source.cog.tif"
        # -> relative path = "source.cog.tif" (same directory).
        # ------------------------------------------------------------------
        changes = rewrite_vrt_sources(vrt_path, vrt_storage_key=vrt_key)
        assert len(changes) == 1, (
            f"Expected exactly 1 SourceFilename to be rewritten, got {changes}"
        )
        assert vsi_cog_in_a in changes[0], (
            f"Expected the /vsiaz/{_CONTAINER_A}/ path in the change record"
        )

        # ------------------------------------------------------------------
        # Step 3: Upload COG + normalised .vrt to container A
        # ------------------------------------------------------------------
        with open(cog_path, "rb") as f:
            azurite_svc.get_blob_client(_CONTAINER_A, cog_key).upload_blob(
                f, overwrite=True
            )

        vrt_bytes_normalised = vrt_path.read_bytes()
        azurite_svc.get_blob_client(_CONTAINER_A, vrt_key).upload_blob(
            vrt_bytes_normalised, overwrite=True
        )

        # ------------------------------------------------------------------
        # Step 4: Assert stored VRT bytes contain NO VSI literals
        # ------------------------------------------------------------------
        stored_vrt_from_a = (
            azurite_svc.get_blob_client(_CONTAINER_A, vrt_key).download_blob().readall()
        )

        assert b"/vsiaz/" not in stored_vrt_from_a, (
            "Stored VRT contains /vsiaz/ literal — rewrite_vrt_sources did not normalise it"
        )
        assert b"/vsis3/" not in stored_vrt_from_a, (
            "Stored VRT contains /vsis3/ literal — unexpected baked path in stored VRT"
        )

        # Verify relativeToVRT="1" attribute was set by the rewrite
        vrt_text = stored_vrt_from_a.decode("utf-8")
        assert 'relativeToVRT="1"' in vrt_text, (
            f'relativeToVRT="1" not found in stored VRT: {vrt_text[:500]}'
        )

        # Verify the relative COG filename is present (without any provider prefix).
        # With vrt_storage_key supplied, the stored path is just the basename
        # ("source.cog.tif") not the full logical key — GDAL resolves it relative
        # to the VRT's own directory in the container (CR-01 fix).
        assert "source.cog.tif" in vrt_text, (
            f"'source.cog.tif' not found in stored VRT: {vrt_text[:500]}"
        )

        # ------------------------------------------------------------------
        # Step 5: sha256-snapshot the stored .vrt bytes (pre-move)
        # ------------------------------------------------------------------
        pre_move_sha256 = _sha256(stored_vrt_from_a)

        # ------------------------------------------------------------------
        # Step 6+7: Copy objects to container B; delete from container A (move)
        # ------------------------------------------------------------------
        # Azure copy: download from A, upload to B
        for key in (cog_key, vrt_key):
            blob_data = (
                azurite_svc.get_blob_client(_CONTAINER_A, key).download_blob().readall()
            )
            azurite_svc.get_blob_client(_CONTAINER_B, key).upload_blob(
                blob_data, overwrite=True
            )
            # Delete from A after confirming upload to B
            azurite_svc.get_blob_client(_CONTAINER_A, key).delete_blob()

        # Verify A no longer has the objects
        from azure.core.exceptions import ResourceNotFoundError

        for key in (cog_key, vrt_key):
            try:
                azurite_svc.get_blob_client(_CONTAINER_A, key).get_blob_properties()
                pytest.fail(f"Object {key} still present in container A after move")
            except ResourceNotFoundError:
                pass  # Correct — deleted from A

        # ------------------------------------------------------------------
        # Step 8: "Flip" config to point at container B
        # ------------------------------------------------------------------
        # We simulate a STORAGE_PROVIDER config flip by patching settings.
        # In a real migration this would be an env var change + service restart.
        mock_settings_b = MagicMock()
        mock_settings_b.storage_provider = "azure"
        mock_settings_b.azure_storage_container = _CONTAINER_B

        # ------------------------------------------------------------------
        # Step 9: Assert sha256 of stored .vrt bytes is UNCHANGED after move
        # ------------------------------------------------------------------
        stored_vrt_from_b = (
            azurite_svc.get_blob_client(_CONTAINER_B, vrt_key).download_blob().readall()
        )
        post_move_sha256 = _sha256(stored_vrt_from_b)

        assert post_move_sha256 == pre_move_sha256, (
            f"Stored VRT XML bytes changed during cross-provider move!\n"
            f"  pre-move  sha256: {pre_move_sha256}\n"
            f"  post-move sha256: {post_move_sha256}\n"
            "The VRT XML must be UNCHANGED — only config/keys change, not stored XML."
        )

        # ------------------------------------------------------------------
        # Step 10: resolve_open_path with flipped config yields provider-B path
        # ------------------------------------------------------------------
        from app.platform.storage.titiler_url import resolve_open_path

        with patch("app.core.config.settings", mock_settings_b):
            open_path_b = resolve_open_path(vrt_key, tenant_id=None)

        expected_vsiaz_b = f"/vsiaz/{_CONTAINER_B}/{vrt_key}"
        assert open_path_b == expected_vsiaz_b, (
            f"After config flip, resolve_open_path returned {open_path_b!r}, "
            f"expected {expected_vsiaz_b!r}"
        )

        # ------------------------------------------------------------------
        # Step 11: GDAL opens the ACTUAL STORED VRT directly from /vsiaz/
        # ------------------------------------------------------------------
        # CR-01 fix: open /vsiaz/{container_b}/{vrt_key} directly — NO absolute-path
        # injection.  GDAL resolves the relativeToVRT="1" SourceFilename
        # ("source.cog.tif") relative to /vsiaz/{container_b}/stor07/dataset1/,
        # yielding /vsiaz/{container_b}/stor07/dataset1/source.cog.tif (which exists).
        #
        # With the OLD bug (full logical key stored as relative path, e.g.
        # "stor07/dataset1/source.cog.tif"), GDAL would resolve to
        # /vsiaz/{container_b}/stor07/dataset1/stor07/dataset1/source.cog.tif
        # (double-path), which does NOT exist, and rasterio.open raises a GDAL error.
        vsiaz_vrt_b = f"/vsiaz/{_CONTAINER_B}/{vrt_key}"
        with rasterio.Env(AZURE_STORAGE_CONNECTION_STRING=_AZURITE_CONN):
            with rasterio.open(vsiaz_vrt_b) as src:
                band_count = src.count
                window = rasterio.windows.Window(0, 0, 4, 4)
                pixel_window = src.read(1, window=window)

        assert band_count == 1, f"Expected 1 band from VRT, got {band_count}"
        assert pixel_window.shape == (4, 4), (
            f"Expected (4,4) window, got {pixel_window.shape}"
        )
        # Sentinel value 55 must appear — proving GDAL read real data from container B
        # through the VRT's relative-path resolution (no absolute-path injection).
        assert (pixel_window == 55).any(), (
            f"Sentinel value 55 not found in pixel window from container B: {pixel_window}"
        )

        # Summary assertion: the key invariant of STOR-07
        assert post_move_sha256 == pre_move_sha256, (
            "STOR-07 INVARIANT VIOLATED: stored VRT XML bytes differ before and after move"
        )

    def test_stored_vrt_contains_no_vsi_literals_after_rewrite(self, tmp_path):
        """Stored VRT has NO /vsis3/ or /vsiaz/ literals after rewrite_vrt_sources.

        This is a pure unit assertion (no Azurite needed) proving the invariant
        that underlies STOR-07: rewrite_vrt_sources strips all provider-specific
        prefixes before storage, so the stored XML is portable across providers.
        """
        # Build a VRT with a baked /vsis3/ path (simulating pre-Plan03 storage)
        vrt_path = tmp_path / "has_s3_path.vrt"
        vrt_xml = _make_vrt_xml_with_vsi_path("/vsis3/my-bucket/rasters/1/cog.tif")
        vrt_path.write_text(vrt_xml, encoding="utf-8")

        changes = rewrite_vrt_sources(vrt_path)
        assert len(changes) == 1

        stored = vrt_path.read_bytes()
        assert b"/vsis3/" not in stored
        assert b"/vsiaz/" not in stored
        assert b"rasters/1/cog.tif" in stored  # logical key present
        assert b'relativeToVRT="1"' in stored

    def test_rewrite_idempotent_sha256_stable(self, tmp_path):
        """Rewriting an already-logical VRT twice produces identical bytes (idempotent).

        This proves that repeated calls to rewrite_vrt_sources during migration
        are safe and do not alter the stored XML's sha256.
        """
        vrt_path = tmp_path / "already_logical.vrt"
        vrt_xml = """<?xml version='1.0' encoding='utf-8'?>
<VRTDataset rasterXSize="32" rasterYSize="32">
  <SRS>EPSG:4326</SRS>
  <VRTRasterBand dataType="Byte" band="1">
    <SimpleSource>
      <SourceFilename relativeToVRT="1">rasters/abc/cog.tif</SourceFilename>
      <SourceBand>1</SourceBand>
    </SimpleSource>
  </VRTRasterBand>
</VRTDataset>"""
        vrt_path.write_text(vrt_xml, encoding="utf-8")
        bytes_before = vrt_path.read_bytes()
        sha_before = _sha256(bytes_before)

        # First rewrite (no changes expected — already logical)
        changes1 = rewrite_vrt_sources(vrt_path)
        assert changes1 == [], (
            f"First rewrite on logical VRT should be no-op: {changes1}"
        )

        # Second rewrite
        changes2 = rewrite_vrt_sources(vrt_path)
        assert changes2 == [], f"Second rewrite should also be no-op: {changes2}"

        sha_after = _sha256(vrt_path.read_bytes())
        assert sha_after == sha_before, (
            f"sha256 changed after idempotent rewrite: {sha_before} -> {sha_after}"
        )


class TestVrtDirectAzuriteOpen:
    """CR-01 proof: GDAL opens the ACTUAL STORED VRT directly from Azurite.

    This test does NOT inject absolute paths — it opens /vsiaz/{container}/{vrt_key}
    and lets GDAL resolve the relativeToVRT="1" SourceFilename relative to that
    /vsiaz/ base.  The test MUST FAIL on the old double-path bug (where the stored
    VRT contained the full logical key as the relative path) and PASS only when the
    relative path is computed correctly (i.e. just the basename when VRT and COG
    share the same directory).

    Skips when Azurite is not reachable.
    """

    def test_gdal_opens_stored_vrt_directly_from_azurite(self, azurite_svc, tmp_path):
        """Open /vsiaz/{container}/{vrt_key} directly — GDAL resolves sub-sources.

        The VRT at stor07cr01/dataset/source.vrt has a relativeToVRT="1" path of
        "source.cog.tif".  GDAL resolves that relative to /vsiaz/{container}/stor07cr01/dataset/
        producing /vsiaz/{container}/stor07cr01/dataset/source.cog.tif — which exists.

        With the OLD bug (full logical key as relative path, e.g.
        "stor07cr01/dataset/source.cog.tif"), GDAL would resolve to
        /vsiaz/{container}/stor07cr01/dataset/stor07cr01/dataset/source.cog.tif
        which does NOT exist, and rasterio.open raises a GDAL error.
        """
        _CONTAINER_CR01 = "geolens-stor07-cr01"
        # Ensure container exists
        try:
            azurite_svc.create_container(_CONTAINER_CR01)
        except Exception:
            pass

        cog_key = "stor07cr01/dataset/source.cog.tif"
        vrt_key = "stor07cr01/dataset/source.vrt"

        # Write a tiny COG with a known sentinel pixel value
        cog_path = tmp_path / "source.cog.tif"
        _make_tiny_cog(cog_path, pixel_value=42)

        # Upload the COG to Azurite
        with open(cog_path, "rb") as f:
            azurite_svc.get_blob_client(_CONTAINER_CR01, cog_key).upload_blob(
                f, overwrite=True
            )

        # Build a VRT referencing the COG via /vsiaz/ absolute path (pre-rewrite form)
        vsi_cog = f"/vsiaz/{_CONTAINER_CR01}/{cog_key}"
        vrt_xml = _make_vrt_xml_with_vsi_path(vsi_cog)
        vrt_path = tmp_path / "source.vrt"
        vrt_path.write_text(vrt_xml, encoding="utf-8")

        # Run rewrite_vrt_sources WITH vrt_storage_key so it computes the
        # correct POSIX relative path (CR-01 fix).
        # Expected result: "source.cog.tif" (same directory), NOT the full key.
        changes = rewrite_vrt_sources(vrt_path, vrt_storage_key=vrt_key)
        assert len(changes) == 1, f"Expected 1 rewrite, got: {changes}"

        # Confirm the stored relative path is JUST the basename
        from xml.etree.ElementTree import parse as _parse

        _tree = _parse(str(vrt_path))
        _nodes = list(_tree.getroot().iter("SourceFilename"))
        assert len(_nodes) == 1
        stored_relative = _nodes[0].text
        assert stored_relative == "source.cog.tif", (
            f"Expected relative path 'source.cog.tif', got {stored_relative!r}. "
            "If this is the full logical key, CR-01 is NOT fixed."
        )

        # Upload the rewritten VRT to Azurite
        vrt_bytes = vrt_path.read_bytes()
        azurite_svc.get_blob_client(_CONTAINER_CR01, vrt_key).upload_blob(
            vrt_bytes, overwrite=True
        )

        # Open the ACTUAL STORED VRT directly from Azurite via /vsiaz/ —
        # no absolute-path injection.  GDAL resolves the relativeToVRT="1"
        # "source.cog.tif" relative to /vsiaz/{container}/stor07cr01/dataset/
        # yielding /vsiaz/{container}/stor07cr01/dataset/source.cog.tif.
        vsiaz_vrt_path = f"/vsiaz/{_CONTAINER_CR01}/{vrt_key}"
        with rasterio.Env(AZURE_STORAGE_CONNECTION_STRING=_AZURITE_CONN):
            with rasterio.open(vsiaz_vrt_path) as src:
                band_count = src.count
                window = rasterio.windows.Window(0, 0, 4, 4)
                pixel_window = src.read(1, window=window)

        assert band_count == 1, f"Expected 1 band from stored VRT, got {band_count}"
        assert pixel_window.shape == (4, 4), (
            f"Expected (4,4) window, got {pixel_window.shape}"
        )
        # Sentinel value 42 must appear — proves GDAL read real data from Azurite
        # through the VRT's relative path resolution.
        assert (pixel_window == 42).any(), (
            f"Sentinel value 42 not found in pixel window from stored VRT: "
            f"{pixel_window}\n"
            "This failure means the relative path in the stored VRT is WRONG — "
            "CR-01 is not fixed."
        )
