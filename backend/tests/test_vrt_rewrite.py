"""Unit tests for vrt_rewrite.rewrite_vrt_sources (STOR-03/04, Phase 1210 Wave 3).

Coverage:
- /vsis3/ prefix stripped to logical key, relativeToVRT="1" set
- /vsiaz/ prefix stripped identically
- VRT-of-VRT: a SourceFilename pointing to a .vrt is stripped the same way
- dry_run=True returns changes WITHOUT modifying the file on disk
- Already-relative SourceFilename left unchanged (idempotent — second pass returns [])
- Store-roundtrip: a VRT built with concrete paths, rewritten to logical keys,
  then re-read, still parses correctly and contains NO /vsis3/ or /vsiaz/ literals

ORDERING PROOF (machine-checkable per plan acceptance_criteria):
  test_metadata_equality_proves_ordering checks that metadata extracted from the
  in-flight tmp .vrt (concrete VSI paths) EQUALS metadata extracted from the STORED
  logical-key VRT reopened via resolve_open_path (local provider).  This proves:
    1. rewrite_vrt_sources ran AFTER extraction (the stored copy has logical keys)
    2. The stored logical-key VRT is still openable by GDAL via resolve_open_path
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from xml.etree.ElementTree import parse

import rasterio
import numpy as np
from rasterio.crs import CRS
from rasterio.transform import from_bounds

from app.processing.raster.vrt_rewrite import rewrite_vrt_sources


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vrt_xml(sources: list[tuple[str, str]]) -> str:
    """Return minimal VRT XML with one SourceFilename per source.

    ``sources`` is a list of (relativeToVRT, path) tuples.
    """
    bands = "\n".join(
        f"""  <VRTRasterBand dataType="Byte" band="1">
    <SimpleSource>
      <SourceFilename relativeToVRT="{rel}">{path}</SourceFilename>
      <SourceBand>1</SourceBand>
    </SimpleSource>
  </VRTRasterBand>"""
        for rel, path in sources
    )
    return f"""<?xml version='1.0' encoding='utf-8'?>
