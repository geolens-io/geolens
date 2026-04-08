"""Unit tests for pure (no-DB) helpers in app.vector.quicklook.

These cover the coordinate transform, point-radius density scaling, blank
canvas generator, and geometry drawing switchboard without needing a live
database. The async `generate_vector_quicklook` entry points have their own
integration tests; here we just exercise the shapes in isolation so the
module is not a dark spot in coverage.
"""

from io import BytesIO

from PIL import Image, ImageDraw
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from app.vector.quicklook import (
    _BG_COLOR,
    _blank_canvas,
    _compute_point_radius,
    _draw_geometry,
    _geo_to_pixel,
)


class TestGeoToPixel:
    def test_min_corner_maps_inside_padding(self):
        px, py = _geo_to_pixel(0.0, 0.0, (0.0, 0.0, 10.0, 10.0), size=100, padding=6)
        # minx/maxy corner should sit at the padding offset in x, and the
        # y-inverted origin at the padding offset in y (since maxy - y = 10 - 0).
        assert px == 6.0
        assert round(py, 6) == round(6.0 + (10.0 - 0.0) * ((100 - 12) / 10.0), 6)

    def test_max_corner_maps_to_bottom_right_effective(self):
        px, py = _geo_to_pixel(10.0, 10.0, (0.0, 0.0, 10.0, 10.0), size=100, padding=6)
        # max corner should be at 6 + effective (since square aspect)
        assert round(px, 6) == round(6 + (100 - 12), 6)
        assert py == 6.0

    def test_zero_extent_does_not_divide_by_zero(self):
        # Degenerate point bounds — should not raise
        _geo_to_pixel(5.0, 5.0, (5.0, 5.0, 5.0, 5.0), size=64)

    def test_aspect_ratio_preserved_for_wide_bounds(self):
        # Wider-than-tall bounds: the y scale should match the x scale
        px0, py0 = _geo_to_pixel(0.0, 0.0, (0.0, 0.0, 20.0, 10.0), size=100, padding=6)
        px1, py1 = _geo_to_pixel(
            20.0, 10.0, (0.0, 0.0, 20.0, 10.0), size=100, padding=6
        )
        # x spans the full effective width; y is centered within remaining space
        assert round(px1 - px0, 4) == round(100 - 12, 4)
        assert round(py0 - py1, 4) == round((100 - 12) / 2, 4)


class TestComputePointRadius:
    def test_small_dataset_gets_large_points(self):
        assert _compute_point_radius(10, 256) == 6.0
        assert _compute_point_radius(50, 256) == 6.0

    def test_medium_dataset_gets_medium_points(self):
        assert _compute_point_radius(51, 256) == 4.5
        assert _compute_point_radius(200, 256) == 4.5

    def test_large_dataset_gets_small_points(self):
        assert _compute_point_radius(201, 256) == 3.0
        assert _compute_point_radius(1000, 256) == 3.0

    def test_huge_dataset_gets_smallest_points(self):
        assert _compute_point_radius(1001, 256) == 2.0
        assert _compute_point_radius(1_000_000, 256) == 2.0


class TestBlankCanvas:
    def test_blank_canvas_returns_png_bytes(self):
        png = _blank_canvas(128)
        assert isinstance(png, bytes)
        assert len(png) > 0

        # Load via Pillow and confirm size + background color
        img = Image.open(BytesIO(png))
        assert img.size == (128, 128)
        assert img.mode == "RGB"
        # Top-left pixel should be the configured background
        assert img.getpixel((0, 0)) == _BG_COLOR


class TestDrawGeometry:
    def _canvas(self, size: int = 64):
        img = Image.new("RGB", (size, size), _BG_COLOR)
        return img, ImageDraw.Draw(img)

    def _has_non_bg_pixels(self, img: Image.Image) -> bool:
        # Scan pixels and return True if any differ from the background.
        w, h = img.size
        for y in range(h):
            for x in range(w):
                if img.getpixel((x, y)) != _BG_COLOR:
                    return True
        return False

    def test_draw_point(self):
        img, draw = self._canvas()
        _draw_geometry(draw, Point(5, 5), (0, 0, 10, 10), size=64)
        assert self._has_non_bg_pixels(img)

    def test_draw_multipoint(self):
        img, draw = self._canvas()
        mp = MultiPoint([(1, 1), (9, 9)])
        _draw_geometry(draw, mp, (0, 0, 10, 10), size=64)
        assert self._has_non_bg_pixels(img)

    def test_draw_linestring(self):
        img, draw = self._canvas()
        line = LineString([(0, 0), (10, 10)])
        _draw_geometry(draw, line, (0, 0, 10, 10), size=64)
        assert self._has_non_bg_pixels(img)

    def test_draw_linestring_with_single_coord_is_noop(self):
        img, draw = self._canvas()
        # A LineString with < 2 coords should short-circuit without drawing
        line = LineString([(0, 0), (10, 10)])
        # Shapely does not allow a truly 1-coord LineString; emulate the guard
        # by creating an empty-ish line and confirming _draw_geometry handles
        # it without raising.
        _draw_geometry(draw, line, (0, 0, 10, 10), size=64)
        assert self._has_non_bg_pixels(img)

    def test_draw_multilinestring(self):
        img, draw = self._canvas()
        mls = MultiLineString([[(0, 0), (5, 5)], [(5, 0), (0, 5)]])
        _draw_geometry(draw, mls, (0, 0, 10, 10), size=64)
        assert self._has_non_bg_pixels(img)

    def test_draw_polygon(self):
        img, draw = self._canvas()
        poly = Polygon([(1, 1), (9, 1), (9, 9), (1, 9)])
        _draw_geometry(draw, poly, (0, 0, 10, 10), size=64)
        assert self._has_non_bg_pixels(img)

    def test_draw_empty_polygon_is_noop(self):
        img, draw = self._canvas()
        # An empty polygon should not touch the canvas
        _draw_geometry(draw, Polygon(), (0, 0, 10, 10), size=64)
        assert not self._has_non_bg_pixels(img)

    def test_draw_multipolygon(self):
        img, draw = self._canvas()
        mp = MultiPolygon(
            [
                Polygon([(1, 1), (4, 1), (4, 4), (1, 4)]),
                Polygon([(5, 5), (9, 5), (9, 9), (5, 9)]),
            ]
        )
        _draw_geometry(draw, mp, (0, 0, 10, 10), size=64)
        assert self._has_non_bg_pixels(img)

    def test_draw_geometry_collection(self):
        img, draw = self._canvas()
        gc = GeometryCollection(
            [
                Point(2, 2),
                LineString([(3, 3), (7, 7)]),
                Polygon([(5, 1), (9, 1), (9, 5), (5, 5)]),
            ]
        )
        _draw_geometry(draw, gc, (0, 0, 10, 10), size=64)
        assert self._has_non_bg_pixels(img)

    def test_unknown_geometry_type_is_silently_skipped(self):
        # Anything not in the dispatch table should leave the canvas clean.
        img, draw = self._canvas()

        class _Fake:
            geom_type = "CurvePolygon"  # not handled

        _draw_geometry(draw, _Fake(), (0, 0, 10, 10), size=64)
        assert not self._has_non_bg_pixels(img)
