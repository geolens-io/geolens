"""The strict-mode COG gate.

`RasterCommitRequest.strict_cog=True` opts the commit path out of the
silent `check_and_prepare_cog` rewrite. The gate lives in
``tasks_raster_common._enforce_strict_cog`` and reads the source inspection
the probe child already made: on non-compliance it raises
``ValueError("Strict-COG mode rejected upload: <reason>. ...")``, which
the outer ``except Exception`` handler in ``ingest_raster`` translates into
``job.status='failed'`` + ``job.error_message``.

Pins four invariants:
  1. strict_cog=True + non-compliant → ValueError with reason.
  2. strict_cog=True + compliant → no raise.
  3. strict_cog=False → no raise, whatever the verdict.
  4. is_manifest_vrt=True → gate skipped even when strict_cog=True
     (VRTs are XML, not TIFFs).
"""

import pytest

from app.processing.ingest.tasks_raster_common import _enforce_strict_cog

_NOT_TILED = {"compliant": False, "compliance_reason": "Not tiled"}


class TestStrictCogEnforcement:
    def test_rejects_non_compliant_when_strict(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            _enforce_strict_cog(_NOT_TILED, is_manifest_vrt=False, strict_cog=True)
        assert "Strict-COG mode rejected upload" in str(exc_info.value)
        assert "Not tiled" in str(exc_info.value)

    def test_accepts_compliant_when_strict(self) -> None:
        compliant = {"compliant": True, "compliance_reason": ""}
        assert (
            _enforce_strict_cog(compliant, is_manifest_vrt=False, strict_cog=True)
            is None
        )

    def test_skips_check_when_not_strict(self) -> None:
        """Every call site that omits the flag (Pydantic default False) passes."""
        _enforce_strict_cog(_NOT_TILED, is_manifest_vrt=False, strict_cog=False)

    def test_skips_check_when_manifest_vrt(self) -> None:
        """VRT manifests are XML, and their compliance verdict means nothing."""
        _enforce_strict_cog(_NOT_TILED, is_manifest_vrt=True, strict_cog=True)