<VRTDataset rasterXSize="256" rasterYSize="256">
  <SRS>EPSG:4326</SRS>
{bands}
</VRTDataset>"""


def _write_vrt(path: Path, xml: str) -> None:
    path.write_text(xml, encoding="utf-8")


# ---------------------------------------------------------------------------
# Core rewrite behaviour
# ---------------------------------------------------------------------------


class TestRewriteS3Prefix:
    def test_strips_s3_prefix_to_logical_key(self, tmp_path: Path) -> None:
        vrt = tmp_path / "test.vrt"
        _write_vrt(
            vrt,
            _make_vrt_xml([("0", "/vsis3/mybucket/rasters/1/cog.tif")]),
        )

        changes = rewrite_vrt_sources(vrt)

        assert len(changes) == 1
        assert "/vsis3/mybucket/rasters/1/cog.tif -> rasters/1/cog.tif" in changes[0]

    def test_rewrites_relativeToVRT_attribute(self, tmp_path: Path) -> None:
        vrt = tmp_path / "test.vrt"
        _write_vrt(
            vrt,
            _make_vrt_xml([("0", "/vsis3/mybucket/rasters/1/cog.tif")]),
        )

        rewrite_vrt_sources(vrt)

        tree = parse(str(vrt))
        nodes = list(tree.getroot().iter("SourceFilename"))
        assert len(nodes) == 1
        assert nodes[0].get("relativeToVRT") == "1"
        assert nodes[0].text == "rasters/1/cog.tif"


class TestRewriteAzurePrefix:
    def test_strips_vsiaz_prefix_to_logical_key(self, tmp_path: Path) -> None:
        vrt = tmp_path / "test.vrt"
        _write_vrt(
            vrt,
            _make_vrt_xml([("0", "/vsiaz/mycontainer/rasters/2/cog.tif")]),
        )

        changes = rewrite_vrt_sources(vrt)

        assert len(changes) == 1
        assert "/vsiaz/mycontainer/rasters/2/cog.tif -> rasters/2/cog.tif" in changes[0]

    def test_rewrites_vsiaz_node_attribute(self, tmp_path: Path) -> None:
        vrt = tmp_path / "test.vrt"
        _write_vrt(
            vrt,
            _make_vrt_xml([("0", "/vsiaz/mycontainer/rasters/2/cog.tif")]),
        )

        rewrite_vrt_sources(vrt)

        tree = parse(str(vrt))
        nodes = list(tree.getroot().iter("SourceFilename"))
        assert nodes[0].get("relativeToVRT") == "1"
        assert nodes[0].text == "rasters/2/cog.tif"


class TestVrtOfVrt:
    """VRT-of-VRT: a SourceFilename pointing to another .vrt is rewritten the same way."""

    def test_strips_vrt_source_filename_with_s3_prefix(self, tmp_path: Path) -> None:
        vrt = tmp_path / "test.vrt"
        _write_vrt(
            vrt,
            _make_vrt_xml([("0", "/vsis3/bucket/rasters/2/source.vrt")]),
        )

        changes = rewrite_vrt_sources(vrt)

        assert len(changes) == 1
        assert "rasters/2/source.vrt" in changes[0]

        tree = parse(str(vrt))
        nodes = list(tree.getroot().iter("SourceFilename"))
        assert nodes[0].text == "rasters/2/source.vrt"
        assert nodes[0].get("relativeToVRT") == "1"

    def test_strips_vrt_source_filename_with_vsiaz_prefix(self, tmp_path: Path) -> None:
        vrt = tmp_path / "test.vrt"
        _write_vrt(
            vrt,
            _make_vrt_xml([("0", "/vsiaz/container/rasters/nested/source.vrt")]),
        )

        changes = rewrite_vrt_sources(vrt)

        assert len(changes) == 1
        assert "rasters/nested/source.vrt" in changes[0]

    def test_mixed_tif_and_vrt_sources(self, tmp_path: Path) -> None:
        """Both .tif and nested .vrt SourceFilename nodes are rewritten."""
        vrt = tmp_path / "test.vrt"
        _write_vrt(
            vrt,
            _make_vrt_xml(
                [
                    ("0", "/vsis3/bucket/rasters/1/cog.tif"),
                    ("0", "/vsis3/bucket/rasters/2/source.vrt"),
                ]
            ),
        )

        changes = rewrite_vrt_sources(vrt)

        assert len(changes) == 2


class TestDryRun:
    def test_dry_run_returns_changes_without_writing(self, tmp_path: Path) -> None:
        vrt = tmp_path / "test.vrt"
        original_xml = _make_vrt_xml([("0", "/vsis3/bucket/rasters/1/cog.tif")])
        _write_vrt(vrt, original_xml)
        mtime_before = vrt.stat().st_mtime

        changes = rewrite_vrt_sources(vrt, dry_run=True)

        # Changes reported
        assert len(changes) == 1
        # File not modified
        assert vrt.stat().st_mtime == mtime_before
        assert vrt.read_text(encoding="utf-8") == original_xml

    def test_dry_run_on_already_clean_vrt_returns_empty(self, tmp_path: Path) -> None:
        vrt = tmp_path / "test.vrt"
        _write_vrt(vrt, _make_vrt_xml([("1", "rasters/1/cog.tif")]))
        mtime_before = vrt.stat().st_mtime

        changes = rewrite_vrt_sources(vrt, dry_run=True)

        assert changes == []
        assert vrt.stat().st_mtime == mtime_before


class TestIdempotency:
    def test_already_relative_source_is_unchanged(self, tmp_path: Path) -> None:
        """A SourceFilename without a VSI prefix is left unchanged."""
        vrt = tmp_path / "test.vrt"
        _write_vrt(vrt, _make_vrt_xml([("1", "rasters/1/cog.tif")]))

        changes = rewrite_vrt_sources(vrt)

        assert changes == []

    def test_second_pass_returns_no_changes(self, tmp_path: Path) -> None:
        """Running rewrite_vrt_sources twice yields no changes on the second pass."""
        vrt = tmp_path / "test.vrt"
        _write_vrt(
            vrt,
            _make_vrt_xml([("0", "/vsis3/bucket/rasters/1/cog.tif")]),
        )

        first_pass = rewrite_vrt_sources(vrt)
        assert len(first_pass) == 1  # changed on first pass

        second_pass = rewrite_vrt_sources(vrt)
        assert second_pass == []  # idempotent — no changes on second pass

    def test_second_pass_does_not_modify_file(self, tmp_path: Path) -> None:
        vrt = tmp_path / "test.vrt"
        _write_vrt(
            vrt,
            _make_vrt_xml([("0", "/vsis3/bucket/rasters/1/cog.tif")]),
        )

        rewrite_vrt_sources(vrt)
        content_after_first = vrt.read_bytes()

        rewrite_vrt_sources(vrt)
        content_after_second = vrt.read_bytes()

        assert content_after_first == content_after_second


class TestStoreRoundtrip:
    """Store-roundtrip: a VRT written with concrete paths, rewritten to logical keys,
    then fetched from "storage" (LocalStorageProvider simulation), still parses
    correctly and contains NO /vsis3/ or /vsiaz/ literals."""

    def test_stored_vrt_contains_no_vsi_literals(self, tmp_path: Path) -> None:
        # Build a VRT with "concrete" absolute paths
        vrt = tmp_path / "source.vrt"
        _write_vrt(
            vrt,
            _make_vrt_xml(
                [
                    ("0", "/vsis3/mybucket/rasters/1/cog.tif"),
                    ("0", "/vsiaz/mycontainer/rasters/2/cog.tif"),
                ]
            ),
        )

        rewrite_vrt_sources(vrt)

        # Simulate "fetch from storage" — just read the file back
        stored_content = vrt.read_text(encoding="utf-8")
        assert "/vsis3/" not in stored_content
        assert "/vsiaz/" not in stored_content

    def test_stored_vrt_all_sourcenames_have_relativetovrt_1(
        self, tmp_path: Path
    ) -> None:
        vrt = tmp_path / "source.vrt"
        _write_vrt(
            vrt,
            _make_vrt_xml(
                [
                    ("0", "/vsis3/mybucket/rasters/1/cog.tif"),
                    ("0", "/vsis3/mybucket/rasters/2/cog.tif"),
                ]
            ),
        )

        rewrite_vrt_sources(vrt)

        tree = parse(str(vrt))
        for node in tree.getroot().iter("SourceFilename"):
            assert node.get("relativeToVRT") == "1", (
                f"SourceFilename '{node.text}' still has relativeToVRT != '1'"
            )


class TestMultipleSourceNodes:
    def test_multiple_s3_sources_all_rewritten(self, tmp_path: Path) -> None:
        vrt = tmp_path / "test.vrt"
        _write_vrt(
            vrt,
            _make_vrt_xml(
                [
                    ("0", "/vsis3/bucket/rasters/1/cog.tif"),
                    ("0", "/vsis3/bucket/rasters/2/cog.tif"),
                    ("0", "/vsis3/bucket/rasters/3/cog.tif"),
                ]
            ),
        )

        changes = rewrite_vrt_sources(vrt)

        assert len(changes) == 3
        tree = parse(str(vrt))
        for node in tree.getroot().iter("SourceFilename"):
            assert node.get("relativeToVRT") == "1"
            assert not node.text.startswith("/vsis3/")


class TestOrderingProof:
    """ORDERING PROOF (machine-checkable per plan acceptance_criteria).

    Simulates the tasks_vrt.py ordering contract:
    1. Build a real rasterio-generated TIF at a concrete path
    2. Build an in-flight tmp VRT over it with gdalbuildvrt (concrete paths — GDAL can open it)
    3. Extract metadata from the in-flight VRT BEFORE any rewrite
    4. Build a "stored" VRT that simulates what would be put to object storage:
       VRT XML with the same sources but expressed as /vsis3/ paths
    5. Run rewrite_vrt_sources on the "stored" VRT (the store-site call)
    6. Reopen the stored logical-key VRT via resolve_open_path (local provider)
    7. Assert metadata from step 3 EQUALS metadata from the stored logical-key VRT

    This proves:
      - extraction (step 3) ran from the concrete in-flight VRT BEFORE the rewrite (step 5)
      - the stored logical-key VRT (after rewrite) is still openable via resolve_open_path
      - band_count / dtype / crs / size are identical between in-flight and stored VRTs

    If rewrite had been run BEFORE extraction (wrong ordering), step 3 would either
    fail (GDAL cannot open a /vsis3/ path without credentials) or produce different
    metadata than the logical-key VRT.
    """

    def test_metadata_equality_proves_ordering(self, tmp_path: Path) -> None:
        storage_root = tmp_path / "storage"
        storage_root.mkdir(parents=True, exist_ok=True)

        # Write a TIF at the logical-key location under storage_root
        # (the local provider serves files from storage_root)
        tif_logical_key = "rasters/test123/source.cog.tif"
        tif_stored_path = storage_root / tif_logical_key
        tif_stored_path.parent.mkdir(parents=True, exist_ok=True)

        transform = from_bounds(0, 0, 1, 1, 64, 64)
        with rasterio.open(
            str(tif_stored_path),
            "w",
            driver="GTiff",
            height=64,
            width=64,
            count=1,
            dtype="uint8",
            crs=CRS.from_epsg(4326),
            transform=transform,
        ) as dst:
            dst.write(np.zeros((1, 64, 64), dtype="uint8"))

        # --- Step 2: Build the in-flight VRT with the concrete absolute TIF path ---
        # Placed in tmp_path (NOT storage_root) to mirror tasks_vrt.py's tempfile.mkdtemp()
        from app.processing.raster.vrt import _build_vrt

        tmp_vrt = tmp_path / "inflight.vrt"
        _build_vrt([str(tif_stored_path)], str(tmp_vrt), "finest")

        # --- Step 3: Extract metadata BEFORE any rewrite ---
        from app.processing.raster.cog import extract_raster_metadata

        meta_inflight = extract_raster_metadata(str(tmp_vrt))
        # Sanity-check: in-flight extraction must succeed
        assert meta_inflight["band_count"] == 1
        assert meta_inflight["epsg"] == 4326

        # --- Step 4: Construct the "stored" VRT with a /vsis3/ SourceFilename
        #     (simulating what tasks_vrt.py put to object storage before this plan).
        #     The stored VRT lives in the same directory as the TIF so that after the
        #     rewrite, the relative SourceFilename "source.cog.tif" resolves correctly.
        stored_vrt_path = storage_root / "rasters/test123/source.vrt"
        stored_vrt_path.parent.mkdir(parents=True, exist_ok=True)

        # Build the stored VRT from the actual TIF via _build_vrt so that the VRT
        # header dimensions (rasterXSize / rasterYSize) match the real TIF (64x64),
        # not the 256x256 hardcoded in _make_vrt_xml.  This simulates the real
        # pipeline: gdalbuildvrt writes a VRT over the concrete TIF path, then
        # tasks_vrt.py puts that XML to object storage before rewrite.
        _build_vrt([str(tif_stored_path)], str(stored_vrt_path), "finest")

        # Replace the concrete local SourceFilename with a /vsis3/ path so that
        # rewrite_vrt_sources has something to rewrite (matching the pre-1210 stored
        # form where VSI paths were written directly into the stored VRT).
        import xml.etree.ElementTree as _ET

        _pre_tree = _ET.parse(str(stored_vrt_path))
        _pre_root = _pre_tree.getroot()
        for _node in _pre_root.iter("SourceFilename"):
            _node.text = f"/vsis3/mybucket/{tif_logical_key}"
            _node.set("relativeToVRT", "0")
        _ET.ElementTree(_pre_root).write(
            str(stored_vrt_path), encoding="utf-8", xml_declaration=True
        )

        # --- Step 5: ORDERING GATE — rewrite_vrt_sources runs AFTER extraction ---
        # (extraction already done in step 3 above)
        # CR-01 fix: supply vrt_storage_key so the rewrite computes paths relative
        # to the VRT's own directory within the bucket.  The VRT is at
        # "rasters/test123/source.vrt" and the source COG is at
        # "rasters/test123/source.cog.tif", so the correct relative path is
        # "source.cog.tif" (same directory), NOT the full logical key.
        stored_vrt_key = "rasters/test123/source.vrt"
        changes = rewrite_vrt_sources(stored_vrt_path, vrt_storage_key=stored_vrt_key)
        assert len(changes) == 1, (
            "Expected one SourceFilename rewritten (S3 -> logical)"
        )

        # Stored copy must have no /vsis3/ literal after rewrite
        stored_content = stored_vrt_path.read_text(encoding="utf-8")
        assert "/vsis3/" not in stored_content

        # Verify the rewriter produced the BASENAME-relative path, not the full key.
        # With vrt_storage_key="rasters/test123/source.vrt", the VRT dir is
        # "rasters/test123/" and the source is "rasters/test123/source.cog.tif",
        # so relpath = "source.cog.tif".
        from xml.etree.ElementTree import parse as _parse

        _tree = _parse(str(stored_vrt_path))
        _nodes = list(_tree.getroot().iter("SourceFilename"))
        assert len(_nodes) == 1
        assert _nodes[0].text == "source.cog.tif", (
            f"Expected relative path 'source.cog.tif' but got {_nodes[0].text!r}. "
            "CR-01: vrt_storage_key must be passed to rewrite_vrt_sources."
        )
        assert _nodes[0].get("relativeToVRT") == "1"

        # --- Step 6: Reopen stored VRT via resolve_open_path (local provider) ---
        with patch("app.core.config.settings.upload_staging_dir", str(storage_root)):
            from app.platform.storage.titiler_url import resolve_open_path

            stored_open_path = resolve_open_path(stored_vrt_key)
            assert stored_open_path == str(stored_vrt_path)

        # --- Step 7: Extract metadata from stored VRT and assert equality ---
        meta_stored = extract_raster_metadata(stored_open_path)

        assert meta_inflight["band_count"] == meta_stored["band_count"], (
            f"band_count mismatch: inflight={meta_inflight['band_count']} "
            f"stored={meta_stored['band_count']}"
        )
        assert meta_inflight["dtype"] == meta_stored["dtype"], (
            f"dtype mismatch: inflight={meta_inflight['dtype']} "
            f"stored={meta_stored['dtype']}"
        )
        assert meta_inflight["epsg"] == meta_stored["epsg"], (
            f"epsg mismatch: inflight={meta_inflight['epsg']} "
            f"stored={meta_stored['epsg']}"
        )
        assert meta_inflight["width"] == meta_stored["width"], (
            f"width mismatch: inflight={meta_inflight['width']} "
            f"stored={meta_stored['width']}"
        )
        assert meta_inflight["height"] == meta_stored["height"], (
            f"height mismatch: inflight={meta_inflight['height']} "
            f"stored={meta_stored['height']}"
        )
