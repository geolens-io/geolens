"""KNOWN-04 (Phase 1071): VRT VSI allow-list single source of truth.

Pins:
- VRT_VSI_ALLOWED_PREFIXES exports from raster/vrt.py with the expected
  7 alphabetically-sorted prefixes.
- validate_vrt_body intentionally rejects VSI paths for user-uploaded VRTs.
"""

from __future__ import annotations

import pytest


EXPECTED_PREFIXES = (
    "/vsiaz/",
    "/vsicurl/",
    "/vsigs/",
    "/vsimem/",
    "/vsis3/",
    "/vsitar/",
    "/vsizip/",
)


class TestVrtVsiAllowedPrefixes:
    def test_constant_shape_and_value(self):
        """The exported constant has exactly the 7 expected prefixes."""
        from app.processing.raster.vrt import VRT_VSI_ALLOWED_PREFIXES

        assert VRT_VSI_ALLOWED_PREFIXES == EXPECTED_PREFIXES, (
            "VRT_VSI_ALLOWED_PREFIXES drifted from the locked KNOWN-04 shape. "
            "If adding a scheme, also update EXPECTED_PREFIXES here AND the "
            "documentation comment block in raster/vrt.py."
        )

    def test_constant_is_a_tuple(self):
        """Must be a tuple — str.startswith uses tuple semantics."""
        from app.processing.raster.vrt import VRT_VSI_ALLOWED_PREFIXES

        assert isinstance(VRT_VSI_ALLOWED_PREFIXES, tuple)

    def test_user_uploaded_vrt_rejects_vsi_even_when_internal_constant_allows_it(
        self, tmp_path
    ):
        """The allow-list is for internal managed VRT generation, not uploads."""
        from app.processing.ingest.validation import validate_vrt_body

        vrt_file = tmp_path / "managed_path.vrt"
        vrt_file.write_bytes(
            b'<?xml version="1.0"?>\n'
            b'<VRTDataset rasterXSize="1" rasterYSize="1">\n'
            b'  <VRTRasterBand dataType="Byte" band="1">\n'
            b"    <SimpleSource>\n"
            b"      <SourceFilename>/vsis3/bucket/key.tif</SourceFilename>\n"
            b"      <SourceBand>1</SourceBand>\n"
            b"    </SimpleSource>\n"
            b"  </VRTRasterBand>\n"
            b"</VRTDataset>\n"
        )

        with pytest.raises(ValueError) as exc:
            validate_vrt_body(str(vrt_file))
        assert "absolute path" in str(exc.value).lower()

    def test_validate_vrt_body_rejects_unknown_vsi_scheme(self, tmp_path):
        """Sanity check: an unknown VSI scheme is rejected when NOT in
        the allow-list (no monkey-patching here — exercises real list)."""
        from app.processing.ingest.validation import validate_vrt_body

        vrt_file = tmp_path / "evil.vrt"
        vrt_file.write_bytes(
            b'<?xml version="1.0"?>\n'
            b'<VRTDataset rasterXSize="1" rasterYSize="1">\n'
            b'  <VRTRasterBand dataType="Byte" band="1">\n'
            b"    <SimpleSource>\n"
            b"      <SourceFilename>/etc/passwd</SourceFilename>\n"
            b"      <SourceBand>1</SourceBand>\n"
            b"    </SimpleSource>\n"
            b"  </VRTRasterBand>\n"
            b"</VRTDataset>\n"
        )

        with pytest.raises(ValueError) as exc:
            validate_vrt_body(str(vrt_file))
        assert "absolute path" in str(exc.value).lower() or "/etc" in str(exc.value)
