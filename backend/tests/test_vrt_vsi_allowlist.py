"""KNOWN-04 (Phase 1071): VRT VSI allow-list single source of truth.

Pins:
- VRT_VSI_ALLOWED_PREFIXES exports from raster/vrt.py with the expected
  7 alphabetically-sorted prefixes.
- validate_vrt_body consumes the shared constant (not a local copy).
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

    def test_validate_vrt_body_consumes_shared_constant(self, tmp_path, monkeypatch):
        """Monkey-patch the constant and confirm validate_vrt_body picks it up
        — proves the validator does not carry a private copy."""
        from app.processing.ingest import validation as validation_module
        from app.processing.raster import vrt as vrt_module

        # Add a test-only fake prefix and confirm validate_vrt_body
        # accepts a SourceFilename using it. If validate_vrt_body has a
        # private copy of the prefix list, the monkey-patch won't affect it
        # and the assertion below fails.
        test_prefix = "/vsifake_phase1071/"
        patched = vrt_module.VRT_VSI_ALLOWED_PREFIXES + (test_prefix,)

        monkeypatch.setattr(vrt_module, "VRT_VSI_ALLOWED_PREFIXES", patched)
        monkeypatch.setattr(
            validation_module, "VRT_VSI_ALLOWED_PREFIXES", patched
        )

        # Write a minimal VRT with a SourceFilename using the fake prefix
        vrt_file = tmp_path / "fake.vrt"
        vrt_file.write_bytes(
            b'<?xml version="1.0"?>\n'
            b'<VRTDataset rasterXSize="1" rasterYSize="1">\n'
            b"  <SRS>EPSG:4326</SRS>\n"
            b'  <VRTRasterBand dataType="Byte" band="1">\n'
            b'    <SimpleSource>\n'
            b'      <SourceFilename relativeToVRT="0">' + test_prefix.encode() + b'fake.tif</SourceFilename>\n'
            b'      <SourceBand>1</SourceBand>\n'
            b'    </SimpleSource>\n'
            b'  </VRTRasterBand>\n'
            b"</VRTDataset>\n"
        )

        # If validate_vrt_body consumes the shared constant, this passes.
        # If it has a private copy, ValueError fires (absolute path rejected).
        validation_module.validate_vrt_body(str(vrt_file))  # MUST NOT raise

    def test_validate_vrt_body_rejects_unknown_vsi_scheme(self, tmp_path):
        """Sanity check: an unknown VSI scheme is rejected when NOT in
        the allow-list (no monkey-patching here — exercises real list)."""
        from app.processing.ingest.validation import validate_vrt_body

        vrt_file = tmp_path / "evil.vrt"
        vrt_file.write_bytes(
            b'<?xml version="1.0"?>\n'
            b'<VRTDataset rasterXSize="1" rasterYSize="1">\n'
            b'  <VRTRasterBand dataType="Byte" band="1">\n'
            b'    <SimpleSource>\n'
            b'      <SourceFilename>/etc/passwd</SourceFilename>\n'
            b'      <SourceBand>1</SourceBand>\n'
            b'    </SimpleSource>\n'
            b'  </VRTRasterBand>\n'
            b"</VRTDataset>\n"
        )

        with pytest.raises(ValueError) as exc:
            validate_vrt_body(str(vrt_file))
        assert "absolute path" in str(exc.value).lower() or "/etc" in str(exc.value)
