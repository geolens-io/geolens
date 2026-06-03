"""SEC-FU-06: parse_bbox must reject NaN and Inf coordinates.

Python's float() accepts 'nan', 'inf', '-inf' and returns the IEEE 754
special values. PostGIS / PostgreSQL handle these inconsistently — some
functions raise, others silently return malformed geometries with downstream
null-pointer or sequential-scan amplification.

Fix: math.isfinite() check on every coordinate after float() conversion,
before envelope reduction and lat-comparison.

Tests use test_sec_fu_06_ prefix for grep-traceability.
"""

import pytest

from app.modules.catalog.features.service import parse_bbox


class TestSecFu06ParseBboxIsfinite:
    def test_sec_fu_06_happy_path_4d(self):
        """Standard 4-value 2D bbox returns list of floats unchanged."""
        result = parse_bbox("-180,-90,180,90")
        assert result == [-180.0, -90.0, 180.0, 90.0]

    def test_sec_fu_06_nan_in_first_coord_raises(self):
        """NaN in the first coordinate raises ValueError."""
        with pytest.raises(ValueError, match="non-finite"):
            parse_bbox("nan,0,1,1")

    def test_sec_fu_06_inf_in_second_coord_raises(self):
        """Positive infinity in the second coordinate raises ValueError."""
        with pytest.raises(ValueError, match="non-finite"):
            parse_bbox("0,inf,1,1")

    def test_sec_fu_06_neg_inf_in_third_coord_raises(self):
        """Negative infinity in the third coordinate raises ValueError."""
        with pytest.raises(ValueError, match="non-finite"):
            parse_bbox("0,0,-inf,1")

    def test_sec_fu_06_3d_bbox_all_finite_passes(self):
        """6-element 3D bbox with all-finite values continues to work (regression)."""
        # 3D bbox: minx, miny, minz, maxx, maxy, maxz
        # parse_bbox extracts the 2D envelope (minx, miny, maxx, maxy)
        result = parse_bbox("0,0,100,1,1,200")
        assert result == [0.0, 0.0, 1.0, 1.0]

    def test_sec_fu_06_3d_bbox_nan_in_z_coord_raises(self):
        """NaN in the Z coordinate of a 3D bbox raises ValueError.

        The isfinite check fires BEFORE the 6-to-4 envelope reduction, so
        a NaN in position 2 (minz) or position 5 (maxz) is also caught.
        """
        with pytest.raises(ValueError, match="non-finite"):
            parse_bbox("0,0,nan,1,1,3")
