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

    def test_validate_vrt_body_consumes_shared_constant(self):
        """validate_vrt_body uses VRT_VSI_ALLOWED_PREFIXES from raster/vrt.py
        — not a private copy. Proves this via object identity.

        WR-05 (Phase 1071 review): the previous test monkey-patched both
        vrt_module and validation_module, but the vrt_module patch was inert
        because `from app.processing.raster.vrt import VRT_VSI_ALLOWED_PREFIXES`
        binds the name in validation's namespace at import time (value copy,
        not live reference). The inert patch created a false impression that the
        test proved read-through from vrt.py's namespace at call time.

        This assertion is the correct structural proof: if validation.py ever
        re-inlines the constant (a private copy), the two objects will no
        longer be identical and this test fails.
        """
        from app.processing.ingest.validation import (
            VRT_VSI_ALLOWED_PREFIXES as v_const,
        )
        from app.processing.raster.vrt import VRT_VSI_ALLOWED_PREFIXES as vrt_const

        assert v_const is vrt_const, (
            "validation.py has re-inlined VRT_VSI_ALLOWED_PREFIXES (private copy detected). "
            "It must import the constant from app.processing.raster.vrt."
        )

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
