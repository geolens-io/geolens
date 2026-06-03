"""Regression test for ING-07 / P2-09.

`RasterCommitRequest.strict_cog=True` opts the commit path out of the
silent `check_and_prepare_cog` rewrite. The gate lives in
``tasks_raster._enforce_strict_cog``: on non-compliance it raises
``ValueError("Strict-COG mode rejected upload: <reason>. ...")`` which
the existing outer ``except Exception`` handler in ``ingest_raster``
translates into ``job.status='failed'`` + ``job.error_message``.

Approach: exercise the helper directly with ``check_cog_compliance``
patched. Avoids spinning up the full Procrastinate task + GDAL +
session lifecycle just to assert the gate's branch behavior.

Pins four invariants:
  1. strict_cog=True + non-compliant → ValueError with reason.
  2. strict_cog=True + compliant → no raise.
  3. strict_cog=False → check_cog_compliance is NOT called (backward
     compat — every existing call site sees zero behavior change).
  4. is_manifest_vrt=True → gate skipped even when strict_cog=True
     (VRTs are XML, not TIFFs).
"""

from unittest.mock import patch

import pytest

from app.processing.ingest.tasks_raster import _enforce_strict_cog


class TestStrictCogEnforcement:
    """Pin behavior of the strict-mode COG gate (ING-07 / P2-09)."""

    async def test_rejects_non_compliant_when_strict(self) -> None:
        """strict_cog=True + non-compliant → ValueError with the reason."""
        with patch(
            "app.processing.ingest.tasks_raster.check_cog_compliance",
            return_value=(False, "Not tiled"),
        ) as mock_check:
            with pytest.raises(ValueError) as exc_info:
                await _enforce_strict_cog(
                    "/tmp/sample.tif",
                    expected_compression="DEFLATE",
                    is_manifest_vrt=False,
                    strict_cog=True,
                )
            assert "Strict-COG mode rejected upload" in str(exc_info.value)
            assert "Not tiled" in str(exc_info.value)
            mock_check.assert_called_once()

    async def test_accepts_compliant_when_strict(self) -> None:
        """strict_cog=True + compliant → no raise, helper returns None."""
        with patch(
            "app.processing.ingest.tasks_raster.check_cog_compliance",
            return_value=(True, ""),
        ) as mock_check:
            result = await _enforce_strict_cog(
                "/tmp/sample.tif",
                expected_compression="DEFLATE",
                is_manifest_vrt=False,
                strict_cog=True,
            )
            assert result is None
            mock_check.assert_called_once()

    async def test_skips_check_when_not_strict(self) -> None:
        """strict_cog=False → check_cog_compliance is NOT called.

        Backward-compat invariant. Every existing raster ingest call site
        omits the flag (Pydantic default False) and must see zero behavior
        change.
        """
        with patch(
            "app.processing.ingest.tasks_raster.check_cog_compliance",
        ) as mock_check:
            await _enforce_strict_cog(
                "/tmp/sample.tif",
                expected_compression="DEFLATE",
                is_manifest_vrt=False,
                strict_cog=False,
            )
            mock_check.assert_not_called()

    async def test_skips_check_when_manifest_vrt(self) -> None:
        """is_manifest_vrt=True bypasses the gate even with strict_cog=True.

        VRT manifests are XML, not TIFFs — `check_cog_compliance` would
        fail for unrelated reasons. The manifest-VRT path stays on its
        own validation rails upstream.
        """
        with patch(
            "app.processing.ingest.tasks_raster.check_cog_compliance",
        ) as mock_check:
            await _enforce_strict_cog(
                "/tmp/manifest.vrt",
                expected_compression="DEFLATE",
                is_manifest_vrt=True,
                strict_cog=True,
            )
            mock_check.assert_not_called()
