"""Unit tests for backend/app/raster/validation.py.

All tests are pure unit tests — no DB, no files, no network.
A FakeRasterAsset dataclass substitutes for SQLAlchemy RasterAsset objects.
CRS equality is tested via mock to avoid real WKT string handling.
"""

import uuid
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, patch


from app.processing.raster.validation import SourceValidationError, validate_sources


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeRasterAsset:
    """Minimal stand-in for RasterAsset with fields used by validate_sources."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    crs_wkt: Optional[str] = "EPSG:4326-WKT"
    band_count: Optional[int] = 1
    dtype: Optional[str] = "uint8"
    nodata: Optional[str] = None
    res_x: Optional[float] = 1.0
    res_y: Optional[float] = 1.0
    width: Optional[int] = 256
    height: Optional[int] = 256
    is_rotated: bool = False


def _ids(errors: list[SourceValidationError]) -> set[str]:
    return {e.code for e in errors}


# ---------------------------------------------------------------------------
# TestCrsCheck
# ---------------------------------------------------------------------------


class TestCrsCheck:
    """VAL-01: CRS consistency check (mosaic + band_stack)."""

    def _make_mock_crs(self, *, equal: bool):
        """Return a CRS mock whose .equals() returns `equal`."""
        crs = MagicMock()
        crs.equals.return_value = equal
        return crs

    def test_matching_crs_no_errors(self):
        sources = [FakeRasterAsset(), FakeRasterAsset()]
        mock_crs = self._make_mock_crs(equal=True)

        with patch("app.processing.raster.validation.rasterio") as mock_rasterio:
            mock_rasterio.CRS.from_wkt.return_value = mock_crs
            errors = validate_sources("mosaic", sources)

        crs_errors = [e for e in errors if e.code == "crs_mismatch"]
        assert crs_errors == []

    def test_mismatched_crs_returns_error(self):
        sources = [FakeRasterAsset(), FakeRasterAsset()]
        ref_crs = MagicMock()
        other_crs = MagicMock()
        ref_crs.equals.return_value = False

        with patch("app.processing.raster.validation.rasterio") as mock_rasterio:
            mock_rasterio.CRS.from_wkt.side_effect = [ref_crs, other_crs]
            errors = validate_sources("mosaic", sources)

        crs_errors = [e for e in errors if e.code == "crs_mismatch"]
        assert len(crs_errors) == 1
        assert crs_errors[0].source_id == sources[1].id
        assert crs_errors[0].field == "crs_wkt"

    def test_none_crs_skipped(self):
        """Sources with crs_wkt=None are skipped; no error raised."""
        sources = [
            FakeRasterAsset(crs_wkt=None),
            FakeRasterAsset(crs_wkt=None),
        ]

        with patch("app.processing.raster.validation.rasterio") as mock_rasterio:
            errors = validate_sources("mosaic", sources)

        crs_errors = [e for e in errors if e.code == "crs_mismatch"]
        assert crs_errors == []
        # from_wkt should not have been called for None-crs sources
        mock_rasterio.CRS.from_wkt.assert_not_called()

    def test_crs_checked_for_band_stack(self):
        sources = [FakeRasterAsset(), FakeRasterAsset()]
        ref_crs = MagicMock()
        ref_crs.equals.return_value = False

        with patch("app.processing.raster.validation.rasterio") as mock_rasterio:
            mock_rasterio.CRS.from_wkt.return_value = ref_crs
            errors = validate_sources("band_stack", sources)

        crs_errors = [e for e in errors if e.code == "crs_mismatch"]
        assert len(crs_errors) == 1


# ---------------------------------------------------------------------------
# TestBandCountCheck
# ---------------------------------------------------------------------------


class TestBandCountCheck:
    """VAL-02: Band count check (mosaic only)."""

    def test_matching_band_count_no_errors(self):
        sources = [FakeRasterAsset(band_count=3), FakeRasterAsset(band_count=3)]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", sources)
        bc_errors = [e for e in errors if e.code == "band_count_mismatch"]
        assert bc_errors == []

    def test_mismatched_band_count_mosaic_error(self):
        sources = [FakeRasterAsset(band_count=3), FakeRasterAsset(band_count=1)]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", sources)
        bc_errors = [e for e in errors if e.code == "band_count_mismatch"]
        assert len(bc_errors) == 1
        assert bc_errors[0].source_id == sources[1].id
        assert bc_errors[0].field == "band_count"

    def test_band_count_not_checked_for_band_stack(self):
        """band_count_mismatch should never appear for band_stack."""
        sources = [FakeRasterAsset(band_count=3), FakeRasterAsset(band_count=1)]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("band_stack", sources)
        bc_errors = [e for e in errors if e.code == "band_count_mismatch"]
        assert bc_errors == []


# ---------------------------------------------------------------------------
# TestSingleBandCheck
# ---------------------------------------------------------------------------


class TestSingleBandCheck:
    """VAL-03: Single-band requirement (band_stack only)."""

    def test_single_band_sources_pass(self):
        sources = [FakeRasterAsset(band_count=1), FakeRasterAsset(band_count=1)]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("band_stack", sources)
        sb_errors = [e for e in errors if e.code == "single_band_required"]
        assert sb_errors == []

    def test_multi_band_source_fails(self):
        sources = [FakeRasterAsset(band_count=1), FakeRasterAsset(band_count=3)]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("band_stack", sources)
        sb_errors = [e for e in errors if e.code == "single_band_required"]
        assert len(sb_errors) == 1
        assert sb_errors[0].source_id == sources[1].id
        assert sb_errors[0].field == "band_count"

    def test_single_band_not_checked_for_mosaic(self):
        sources = [FakeRasterAsset(band_count=3), FakeRasterAsset(band_count=3)]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", sources)
        sb_errors = [e for e in errors if e.code == "single_band_required"]
        assert sb_errors == []


# ---------------------------------------------------------------------------
# TestDtypeCheck
# ---------------------------------------------------------------------------


class TestDtypeCheck:
    """VAL-04: dtype consistency check (mosaic + band_stack)."""

    def test_matching_dtype_no_errors(self):
        sources = [FakeRasterAsset(dtype="float32"), FakeRasterAsset(dtype="float32")]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", sources)
        dt_errors = [e for e in errors if e.code == "dtype_mismatch"]
        assert dt_errors == []

    def test_mismatched_dtype_error(self):
        sources = [FakeRasterAsset(dtype="uint8"), FakeRasterAsset(dtype="float32")]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", sources)
        dt_errors = [e for e in errors if e.code == "dtype_mismatch"]
        assert len(dt_errors) == 1
        assert dt_errors[0].source_id == sources[1].id
        assert dt_errors[0].field == "dtype"

    def test_dtype_checked_for_band_stack(self):
        sources = [FakeRasterAsset(dtype="uint8"), FakeRasterAsset(dtype="float32")]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("band_stack", sources)
        dt_errors = [e for e in errors if e.code == "dtype_mismatch"]
        assert len(dt_errors) == 1


# ---------------------------------------------------------------------------
# TestNodataCheck
# ---------------------------------------------------------------------------


class TestNodataCheck:
    """VAL-06: Nodata consistency check (mosaic + band_stack)."""

    def test_all_none_nodata_passes(self):
        sources = [FakeRasterAsset(nodata=None), FakeRasterAsset(nodata=None)]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", sources)
        nd_errors = [e for e in errors if e.code == "nodata_inconsistent"]
        assert nd_errors == []

    def test_all_defined_nodata_passes(self):
        sources = [FakeRasterAsset(nodata="-9999"), FakeRasterAsset(nodata="0")]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", sources)
        nd_errors = [e for e in errors if e.code == "nodata_inconsistent"]
        assert nd_errors == []

    def test_mixed_nodata_fails(self):
        """First source has nodata, second does not."""
        sources = [FakeRasterAsset(nodata="-9999"), FakeRasterAsset(nodata=None)]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", sources)
        nd_errors = [e for e in errors if e.code == "nodata_inconsistent"]
        assert len(nd_errors) == 1
        assert nd_errors[0].source_id == sources[1].id
        assert nd_errors[0].field == "nodata"

    def test_mixed_nodata_reverse_fails(self):
        """First source has no nodata, second does."""
        sources = [FakeRasterAsset(nodata=None), FakeRasterAsset(nodata="-9999")]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", sources)
        nd_errors = [e for e in errors if e.code == "nodata_inconsistent"]
        assert len(nd_errors) == 1

    def test_nodata_checked_for_band_stack(self):
        sources = [FakeRasterAsset(nodata="-9999"), FakeRasterAsset(nodata=None)]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("band_stack", sources)
        nd_errors = [e for e in errors if e.code == "nodata_inconsistent"]
        assert len(nd_errors) == 1


# ---------------------------------------------------------------------------
# TestRotationCheck
# ---------------------------------------------------------------------------


class TestRotationCheck:
    """VAL-07: Rotation rejection (mosaic + band_stack)."""

    def test_non_rotated_no_errors(self):
        sources = [FakeRasterAsset(is_rotated=False), FakeRasterAsset(is_rotated=False)]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", sources)
        rot_errors = [e for e in errors if e.code == "rotated_raster"]
        assert rot_errors == []

    def test_rotated_source_fails(self):
        src_rotated = FakeRasterAsset(is_rotated=True)
        sources = [FakeRasterAsset(is_rotated=False), src_rotated]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", sources)
        rot_errors = [e for e in errors if e.code == "rotated_raster"]
        assert len(rot_errors) == 1
        assert rot_errors[0].source_id == src_rotated.id
        assert rot_errors[0].field == "is_rotated"

    def test_rotation_checked_for_band_stack(self):
        src_rotated = FakeRasterAsset(is_rotated=True)
        sources = [FakeRasterAsset(is_rotated=False), src_rotated]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("band_stack", sources)
        rot_errors = [e for e in errors if e.code == "rotated_raster"]
        assert len(rot_errors) == 1

    def test_first_source_rotated_also_flagged(self):
        """Rotation check applies to ALL sources including the first."""
        src1 = FakeRasterAsset(is_rotated=True)
        src2 = FakeRasterAsset(is_rotated=False)
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", [src1, src2])
        rot_errors = [e for e in errors if e.code == "rotated_raster"]
        assert len(rot_errors) == 1
        assert rot_errors[0].source_id == src1.id


# ---------------------------------------------------------------------------
# TestGridAlignmentCheck
# ---------------------------------------------------------------------------


class TestGridAlignmentCheck:
    """VAL-05: Grid alignment check (band_stack only)."""

    def test_matching_grid_passes(self):
        sources = [
            FakeRasterAsset(width=256, height=256, res_x=1.0, res_y=1.0),
            FakeRasterAsset(width=256, height=256, res_x=1.0, res_y=1.0),
        ]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("band_stack", sources)
        grid_errors = [e for e in errors if e.code == "grid_misaligned"]
        assert grid_errors == []

    def test_mismatched_width_fails(self):
        sources = [
            FakeRasterAsset(width=256, height=256),
            FakeRasterAsset(width=512, height=256),
        ]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("band_stack", sources)
        grid_errors = [e for e in errors if e.code == "grid_misaligned"]
        assert len(grid_errors) == 1
        assert grid_errors[0].field == "width"

    def test_mismatched_height_fails(self):
        sources = [
            FakeRasterAsset(width=256, height=256),
            FakeRasterAsset(width=256, height=512),
        ]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("band_stack", sources)
        grid_errors = [e for e in errors if e.code == "grid_misaligned"]
        assert len(grid_errors) == 1
        assert grid_errors[0].field == "height"

    def test_mismatched_res_x_fails(self):
        sources = [
            FakeRasterAsset(res_x=1.0, res_y=1.0),
            FakeRasterAsset(res_x=2.0, res_y=1.0),
        ]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("band_stack", sources)
        grid_errors = [e for e in errors if e.code == "grid_misaligned"]
        assert len(grid_errors) == 1
        assert grid_errors[0].field == "res_x"

    def test_mismatched_res_y_fails(self):
        sources = [
            FakeRasterAsset(res_x=1.0, res_y=1.0),
            FakeRasterAsset(res_x=1.0, res_y=2.0),
        ]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("band_stack", sources)
        grid_errors = [e for e in errors if e.code == "grid_misaligned"]
        assert len(grid_errors) == 1
        assert grid_errors[0].field == "res_y"

    def test_float_tolerance_within_bounds(self):
        """Tiny floating point differences within tolerance should not trigger grid_misaligned."""
        sources = [
            FakeRasterAsset(res_x=1.0, res_y=1.0),
            FakeRasterAsset(res_x=1.0 + 1e-11, res_y=1.0),
        ]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("band_stack", sources)
        grid_errors = [e for e in errors if e.code == "grid_misaligned"]
        assert grid_errors == []

    def test_grid_not_checked_for_mosaic(self):
        """Grid alignment is only for band_stack; mosaic ignores it."""
        sources = [
            FakeRasterAsset(width=256, height=256),
            FakeRasterAsset(width=512, height=512),
        ]
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", sources)
        grid_errors = [e for e in errors if e.code == "grid_misaligned"]
        assert grid_errors == []


# ---------------------------------------------------------------------------
# TestAllChecksRun
# ---------------------------------------------------------------------------


class TestAllChecksRun:
    """Verify no fail-fast: multiple errors returned for one problematic source."""

    def test_multiple_problems_return_multiple_errors(self):
        """A source with CRS mismatch, dtype mismatch, and rotation returns 3 errors."""
        src_ref = FakeRasterAsset(dtype="uint8", is_rotated=False)
        src_bad = FakeRasterAsset(dtype="float32", is_rotated=True)

        ref_crs = MagicMock()
        ref_crs.equals.return_value = False

        with patch("app.processing.raster.validation.rasterio") as mock_rasterio:
            mock_rasterio.CRS.from_wkt.return_value = ref_crs
            errors = validate_sources("mosaic", [src_ref, src_bad])

        bad_src_errors = [e for e in errors if e.source_id == src_bad.id]
        codes = {e.code for e in bad_src_errors}
        assert "crs_mismatch" in codes
        assert "dtype_mismatch" in codes
        assert "rotated_raster" in codes
        assert len(bad_src_errors) >= 3

    def test_band_stack_multiple_problems(self):
        """Band-stack: CRS mismatch + dtype mismatch + rotation + grid misalign."""
        src_ref = FakeRasterAsset(
            dtype="uint8",
            is_rotated=False,
            band_count=1,
            width=256,
            height=256,
            res_x=1.0,
            res_y=1.0,
        )
        src_bad = FakeRasterAsset(
            dtype="float32",
            is_rotated=True,
            band_count=3,
            width=512,
            height=256,
            res_x=2.0,
            res_y=1.0,
        )

        ref_crs = MagicMock()
        ref_crs.equals.return_value = False

        with patch("app.processing.raster.validation.rasterio") as mock_rasterio:
            mock_rasterio.CRS.from_wkt.return_value = ref_crs
            errors = validate_sources("band_stack", [src_ref, src_bad])

        codes = {e.code for e in errors if e.source_id == src_bad.id}
        assert "crs_mismatch" in codes
        assert "dtype_mismatch" in codes
        assert "rotated_raster" in codes
        assert "single_band_required" in codes


# ---------------------------------------------------------------------------
# TestValidSources
# ---------------------------------------------------------------------------


class TestValidSources:
    """Fully compatible sources return empty list for both vrt_types."""

    def test_valid_mosaic_sources(self):
        sources = [
            FakeRasterAsset(band_count=3, dtype="uint8", nodata=None, is_rotated=False),
            FakeRasterAsset(band_count=3, dtype="uint8", nodata=None, is_rotated=False),
        ]
        mock_crs = MagicMock()
        mock_crs.equals.return_value = True

        with patch("app.processing.raster.validation.rasterio") as mock_rasterio:
            mock_rasterio.CRS.from_wkt.return_value = mock_crs
            errors = validate_sources("mosaic", sources)

        assert errors == []

    def test_valid_band_stack_sources(self):
        sources = [
            FakeRasterAsset(
                band_count=1,
                dtype="float32",
                nodata="-9999",
                is_rotated=False,
                width=256,
                height=256,
                res_x=1.0,
                res_y=1.0,
            ),
            FakeRasterAsset(
                band_count=1,
                dtype="float32",
                nodata="-9999",
                is_rotated=False,
                width=256,
                height=256,
                res_x=1.0,
                res_y=1.0,
            ),
        ]
        mock_crs = MagicMock()
        mock_crs.equals.return_value = True

        with patch("app.processing.raster.validation.rasterio") as mock_rasterio:
            mock_rasterio.CRS.from_wkt.return_value = mock_crs
            errors = validate_sources("band_stack", sources)

        assert errors == []


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases: 0 or 1 sources return empty list."""

    def test_zero_sources(self):
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", [])
        assert errors == []

    def test_one_source(self):
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("mosaic", [FakeRasterAsset()])
        assert errors == []

    def test_one_source_band_stack(self):
        with patch("app.processing.raster.validation.rasterio"):
            errors = validate_sources("band_stack", [FakeRasterAsset()])
        assert errors == []


# ---------------------------------------------------------------------------
# TestSourceValidationError
# ---------------------------------------------------------------------------


class TestSourceValidationError:
    """Verify SourceValidationError has all required fields."""

    def test_all_fields_present(self):
        err = SourceValidationError(
            source_id=uuid.uuid4(),
            code="crs_mismatch",
            message="CRS does not match reference source",
            field="crs_wkt",
        )
        assert err.source_id is not None
        assert err.code == "crs_mismatch"
        assert err.message == "CRS does not match reference source"
        assert err.field == "crs_wkt"
        assert err.severity == "error"  # default

    def test_severity_override(self):
        err = SourceValidationError(
            source_id=uuid.uuid4(),
            code="rotated_raster",
            message="Raster is rotated",
            field="is_rotated",
            severity="warning",
        )
        assert err.severity == "warning"
