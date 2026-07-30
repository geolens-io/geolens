"""Antimeridian handling in the raster pipeline (#887).

Three sites, one seam:

1. ``processing/raster/cog.py`` — ``extract_raster_metadata`` folded the
   reprojected WGS84 bounds into a single hand-built ``POLYGON`` ring. GDAL
   already reports a seam-crossing footprint as ``west > east``, so that ring
   was the *complement*: a Pacific COG spanning 175E..175W registered a valid
   350°-wide rectangle covering 7000 deg² of the wrong side of the world
   instead of its real 200.
2. ``processing/raster/vrt.py`` — both builders took ``min(left)`` /
   ``max(right)`` across sources, so a 10°-wide mosaic straddling the seam was
   allocated 360° wide (3600 x 50 px instead of 100 x 50) with every source at
   the wrong ``dst_x_off``. ``gdalbuildvrt`` is the production builder and does
   the same thing, so the correction is applied to *its* output — see
   ``TestSeamFrameRewrite``.
3. ``processing/tiles/router.py`` — the user-visible symptom. Source maxzoom is
   derived from extent width when the COG has no recorded resolution, so a
   seam-crossing raster measured 36x too wide, understated its own resolution,
   and stopped rendering as the user zoomed in.

The DB-backed tests need Postgres (``docker compose up -d --wait db``); the rest
are pure rasterio/XML unit tests. Any test here that commits a seam-crossing
extent MUST take ``clean_tables`` — see ``TestRasterTokenAcrossTheSeam``.
"""

import io
import math
import shutil
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from xml.etree.ElementTree import parse as parse_vrt

import numpy as np
import pytest
import rasterio
from httpx import AsyncClient
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import transform as warp_transform
from shapely import wkt as shapely_wkt
from sqlalchemy import func, select

from app.core.config import settings
from app.core.geo import (
    LON_EPSILON_DEGREES,
    bbox_to_extent_wkt,
    extent_lon_span,
    extent_to_bbox,
)
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.raster.cog import extract_raster_metadata
from app.processing.raster.models import RasterAsset
from app.processing.raster import vrt as vrt_module
from app.processing.raster.vrt import (
    _seam_frame_origin,
    _write_python_vrt,
    build_vrt,
    is_attacker_controllable_source,
    shift_vrt_longitude_frame,
    sources_seam_frame_origin,
)
from app.processing.raster.vrt_rewrite import rewrite_vrt_sources
from app.processing.tiles.router import _raster_maxzoom_from_metadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WGS84 = CRS.from_epsg(4326)
# EPSG:3832 — WGS 84 / PDC Mercator, central meridian 150E. The canonical
# Pacific-centred projection: its easting runs continuously across ±180.
PDC = CRS.from_epsg(3832)
WEB_MERCATOR_HALF_WORLD_M = 20037508.342789244


def _write_tif(
    path: Path,
    *,
    epsg: int | None,
    bounds: tuple[float, float, float, float],
    width: int = 64,
    height: int = 64,
    nodata: float | None = None,
    fill: int = 0,
    mask: bool = False,
) -> str:
    """Write a synthetic single-band GeoTIFF at the given native bounds."""
    profile = {
        "driver": "GTiff",
        "dtype": "uint8",
        "width": width,
        "height": height,
        "count": 1,
        "transform": from_bounds(*bounds, width, height),
    }
    if epsg is not None:
        profile["crs"] = CRS.from_epsg(epsg)
    if nodata is not None:
        profile["nodata"] = nodata

    buf = io.BytesIO()
    with MemoryFile() as mem:
        with mem.open(**profile) as ds:
            ds.write(np.full((height, width), fill, dtype="uint8"), 1)
            if mask:
                band_mask = np.full((height, width), 255, dtype="uint8")
                band_mask[:, : width // 2] = 0
                ds.write_mask(band_mask)
        buf.write(mem.read())
    path.write_bytes(buf.getvalue())
    return str(path)


def _project(epsg: int, lonlat_bounds: tuple[float, float, float, float]):
    """Project a lon/lat rectangle's corners into ``epsg``'s own units.

    The west corner is transformed first so a seam-crossing rectangle keeps its
    real (continuous) easting order in a Pacific-centred CRS.
    """
    west, south, east, north = lonlat_bounds
    xs, ys = warp_transform(WGS84, CRS.from_epsg(epsg), [west, east], [south, north])
    return (xs[0], ys[0], xs[1], ys[1])


def _dst_x_offs(vrt_path: str) -> list[float]:
    """Destination x offsets — float, because they are legitimately fractional.

    Both writers keep sub-pixel offsets (fix(#887)), so this must not coerce to
    int; `50.0 == 50` keeps whole-pixel assertions readable.
    """
    root = parse_vrt(vrt_path).getroot()
    return [float(d.get("xOff")) for d in root.iter("DstRect")]


def _vrt_geotransform(vrt_path: str) -> list[float]:
    root = parse_vrt(vrt_path).getroot()
    return [float(v) for v in root.find("GeoTransform").text.split(",")]


def _vrt_size(vrt_path: str) -> tuple[int, int]:
    root = parse_vrt(vrt_path).getroot()
    return int(root.get("rasterXSize")), int(root.get("rasterYSize"))


# ---------------------------------------------------------------------------
# Site 1: extract_raster_metadata / bbox_wkt
# ---------------------------------------------------------------------------


class TestCogExtentFold:
    def test_pacific_cog_registers_two_ring_extent(self, tmp_path):
        """A 3832 COG spanning 175E..175W registers its real 10° footprint.

        The pre-fix ring covered 7000 deg² between 175W and 175E — a valid
        rectangle that does not even contain the data it describes.
        """
        tif = _write_tif(
            tmp_path / "pacific.tif",
            epsg=3832,
            bounds=_project(3832, (175.0, -10.0, -175.0, 10.0)),
        )
        meta = extract_raster_metadata(tif)

        west, south, east, north = meta["bounds_wgs84"]
        assert west == pytest.approx(175.0)
        assert east == pytest.approx(-175.0)
        assert west > east, "a seam-crossing footprint must report west > east"
        assert (south, north) == (pytest.approx(-10.0), pytest.approx(10.0))

        geom = shapely_wkt.loads(meta["bbox_wkt"])
        assert geom.geom_type == "MultiPolygon"
        assert len(geom.geoms) == 2
        assert geom.is_valid
        # 10 deg of longitude x 20 deg of latitude. The bug produced 350 x 20.
        assert geom.area == pytest.approx(200.0, rel=1e-6)

    def test_pacific_cog_extent_reads_back_as_west_east(self, tmp_path):
        """The stored WKT round-trips through ``extent_to_bbox`` unchanged.

        This is the #901 contract: the two rings must share one latitude band or
        the reader degrades to an over-broad -180..180.
        """
        from geoalchemy2.shape import from_shape

        tif = _write_tif(
            tmp_path / "pacific.tif",
            epsg=3832,
            bounds=_project(3832, (175.0, -10.0, -175.0, 10.0)),
        )
        meta = extract_raster_metadata(tif)
        extent = from_shape(shapely_wkt.loads(meta["bbox_wkt"]), srid=4326)

        bbox = extent_to_bbox(extent)
        assert bbox[0] == pytest.approx(175.0)
        assert bbox[2] == pytest.approx(-175.0)
        assert extent_lon_span(extent) == pytest.approx(10.0)

    def test_global_web_mercator_raster_extent_unchanged(self, tmp_path):
        """Regression guard: a genuinely global raster stays -180..180."""
        half = WEB_MERCATOR_HALF_WORLD_M
        tif = _write_tif(
            tmp_path / "global3857.tif",
            epsg=3857,
            bounds=(-half, -half, half, half),
        )
        meta = extract_raster_metadata(tif)

        west, _, east, _ = meta["bounds_wgs84"]
        assert west == pytest.approx(-180.0)
        assert east == pytest.approx(180.0)

        geom = shapely_wkt.loads(meta["bbox_wkt"])
        assert geom.geom_type == "Polygon"
        assert geom.bounds[0] == pytest.approx(-180.0)
        assert geom.bounds[2] == pytest.approx(180.0)

    def test_global_pacific_raster_records_the_whole_world(self, tmp_path):
        """A global 3832 raster is 360° wide, not a zero-area line at lon -30.

        Its left and right edges land on the *same* meridian, so GDAL can only
        report a zero-width longitude range for it, and the pre-fix ring
        recorded the globe as a 0 deg² sliver.
        """
        half = WEB_MERCATOR_HALF_WORLD_M
        tif = _write_tif(
            tmp_path / "global3832.tif",
            epsg=3832,
            bounds=(-half, -8_000_000.0, half, 8_000_000.0),
        )
        meta = extract_raster_metadata(tif)

        west, south, east, north = meta["bounds_wgs84"]
        assert west == pytest.approx(-180.0)
        assert east == pytest.approx(180.0)

        geom = shapely_wkt.loads(meta["bbox_wkt"])
        assert geom.geom_type == "Polygon"
        assert geom.area == pytest.approx(360.0 * (north - south), rel=1e-6)
        assert geom.area > 0.0

    def test_pacific_sliver_is_not_inflated_to_the_globe(self, tmp_path):
        """Near miss for the degenerate-range repair: a 2 m-wide 3832 raster.

        Differs from the global fixture in exactly one axis — the same CRS, the
        same latitude band, only the easting width changes. A span-only guard
        would read the near-zero longitude range as a wrap.
        """
        tif = _write_tif(
            tmp_path / "sliver.tif",
            epsg=3832,
            bounds=(-1.0, -8_000_000.0, 1.0, 8_000_000.0),
        )
        meta = extract_raster_metadata(tif)

        west, _, east, _ = meta["bounds_wgs84"]
        assert west == pytest.approx(150.0, abs=1e-4)
        assert east == pytest.approx(150.0, abs=1e-4)
        geom = shapely_wkt.loads(meta["bbox_wkt"])
        assert geom.geom_type == "Polygon"
        assert geom.bounds[0] > 149.0, "a sliver must not widen to the whole world"

    @pytest.mark.parametrize(
        "label,epsg,lonlat",
        [
            # Each of these is 10 deg wide over the same latitude band as the
            # crossing fixture above: only the longitude POSITION differs, so a
            # miss here is a real guard failure and not a fixture difference.
            ("ends flush at +180", 3857, (170.0, -10.0, 180.0, 10.0)),
            ("ends flush at +180 (pacific crs)", 3832, (170.0, -10.0, 180.0, 10.0)),
            ("starts flush at -180", 3857, (-180.0, -10.0, -170.0, 10.0)),
            ("prime-meridian straddle", 3857, (-5.0, -10.0, 5.0, 10.0)),
        ],
    )
    def test_near_miss_footprints_stay_single_ring(self, tmp_path, label, epsg, lonlat):
        tif = _write_tif(
            tmp_path / f"{abs(hash(label))}.tif",
            epsg=epsg,
            bounds=_project(epsg, lonlat),
        )
        meta = extract_raster_metadata(tif)

        west, _, east, _ = meta["bounds_wgs84"]
        assert west < east, f"{label}: must stay monotonic"
        assert west == pytest.approx(lonlat[0], abs=1e-6)
        assert east == pytest.approx(lonlat[2], abs=1e-6)

        geom = shapely_wkt.loads(meta["bbox_wkt"])
        assert geom.geom_type == "Polygon", f"{label}: no seam split expected"
        assert geom.area == pytest.approx(200.0, rel=1e-6)

    @pytest.mark.parametrize(
        "label,lonlat,expect_split",
        [
            # A 180-degree-wide footprint is the exact boundary of the "wider
            # than 180" guard and must not be re-framed.
            ("exactly 180 wide", (-10.0, -10.0, 170.0, 10.0), False),
            ("global", (-180.0, -90.0, 180.0, 90.0), False),
            # 0..360-domain source, which is what the seam-aware VRT builder
            # emits for a straddling mosaic.
            ("0..360 domain", (175.0, -10.0, 185.0, 10.0), True),
            ("below -180 domain", (-185.0, -10.0, -175.0, 10.0), True),
        ],
    )
    def test_geographic_source_longitudes_are_folded(
        self, tmp_path, label, lonlat, expect_split
    ):
        tif = _write_tif(
            tmp_path / f"geo{abs(hash(label))}.tif", epsg=4326, bounds=lonlat
        )
        meta = extract_raster_metadata(tif)
        geom = shapely_wkt.loads(meta["bbox_wkt"])

        if expect_split:
            assert geom.geom_type == "MultiPolygon", f"{label}: expected two rings"
            assert len(geom.geoms) == 2
            assert geom.area == pytest.approx(200.0, rel=1e-6)
            assert meta["bounds_wgs84"][0] > meta["bounds_wgs84"][2]
        else:
            assert geom.geom_type == "Polygon", f"{label}: expected one ring"
            assert meta["bounds_wgs84"][0] < meta["bounds_wgs84"][2]
            expected_area = (lonlat[2] - lonlat[0]) * (lonlat[3] - lonlat[1])
            assert geom.area == pytest.approx(expected_area, rel=1e-6)

    def test_source_starting_exactly_at_180_needs_only_one_ring(self, tmp_path):
        """A 180..190 raster is entirely west of the seam once folded.

        The fold reports ``west > east`` (``wrap_longitude`` keeps +180 as +180,
        per #886), but the ``180..180`` half has zero width, so
        ``bbox_to_extent_wkt`` drops it and emits the ``-180..-170`` ring alone.
        Asserting the area is what distinguishes that from silently losing half
        the footprint.
        """
        tif = _write_tif(
            tmp_path / "at180.tif", epsg=4326, bounds=(180.0, -10.0, 190.0, 10.0)
        )
        meta = extract_raster_metadata(tif)

        assert meta["bounds_wgs84"] == (180.0, -10.0, -170.0, 10.0)
        geom = shapely_wkt.loads(meta["bbox_wkt"])
        assert geom.geom_type == "Polygon"
        assert geom.is_valid
        assert geom.bounds[0] == pytest.approx(-180.0)
        assert geom.bounds[2] == pytest.approx(-170.0)
        assert geom.area == pytest.approx(200.0, rel=1e-6)

    def test_crs_less_raster_bounds_are_not_folded(self, tmp_path):
        """Without a CRS the bounds are not longitudes; leave them alone.

        A pixel-space right edge past 360 must not be reinterpreted as a wrap of
        the world.
        """
        tif = _write_tif(
            tmp_path / "nocrs.tif", epsg=None, bounds=(0.0, 0.0, 4000.0, 2000.0)
        )
        meta = extract_raster_metadata(tif)

        assert meta["bounds_wgs84"] == (0.0, 0.0, 4000.0, 2000.0)


# ---------------------------------------------------------------------------
# Site 2: _write_python_vrt mosaic geometry
# ---------------------------------------------------------------------------


class TestSeamFrameOrigin:
    """The frame chooser's two guards, at their boundaries."""

    @pytest.mark.parametrize(
        "label,spans,expected",
        [
            ("seam-adjacent pair", [(175.0, 180.0), (-180.0, -175.0)], 175.0),
            ("seam pair with a gap", [(160.0, 170.0), (-170.0, -160.0)], 160.0),
            (
                "three sources, widest gap in the Atlantic",
                [(100.0, 170.0), (-170.0, -100.0), (-50.0, -40.0)],
                100.0,
            ),
            # Guard 1: nothing at or below 180 deg wide can be improved.
            ("exactly 180 wide", [(-10.0, 80.0), (80.0, 170.0)], None),
            ("ends flush at +180", [(170.0, 175.0), (175.0, 180.0)], None),
            ("narrow pair", [(10.0, 15.0), (15.0, 20.0)], None),
            # Guard 2: over 180 wide, but no frame is strictly narrower.
            ("185 wide, contiguous", [(-10.0, 85.0), (85.0, 175.0)], None),
            (
                "global tiling",
                [(-180.0 + 10 * i, -170.0 + 10 * i) for i in range(36)],
                None,
            ),
        ],
    )
    def test_guard_boundaries(self, label, spans, expected):
        assert _seam_frame_origin(spans) == expected, label

    def test_global_mosaic_on_non_round_boundaries_is_not_reframed(self):
        """Float noise must not win the "is the shifted hull narrower" contest.

        ``left + 360`` is not bit-exact for an arbitrary mantissa, so a global
        tiling whose boundaries are not round numbers can measure fractionally
        narrower in a shifted frame than in the plain one. With a bare ``<`` this
        exact fixture re-frames a *global* mosaic to origin 160.3; the margin is
        what keeps it at ``None``. Same trap #886/#928 hit in the rollup folds.
        """
        step = 360.0 / 36
        spans = [(-179.7 + step * i, -179.7 + step * (i + 1)) for i in range(36)]

        assert _seam_frame_origin(spans) is None

    @pytest.mark.parametrize(
        "spans,expected",
        [
            ([(175.0, 180.0), (-180.0, -175.0)], 175.0),
            ([(175.123456789, 180.0), (-180.0, -175.987654321)], 175.123456789),
        ],
    )
    def test_margin_does_not_suppress_a_real_crossing(self, spans, expected):
        """The margin is 0.1 mm — it must not swallow a genuine 5° seam pair."""
        assert _seam_frame_origin(spans) == pytest.approx(expected)

    def test_shifted_hull_is_the_tightest_available(self):
        """The chosen origin must minimise the hull, not merely improve on it."""
        spans = [(100.0, 170.0), (-170.0, -100.0), (-50.0, -40.0)]
        origin = _seam_frame_origin(spans)
        hull = max(r + 360.0 if left < origin else r for left, r in spans) - origin
        assert hull == pytest.approx(220.0)


class TestSeamStraddlingVrt:
    def _tiles(self, tmp_path, lon_pairs, *, epsg=4326, lat=(0.0, 5.0)):
        return [
            _write_tif(
                tmp_path / f"tile{i}.tif",
                epsg=epsg,
                bounds=(west, lat[0], east, lat[1]),
                width=50,
                height=50,
            )
            for i, (west, east) in enumerate(lon_pairs)
        ]

    def test_mosaic_is_sized_to_the_real_footprint(self, tmp_path):
        """Two 5° tiles either side of ±180 allocate 100 px, not 3600.

        Pre-fix: rasterXSize 3600 (a full 360° at 0.1°/px) with the eastern
        source parked at ``dst_x_off`` 3550 — an enormous, misregistered mosaic
        with a 350° hole in the middle.
        """
        sources = self._tiles(tmp_path, [(175.0, 180.0), (-180.0, -175.0)])
        out = _write_python_vrt(sources, str(tmp_path / "seam.vrt"), "finest")

        assert _vrt_size(out) == (100, 50)
        gt = _vrt_geotransform(out)
        assert gt[0] == pytest.approx(175.0), "frame origin must be the western tile"
        assert gt[1] == pytest.approx(0.1)
        assert _dst_x_offs(out) == [0, 50]

        with rasterio.open(out) as ds:
            assert ds.bounds.left == pytest.approx(175.0)
            assert ds.bounds.right == pytest.approx(185.0)

    def test_seam_mosaic_extent_is_two_rings_end_to_end(self, tmp_path):
        """The VRT the builder writes reads back as a two-ring 10° extent."""
        sources = self._tiles(tmp_path, [(175.0, 180.0), (-180.0, -175.0)])
        out = _write_python_vrt(sources, str(tmp_path / "seam.vrt"), "finest")

        meta = extract_raster_metadata(out)
        assert meta["bounds_wgs84"][0] == pytest.approx(175.0)
        assert meta["bounds_wgs84"][2] == pytest.approx(-175.0)

        geom = shapely_wkt.loads(meta["bbox_wkt"])
        assert geom.geom_type == "MultiPolygon"
        assert geom.area == pytest.approx(50.0, rel=1e-6)  # 10 deg x 5 deg

    def test_non_crossing_mosaic_geometry_is_unchanged(self, tmp_path):
        """Control: the same two 5° tiles, same latitude band, moved off the seam."""
        sources = self._tiles(tmp_path, [(10.0, 15.0), (15.0, 20.0)])
        out = _write_python_vrt(sources, str(tmp_path / "plain.vrt"), "finest")

        assert _vrt_size(out) == (100, 50)
        assert _vrt_geotransform(out)[0] == pytest.approx(10.0)
        assert _dst_x_offs(out) == [0, 50]

    def test_global_mosaic_is_not_reframed(self, tmp_path):
        """A mosaic that really is -180..180 keeps its origin and its width."""
        lon_pairs = [(-180.0 + 10 * i, -170.0 + 10 * i) for i in range(36)]
        sources = self._tiles(tmp_path, lon_pairs)
        out = _write_python_vrt(sources, str(tmp_path / "global.vrt"), "finest")

        assert _vrt_geotransform(out)[0] == pytest.approx(-180.0)
        assert _vrt_size(out)[0] == 36 * 50
        assert _dst_x_offs(out) == [50 * i for i in range(36)]

    def test_projected_sources_are_never_reframed(self, tmp_path):
        """Metres are not degrees.

        Two EPSG:3857 tiles at opposite ends of the world span 4e7 *metres*,
        which clears a bare ">180" guard trivially; a +360 shift would move a
        source by 360 m. The CRS gate is what stops it.
        """
        half = WEB_MERCATOR_HALF_WORLD_M
        sources = [
            _write_tif(
                tmp_path / "west3857.tif",
                epsg=3857,
                bounds=(-half, 0.0, -half + 1_000_000.0, 1_000_000.0),
                width=50,
                height=50,
            ),
            _write_tif(
                tmp_path / "east3857.tif",
                epsg=3857,
                bounds=(half - 1_000_000.0, 0.0, half, 1_000_000.0),
                width=50,
                height=50,
            ),
        ]
        out = _write_python_vrt(sources, str(tmp_path / "proj.vrt"), "finest")

        assert _vrt_geotransform(out)[0] == pytest.approx(-half)
        # 4.0075e7 m of easting at 2e4 m/px. The eastern tile starts 1953.75 px
        # in and keeps that fraction — these sources are off the output grid, and
        # rounding to 1954 would slide them a quarter pixel (fix(#887)).
        assert _vrt_size(out) == (2004, 50)
        offsets = _dst_x_offs(out)
        assert offsets[0] == 0
        assert offsets[1] == pytest.approx(1953.7508342789, abs=1e-6)

    def test_fallback_keeps_fractional_geometry_like_the_rewrite(self, tmp_path):
        """The fallback writer obeys the same geometry rule as the rewrite.

        Both writers now go through ``_offset_text`` and ``_containing_pixels``.
        Before that, this fallback rounded a source needing ``xOff`` 248.5 down
        to 248 and sized the 298.5-pixel hull at 298 — sliding the eastern tile
        half a pixel and clipping the edge. It is unreachable in the shipped
        worker (the image installs ``gdal-bin``), but two writers disagreeing
        about one rule is what produced the first regression in this PR.
        """
        sources = [
            _write_tif(
                tmp_path / "w.tif",
                epsg=4326,
                bounds=(175.03, 0.0, 180.0, 2.0),
                width=50,
                height=20,
            ),
            _write_tif(
                tmp_path / "e.tif",
                epsg=4326,
                bounds=(-180.0, 0.0, -179.0, 2.0),
                width=50,
                height=20,
            ),
        ]

        out = _write_python_vrt(sources, str(tmp_path / "frac.vrt"), "finest")

        root = parse_vrt(out).getroot()
        rects = [
            (float(d.get("xOff")), float(d.get("xSize"))) for d in root.iter("DstRect")
        ]
        width = int(root.get("rasterXSize"))

        assert rects[1][0] == pytest.approx(248.5), (
            "the eastern tile must keep its half-pixel offset"
        )
        far_edge = max(off + size for off, size in rects)
        assert far_edge == pytest.approx(298.5)
        assert width == 299, "the hull must be rounded UP to contain 298.5 px"

    def test_band_stack_seam_sources_share_the_shifted_frame(self, tmp_path):
        """``-separate`` band stacks re-frame identically to a mosaic."""
        sources = self._tiles(tmp_path, [(175.0, 180.0), (-180.0, -175.0)])
        out = _write_python_vrt(
            sources, str(tmp_path / "stack.vrt"), "finest", separate=True
        )

        assert _vrt_size(out) == (100, 50)
        assert _vrt_geotransform(out)[0] == pytest.approx(175.0)
        assert _dst_x_offs(out) == [0, 50]


# ---------------------------------------------------------------------------
# Site 2, the path production actually takes
# ---------------------------------------------------------------------------


class TestSourcesSeamFrameOrigin:
    """The build-time probe, on the inputs that must not trip it."""

    def test_geographic_seam_pair_is_detected(self, tmp_path):
        sources = [
            _write_tif(tmp_path / "a.tif", epsg=4326, bounds=(175.0, 0.0, 180.0, 5.0)),
            _write_tif(
                tmp_path / "b.tif", epsg=4326, bounds=(-180.0, 0.0, -175.0, 5.0)
            ),
        ]

        assert sources_seam_frame_origin(sources) == pytest.approx(175.0)

    def test_off_seam_pair_is_not_detected(self, tmp_path):
        sources = [
            _write_tif(tmp_path / "a.tif", epsg=4326, bounds=(10.0, 0.0, 15.0, 5.0)),
            _write_tif(tmp_path / "b.tif", epsg=4326, bounds=(15.0, 0.0, 20.0, 5.0)),
        ]

        assert sources_seam_frame_origin(sources) is None

    def test_one_crs_less_source_disables_detection(self, tmp_path):
        """Unknown units means unknown wrap: refuse rather than guess."""
        sources = [
            _write_tif(tmp_path / "a.tif", epsg=4326, bounds=(175.0, 0.0, 180.0, 5.0)),
            _write_tif(
                tmp_path / "b.tif", epsg=None, bounds=(-180.0, 0.0, -175.0, 5.0)
            ),
        ]

        assert sources_seam_frame_origin(sources) is None

    def test_projected_sources_are_not_detected(self, tmp_path):
        """Metres are not degrees — a 4e7 m hull must not read as a seam crossing."""
        half = WEB_MERCATOR_HALF_WORLD_M
        sources = [
            _write_tif(
                tmp_path / "w.tif",
                epsg=3857,
                bounds=(-half, 0.0, -half + 1_000_000.0, 1_000_000.0),
            ),
            _write_tif(
                tmp_path / "e.tif",
                epsg=3857,
                bounds=(half - 1_000_000.0, 0.0, half, 1_000_000.0),
            ),
        ]

        assert sources_seam_frame_origin(sources) is None

    def test_unopenable_source_is_not_detected(self, tmp_path):
        bogus = tmp_path / "broken.tif"
        bogus.write_bytes(b"not a tiff")

        assert sources_seam_frame_origin([str(bogus)]) is None

    def test_remote_source_is_never_fetched_by_the_probe(self, tmp_path):
        """AGENTS.md Rule 2: the probe must not fetch a caller-supplied URL.

        This runs *ahead* of ``gdalbuildvrt``, so for a remotely imported STAC
        asset — whose URL ``resolve_open_path`` passes through unchanged — it
        would be the first thing to fetch it, and a URL that was safe at import
        time but now redirects to a private address would be followed.

        Asserting "the redirect was not followed" would be too weak, because no
        GDAL setting can deliver that: measured on GDAL 3.12.1,
        ``GDAL_HTTP_FOLLOWLOCATION`` is not a real config option
        (``Warning 1: Unknown configuration option``) and the 302 is followed
        with or without it, in-process and in the subprocess alike. So assert
        the strong property instead: **the host is never contacted at all.**
        A local server records every hit; the list must stay empty.
        """
        requested: list[str] = []

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
                requested.append(self.path)
                if self.path.startswith("/redirect"):
                    self.send_response(302)
                    self.send_header("Location", "/private.tif")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/tiff")
                self.end_headers()
                self.wfile.write(b"\x00" * 64)

            def do_HEAD(self):  # noqa: N802 (GDAL probes with HEAD first)
                self.do_GET()

            def log_message(self, *args):  # silence the default stderr spam
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/redirect.tif"
            assert sources_seam_frame_origin([url]) is None
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert requested == [], f"the probe fetched a caller-supplied URL: {requested}"

    @pytest.mark.parametrize(
        "path,controllable",
        [
            ("https://example.invalid/a.tif", True),
            ("http://example.invalid/a.tif", True),
            ("/vsicurl/https://example.invalid/a.tif", True),
            ("/vsicurl_streaming/https://example.invalid/a.tif", True),
            # Managed storage: bucket from settings, key already validated.
            ("/vsis3/bucket/rasters/a.tif", False),
            ("/vsiaz/container/rasters/a.tif", False),
            ("/srv/staging/rasters/a.tif", False),
        ],
    )
    def test_attacker_controllable_source_classification(self, path, controllable):
        assert is_attacker_controllable_source(path) is controllable

    def test_managed_storage_paths_are_still_probed(self, tmp_path):
        """The refusal is scoped to caller-supplied hosts, not to all I/O.

        Same seam pair as the positive case, just proving the local/managed path
        did not get caught by the URL guard.
        """
        sources = [
            _write_tif(tmp_path / "m1.tif", epsg=4326, bounds=(175.0, 0.0, 180.0, 5.0)),
            _write_tif(
                tmp_path / "m2.tif", epsg=4326, bounds=(-180.0, 0.0, -175.0, 5.0)
            ),
        ]

        assert sources_seam_frame_origin(sources) == pytest.approx(175.0)

    def test_grads_based_geographic_crs_is_not_detected(self, tmp_path):
        """``is_geographic`` is not the same as "wraps at ±180".

        EPSG:4807 (NTF Paris) is geographic with an angular unit of GRADS: a full
        turn is 400 and the seam sits at 200. The seam logic is written in
        degrees end to end, so a 195..200 / -200..-195 pair here would be shifted
        by 360 instead of 400 and land as a 40-grad hull instead of a 10-grad
        one. Refuse rather than corrupt it.
        """
        sources = [
            _write_tif(tmp_path / "g1.tif", epsg=4807, bounds=(195.0, 0.0, 200.0, 5.0)),
            _write_tif(
                tmp_path / "g2.tif", epsg=4807, bounds=(-200.0, 0.0, -195.0, 5.0)
            ),
        ]

        assert sources_seam_frame_origin(sources) is None

    def test_degree_based_non_4326_crs_is_still_detected(self, tmp_path):
        """Positive control for the unit gate: EPSG:4269 is degrees, so it counts.

        Differs from the grads fixture in exactly one axis — same longitudes,
        same latitudes, same seam crossing, only the CRS's angular unit changes.
        """
        sources = [
            _write_tif(tmp_path / "n1.tif", epsg=4269, bounds=(175.0, 0.0, 180.0, 5.0)),
            _write_tif(
                tmp_path / "n2.tif", epsg=4269, bounds=(-180.0, 0.0, -175.0, 5.0)
            ),
        ]

        assert sources_seam_frame_origin(sources) == pytest.approx(175.0)


# A gdalbuildvrt mosaic of two nodata-carrying tiles either side of ±180, as
# emitted verbatim by BOTH GDAL 3.10.3 (worker image) and GDAL 3.13.0 (local):
# 3600 x 50 px anchored at -180, western tile parked at dst_x_off 3550. Reproduced
# here so the rewrite is tested deterministically on machines with no GDAL CLI --
# the skipif-gated tests below drive the real binary where it exists.
_GDALBUILDVRT_SEAM_XML = """<VRTDataset rasterXSize="3600" rasterYSize="50">
  <SRS dataAxisToSRSAxisMapping="2,1">GEOGCS["WGS 84"]</SRS>
  <GeoTransform> -1.8000000000000000e+02,  1.0000000000000001e-01,  0.0000000000000000e+00,  5.0000000000000000e+00,  0.0000000000000000e+00, -1.0000000000000001e-01</GeoTransform>
  <VRTRasterBand dataType="Byte" band="1">
    <NoDataValue>0</NoDataValue>
    <ColorInterp>Gray</ColorInterp>
    <ComplexSource>
      <SourceFilename relativeToVRT="1">w.tif</SourceFilename>
      <SourceBand>1</SourceBand>
      <SrcRect xOff="0" yOff="0" xSize="50" ySize="50" />
      <DstRect xOff="3550" yOff="0" xSize="50" ySize="50" />
      <NODATA>0</NODATA>
    </ComplexSource>
    <ComplexSource>
      <SourceFilename relativeToVRT="1">e.tif</SourceFilename>
      <SourceBand>1</SourceBand>
      <SrcRect xOff="0" yOff="0" xSize="50" ySize="50" />
      <DstRect xOff="0" yOff="0" xSize="50" ySize="50" />
      <NODATA>0</NODATA>
    </ComplexSource>
    <MaskBand>
      <VRTRasterBand dataType="Byte">
        <ComplexSource>
          <SourceFilename relativeToVRT="1">w.tif</SourceFilename>
          <SourceBand>mask,1</SourceBand>
          <SrcRect xOff="0" yOff="0" xSize="50" ySize="50" />
          <DstRect xOff="3550" yOff="0" xSize="50" ySize="50" />
        </ComplexSource>
      </VRTRasterBand>
    </MaskBand>
  </VRTRasterBand>
</VRTDataset>
"""


class TestSeamFrameRewrite:
    """``_write_python_vrt`` is the fallback; ``gdalbuildvrt`` is what ships.

    The worker image installs ``gdal-bin``, so ``_build_vrt`` gets a working
    subprocess and the ``FileNotFoundError`` fallback never fires in a deployed
    worker. A test that calls ``_write_python_vrt`` directly therefore proves
    nothing about production, which is exactly how the first cut of this fix
    landed as dead code (codex P1 on #924).

    Rebuilding the seam case with the Python writer instead was the second wrong
    answer (codex P1 round 2): that writer emits bare ``SimpleSource`` elements,
    so nodata, colour interpretation and masks all vanish. GDAL keeps building
    the VRT; only the framing is rewritten afterwards.
    """

    def _tiles(self, tmp_path, lon_pairs, *, epsg=4326):
        return [
            _write_tif(
                tmp_path / f"p{i}.tif",
                epsg=epsg,
                bounds=(west, 0.0, east, 5.0),
                width=50,
                height=50,
            )
            for i, (west, east) in enumerate(lon_pairs)
        ]

    def _fake_gdalbuildvrt(self, xml: str):
        """A ``run_gdal`` stub that writes GDAL's own output for the seam pair."""

        def _run(cmd, **kwargs):
            # gdalbuildvrt's output path is the argument after "-resolution <mode>".
            Path(cmd[cmd.index("-resolution") + 2]).write_text(xml)
            return SimpleNamespace(returncode=0, stderr="")

        return _run

    def test_seam_frame_is_rewritten_in_gdalbuildvrt_output(
        self, tmp_path, monkeypatch
    ):
        """The geometry is corrected and every band tag survives untouched."""
        monkeypatch.setattr(
            vrt_module,
            "run_gdal",
            self._fake_gdalbuildvrt(_GDALBUILDVRT_SEAM_XML),
        )
        sources = self._tiles(tmp_path, [(175.0, 180.0), (-180.0, -175.0)])

        out = vrt_module._build_vrt(sources, str(tmp_path / "seam.vrt"), "finest")

        assert _vrt_size(out) == (100, 50)
        assert _vrt_geotransform(out)[0] == pytest.approx(175.0)
        # Band DstRects and the MaskBand's DstRect all move into the same frame.
        assert _dst_x_offs(out) == [0, 50, 0]

        xml = Path(out).read_text()
        for tag in (
            "NoDataValue",
            "ColorInterp",
            "ComplexSource",
            "NODATA",
            "MaskBand",
        ):
            assert f"<{tag}>" in xml, f"{tag} did not survive the rewrite"
        assert "SimpleSource" not in xml, "the rewrite must not rebuild the sources"

    def test_non_crossing_output_is_left_byte_identical(self, tmp_path, monkeypatch):
        """Negative probe: same tiles, same latitudes, moved off the seam.

        Only the longitude position differs, so anything that changes here is the
        rewrite firing when it must not.
        """
        monkeypatch.setattr(
            vrt_module,
            "run_gdal",
            self._fake_gdalbuildvrt(_GDALBUILDVRT_SEAM_XML),
        )
        sources = self._tiles(tmp_path, [(10.0, 15.0), (15.0, 20.0)])

        out = vrt_module._build_vrt(sources, str(tmp_path / "plain.vrt"), "finest")

        assert Path(out).read_text() == _GDALBUILDVRT_SEAM_XML

    def test_global_mosaic_output_is_left_alone(self, tmp_path, monkeypatch):
        """A genuinely global mosaic is not a seam crossing."""
        monkeypatch.setattr(
            vrt_module,
            "run_gdal",
            self._fake_gdalbuildvrt(_GDALBUILDVRT_SEAM_XML),
        )
        sources = self._tiles(
            tmp_path, [(-180.0 + 10 * i, -170.0 + 10 * i) for i in range(36)]
        )

        out = vrt_module._build_vrt(sources, str(tmp_path / "global.vrt"), "finest")

        assert Path(out).read_text() == _GDALBUILDVRT_SEAM_XML

    def test_band_stack_dispatch_also_rewrites(self, tmp_path, monkeypatch):
        """``build_vrt("band_stack", ...)`` reaches the rewrite too."""
        monkeypatch.setattr(
            vrt_module,
            "run_gdal",
            self._fake_gdalbuildvrt(_GDALBUILDVRT_SEAM_XML),
        )
        sources = self._tiles(tmp_path, [(175.0, 180.0), (-180.0, -175.0)])

        out = build_vrt("band_stack", sources, str(tmp_path / "stack.vrt"), "finest")

        assert _vrt_size(out) == (100, 50)
        assert _vrt_geotransform(out)[0] == pytest.approx(175.0)

    def test_missing_dstrect_fails_loudly(self, tmp_path):
        """Editing generated XML is version-sensitive, so assert the structure.

        A source with no ``DstRect`` covers the whole raster implicitly; shrinking
        the raster underneath it would silently restretch it. Raise instead —
        shipping a misregistered mosaic that looks fine is the one unacceptable
        outcome.
        """
        vrt = tmp_path / "no_dstrect.vrt"
        vrt.write_text(
            '<VRTDataset rasterXSize="3600" rasterYSize="50">'
            "<GeoTransform>-180.0, 0.1, 0.0, 5.0, 0.0, -0.1</GeoTransform>"
            '<VRTRasterBand dataType="Byte" band="1"><SimpleSource>'
            "<SourceFilename>w.tif</SourceFilename></SimpleSource>"
            "</VRTRasterBand></VRTDataset>"
        )

        with pytest.raises(RuntimeError, match="expected one DstRect per source"):
            shift_vrt_longitude_frame(str(vrt), 175.0)

    def test_missing_geotransform_fails_loudly(self, tmp_path):
        vrt = tmp_path / "no_gt.vrt"
        vrt.write_text('<VRTDataset rasterXSize="10" rasterYSize="10" />')

        with pytest.raises(RuntimeError, match="no GeoTransform"):
            shift_vrt_longitude_frame(str(vrt), 175.0)

    def test_fractional_offsets_stay_fractional(self, tmp_path):
        """Sub-pixel offsets must not be rounded to whole pixels.

        ``gdalbuildvrt`` emits fractional ``xOff`` whenever a source is not
        aligned to the chosen output grid — measured ``17751.5`` and ``349.51``
        on mixed-resolution mosaics. Rounding slides the source by up to half an
        output pixel and changes its resampling alignment.
        """
        vrt = tmp_path / "frac.vrt"
        vrt.write_text(
            '<VRTDataset rasterXSize="18000" rasterYSize="50">'
            "<GeoTransform> -1.8e+02, 2.0e-02, 0.0, 5.0, 0.0, -2.0e-02</GeoTransform>"
            '<VRTRasterBand dataType="Byte" band="1">'
            "<ComplexSource>"
            '<SrcRect xOff="0" yOff="0" xSize="50" ySize="50" />'
            '<DstRect xOff="17751.5" yOff="0" xSize="248.5" ySize="50" />'
            "</ComplexSource>"
            "<ComplexSource>"
            '<SrcRect xOff="0" yOff="0" xSize="50" ySize="50" />'
            '<DstRect xOff="0" yOff="0" xSize="50" ySize="50" />'
            "</ComplexSource>"
            "</VRTRasterBand></VRTDataset>"
        )

        shift_vrt_longitude_frame(str(vrt), 175.0)

        root = parse_vrt(str(vrt)).getroot()
        offsets = [d.get("xOff") for d in root.iter("DstRect")]
        # 17751.5 px at 0.02 deg puts the western source at 175.03; re-anchored
        # there it sits at 0, and the eastern source lands 248.5 px further on.
        assert offsets == ["0", "248.5"]
        assert float(offsets[1]) == pytest.approx(248.5)
        # ... and the raster has to be wide enough to hold it: 248.5 + 50 = 298.5
        # needs 299 px. 298 would leave the last half pixel outside the dataset.
        assert int(root.get("rasterXSize")) == 299

    def test_raster_width_contains_every_source(self, tmp_path):
        """The containment invariant, stated directly.

        A pixel-count assertion cannot catch an under-sized raster — a 50-pixel
        source still reads back as 50 pixels while its final half pixel is
        clipped — so assert the geometry instead. GDAL sizes its own mosaics the
        same way: measured ``max(xOff + xSize) = 298.5`` against
        ``rasterXSize = 299``.
        """
        vrt = tmp_path / "contain.vrt"
        vrt.write_text(
            '<VRTDataset rasterXSize="18000" rasterYSize="50">'
            "<GeoTransform> -1.8e+02, 2.0e-02, 0.0, 5.0, 0.0, -2.0e-02</GeoTransform>"
            '<VRTRasterBand dataType="Byte" band="1">'
            "<ComplexSource>"
            '<DstRect xOff="17751.5" yOff="0" xSize="248.5" ySize="50" />'
            "</ComplexSource>"
            "<ComplexSource>"
            '<DstRect xOff="0" yOff="0" xSize="50" ySize="50" />'
            "</ComplexSource>"
            "</VRTRasterBand></VRTDataset>"
        )

        shift_vrt_longitude_frame(str(vrt), 175.0)

        root = parse_vrt(str(vrt)).getroot()
        width = int(root.get("rasterXSize"))
        far_edge = max(
            float(d.get("xOff")) + float(d.get("xSize")) for d in root.iter("DstRect")
        )
        assert width >= far_edge, (
            f"raster {width} px clips a source ending at {far_edge}"
        )
        # And not over-allocated either — exactly the containing integer.
        assert width == 299

    @pytest.mark.parametrize("res_x", [0.02, 0.01666666666666667, 1.0 / 3.0, 0.007])
    @pytest.mark.parametrize(
        "lefts",
        [
            (175.001, -180.0),
            (175.123456789, -180.0),
            (174.99999999, -179.87654321),
            (170.3333333333, -175.6666666667),
            (179.9, -180.0, -179.4),
            (160.07, 170.07, -180.0, -170.0),
        ],
    )
    def test_reframing_invariants_hold_for_off_grid_mosaics(
        self, tmp_path, res_x, lefts
    ):
        """Property sweep over the whole re-framing path (#887).

        Every one of these mosaics straddles ±180 with edges and resolutions
        chosen to be awkward in binary, which is what makes `gdalbuildvrt` emit
        fractional offsets and what makes a reconstructed edge land a hair off
        its true value. Two invariants must survive all of them:

        1. the raster CONTAINS every source (``rasterXSize >= max(xOff+xSize)``);
        2. the sources are not left scattered across a world — the re-framed hull
           must be near the real footprint, not ~360°.

        This is the shape that caught the frame-chooser noise bug when
        example-based tests did not. A bare ``<`` at any of the six comparison
        sites in this path fails invariant 2 here.
        """
        widths = [4.0] * len(lefts)
        sources = [(left, left + w) for left, w in zip(lefts, widths, strict=True)]

        # What gdalbuildvrt emits: the plain min/max fold over -180..180.
        old_left = min(left for left, _ in sources)
        old_right = max(right for _, right in sources)
        plain_width = max(1, math.ceil(round((old_right - old_left) / res_x, 6)))
        rects = "".join(
            f'<ComplexSource><DstRect xOff="{(left - old_left) / res_x!r}" yOff="0" '
            f'xSize="{(right - left) / res_x!r}" ySize="10" /></ComplexSource>'
            for left, right in sources
        )
        vrt = tmp_path / f"prop_{abs(hash((res_x, lefts)))}.vrt"
        vrt.write_text(
            f'<VRTDataset rasterXSize="{plain_width}" rasterYSize="10">'
            f"<GeoTransform> {old_left!r}, {res_x!r}, 0.0, 5.0, 0.0, -{res_x!r}</GeoTransform>"
            f'<VRTRasterBand dataType="Byte" band="1">{rects}</VRTRasterBand>'
            "</VRTDataset>"
        )

        seam_origin = _seam_frame_origin(sources)
        assert seam_origin is not None, "fixture must straddle the seam"
        shift_vrt_longitude_frame(str(vrt), seam_origin)

        root = parse_vrt(str(vrt)).getroot()
        width = int(root.get("rasterXSize"))
        offsets = [
            (float(d.get("xOff")), float(d.get("xSize"))) for d in root.iter("DstRect")
        ]
        far_edge = max(off + size for off, size in offsets)

        assert width >= far_edge, (
            f"raster {width} px clips a source ending at {far_edge}"
        )
        assert min(off for off, _ in offsets) == pytest.approx(0.0, abs=1e-6), (
            "the frame must be anchored on a source"
        )
        # Recompute the expected hull independently, in the shifted frame, and
        # require the raster to match it to within a pixel. A loose "< 359°"
        # bound would pass a mosaic that is merely less broken than before; this
        # pins the actual footprint.
        shifted = [
            (left + 360.0, right + 360.0)
            if left < seam_origin - LON_EPSILON_DEGREES
            else (left, right)
            for left, right in sources
        ]
        expected_span = max(right for _, right in shifted) - min(
            left for left, _ in shifted
        )
        assert width * res_x == pytest.approx(expected_span, abs=2 * res_x), (
            f"re-framed hull is {width * res_x:.4f}°, expected {expected_span:.4f}° "
            "— the sources were left scattered across a world"
        )

    def test_whole_pixel_offsets_stay_integral(self, tmp_path):
        """The common case still reads like GDAL's own output, not ``50.0``.

        Rounding the width up must not inflate an exactly-aligned mosaic: 50 + 50
        is 100 pixels, not 101.
        """
        vrt = tmp_path / "whole.vrt"
        vrt.write_text(_GDALBUILDVRT_SEAM_XML)

        shift_vrt_longitude_frame(str(vrt), 175.0)

        root = parse_vrt(str(vrt)).getroot()
        assert [d.get("xOff") for d in root.iter("DstRect")] == ["0", "50", "0"]
        assert int(root.get("rasterXSize")) == 100

    def test_unopenable_source_is_left_to_gdalbuildvrt(self, tmp_path, monkeypatch):
        """The probe must never swallow a broken source's real error."""
        calls = []

        def _record(cmd, **kwargs):
            calls.append(cmd)
            return SimpleNamespace(returncode=1, stderr="not a recognized file format")

        monkeypatch.setattr(vrt_module, "run_gdal", _record)
        bogus = tmp_path / "broken.tif"
        bogus.write_bytes(b"not a tiff")

        with pytest.raises(RuntimeError, match="gdalbuildvrt failed"):
            vrt_module._build_vrt([str(bogus)], str(tmp_path / "x.vrt"), "finest")

        assert len(calls) == 1

    def test_bad_resolution_strategy_still_raises_first(self, tmp_path):
        """The KeyError contract holds ahead of any seam work."""
        sources = self._tiles(tmp_path, [(175.0, 180.0), (-180.0, -175.0)])

        with pytest.raises(KeyError):
            vrt_module._build_vrt(sources, str(tmp_path / "bad.vrt"), "sharpest")


@pytest.mark.skipif(
    shutil.which("gdalbuildvrt") is None,
    reason="needs the real gdalbuildvrt (present in the worker image)",
)
class TestSeamFrameRewriteAgainstRealGdal:
    """End-to-end against whatever GDAL is installed.

    Verified identical on GDAL 3.10.3 (the worker image) and 3.13.0 (local): the
    upstream defect, the XML shape the rewrite depends on, and the corrected
    result all match.
    """

    def _nodata_tile(self, path, *, bounds, value):
        return _write_tif(
            path, epsg=4326, bounds=bounds, width=50, height=50, nodata=0, fill=value
        )

    def test_upstream_still_gets_the_seam_wrong(self, tmp_path):
        """A test of the premise, not of our code.

        If a future GDAL learns to fold longitudes itself, this fails and the
        rewrite can be reconsidered.
        """
        sources = [
            self._nodata_tile(
                tmp_path / "w.tif", bounds=(175.0, 0.0, 180.0, 5.0), value=7
            ),
            self._nodata_tile(
                tmp_path / "e.tif", bounds=(-180.0, 0.0, -175.0, 5.0), value=9
            ),
        ]
        raw = str(tmp_path / "raw.vrt")
        result = subprocess.run(
            ["gdalbuildvrt", "-resolution", "highest", raw, *sources],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

        assert _vrt_size(raw) == (3600, 50), "gdalbuildvrt folded the seam itself"
        assert _vrt_geotransform(raw)[0] == pytest.approx(-180.0)
        assert 3550 in _dst_x_offs(raw)
        # And the structure the rewrite depends on is there.
        assert "<DstRect" in Path(raw).read_text()

    def test_nodata_and_pixels_survive_a_seam_build(self, tmp_path):
        """The assertion that would have caught the round-2 P1."""
        sources = [
            self._nodata_tile(
                tmp_path / "w.tif", bounds=(175.0, 0.0, 180.0, 5.0), value=7
            ),
            self._nodata_tile(
                tmp_path / "e.tif", bounds=(-180.0, 0.0, -175.0, 5.0), value=9
            ),
        ]

        out = vrt_module._build_vrt(sources, str(tmp_path / "seam.vrt"), "finest")

        with rasterio.open(out) as ds:
            assert (ds.width, ds.height) == (100, 50)
            assert ds.bounds.left == pytest.approx(175.0)
            assert ds.bounds.right == pytest.approx(185.0)
            assert ds.nodata == 0.0, "nodata must survive the seam build"
            assert ds.colorinterp[0].name == "gray"
            assert ds.mask_flag_enums[0][0].name == "nodata"
            band = ds.read(1)

        # Each tile lands on its own half, in the shifted frame.
        assert set(band[:, :50].ravel().tolist()) == {7}
        assert set(band[:, 50:].ravel().tolist()) == {9}

    def test_overlapping_fill_does_not_obscure_valid_pixels(self, tmp_path):
        """An all-nodata source laid last must not erase an earlier tile.

        Measured on the Python-writer route this replaces: these pixels read 0.
        """
        sources = [
            self._nodata_tile(
                tmp_path / "w.tif", bounds=(175.0, 0.0, 180.0, 5.0), value=7
            ),
            self._nodata_tile(
                tmp_path / "e.tif", bounds=(-180.0, 0.0, -175.0, 5.0), value=9
            ),
            # laid last, entirely fill, over the western tile's eastern half
            self._nodata_tile(
                tmp_path / "fill.tif", bounds=(177.5, 0.0, 180.0, 5.0), value=0
            ),
        ]

        out = vrt_module._build_vrt(sources, str(tmp_path / "ov.vrt"), "finest")

        with rasterio.open(out) as ds:
            band = ds.read(1)
            assert ds.nodata == 0.0
        # 177.5..180 is columns 25-49 of the 100-px hull anchored at 175.
        assert set(band[:, 25:50].ravel().tolist()) == {7}

    def test_masked_sources_keep_their_mask_band(self, tmp_path):
        sources = [
            _write_tif(
                tmp_path / "mw.tif",
                epsg=4326,
                bounds=(175.0, 0.0, 180.0, 5.0),
                width=50,
                height=50,
                mask=True,
            ),
            _write_tif(
                tmp_path / "me.tif",
                epsg=4326,
                bounds=(-180.0, 0.0, -175.0, 5.0),
                width=50,
                height=50,
                mask=True,
            ),
        ]

        out = vrt_module._build_vrt(sources, str(tmp_path / "mask.vrt"), "finest")

        assert "UseMaskBand" in Path(out).read_text()
        with rasterio.open(out) as ds:
            assert (ds.width, ds.height) == (100, 50)
            assert ds.mask_flag_enums[0][0].name == "per_dataset"

    def test_frame_origin_is_computed_not_taken_from_argv_order(self, tmp_path):
        """Three sources whose frame origin is the SECOND one on the command line.

        Catches a whole class of "just use the first source" errors: the origin is
        175 (``p1``), so the sources must land 2, 1, 3 across the hull, not in the
        order they were passed.
        """
        sources = [
            self._nodata_tile(
                tmp_path / "p0.tif", bounds=(-180.0, 0.0, -175.0, 5.0), value=1
            ),
            self._nodata_tile(
                tmp_path / "p1.tif", bounds=(175.0, 0.0, 180.0, 5.0), value=2
            ),
            self._nodata_tile(
                tmp_path / "p2.tif", bounds=(-175.0, 0.0, -170.0, 5.0), value=3
            ),
        ]

        out = vrt_module._build_vrt(sources, str(tmp_path / "three.vrt"), "finest")

        with rasterio.open(out) as ds:
            assert (ds.width, ds.height) == (150, 50)
            assert ds.bounds.left == pytest.approx(175.0)
            assert ds.bounds.right == pytest.approx(190.0)
            row = ds.read(1)[0]

        assert set(row[:50].tolist()) == {2}
        assert set(row[50:100].tolist()) == {1}
        assert set(row[100:].tolist()) == {3}

    def test_band_stack_keeps_per_band_nodata_across_the_seam(self, tmp_path):
        """``-separate`` through the real binary: each band keeps its own source."""
        sources = [
            self._nodata_tile(
                tmp_path / "bw.tif", bounds=(175.0, 0.0, 180.0, 5.0), value=7
            ),
            self._nodata_tile(
                tmp_path / "be.tif", bounds=(-180.0, 0.0, -175.0, 5.0), value=9
            ),
        ]

        out = build_vrt("band_stack", sources, str(tmp_path / "stack.vrt"), "finest")

        with rasterio.open(out) as ds:
            assert (ds.width, ds.height) == (100, 50)
            assert ds.bounds.left == pytest.approx(175.0)
            assert ds.count == 2
            assert ds.nodatavals == (0.0, 0.0)
            # Band 1 carries the western tile, band 2 the eastern one; the rest of
            # each band is fill. A mis-shifted frame would put them on top of
            # each other or off the raster entirely.
            assert set(ds.read(1)[:, :50].ravel().tolist()) == {7}
            assert set(ds.read(2)[:, 50:].ravel().tolist()) == {9}

    def test_rewritten_vrt_still_accepts_the_stor03_source_rewrite(self, tmp_path):
        """``rewrite_vrt_sources`` runs after this at the store site (STOR-03)."""
        sources = [
            self._nodata_tile(
                tmp_path / "sw.tif", bounds=(175.0, 0.0, 180.0, 5.0), value=7
            ),
            self._nodata_tile(
                tmp_path / "se.tif", bounds=(-180.0, 0.0, -175.0, 5.0), value=9
            ),
        ]
        out = vrt_module._build_vrt(sources, str(tmp_path / "seam.vrt"), "finest")

        rewrite_vrt_sources(Path(out), vrt_storage_key="rasters/x/source.vrt")

        with rasterio.open(out) as ds:
            assert (ds.width, ds.height) == (100, 50)
            assert ds.bounds.left == pytest.approx(175.0)
            assert ds.nodata == 0.0

    def test_off_grid_seam_mosaic_is_not_clipped(self, tmp_path):
        """Off-grid sources produce fractional offsets; the raster must hold them.

        The western tile's left edge (175.03) is deliberately off the finest
        output grid, which is what makes `gdalbuildvrt` emit a fractional
        `DstRect`. The rewrite must keep that fraction *and* round the containing
        width up, or the last source hangs half a pixel outside the dataset.
        """
        sources = [
            _write_tif(
                tmp_path / "w.tif",
                epsg=4326,
                bounds=(175.03, 0.0, 180.0, 2.0),
                width=50,
                height=20,
                nodata=0,
                fill=7,
            ),
            _write_tif(
                tmp_path / "e.tif",
                epsg=4326,
                bounds=(-180.0, 0.0, -179.0, 2.0),
                width=50,
                height=20,
                nodata=0,
                fill=9,
            ),
        ]

        out = vrt_module._build_vrt(sources, str(tmp_path / "offgrid.vrt"), "finest")

        root = parse_vrt(out).getroot()
        offsets = [d.get("xOff") for d in root.iter("DstRect")]
        assert any("." in o for o in offsets), "expected a fractional offset here"
        width = int(root.get("rasterXSize"))
        far_edge = max(
            float(d.get("xOff")) + float(d.get("xSize")) for d in root.iter("DstRect")
        )
        assert width >= far_edge, (
            f"raster {width} px clips a source ending at {far_edge}"
        )

        with rasterio.open(out) as ds:
            assert ds.bounds.left == pytest.approx(175.03)
            row = ds.read(1)[0]
        assert set(row.tolist()) == {7, 9}

    def test_non_crossing_build_is_byte_identical_to_plain_gdalbuildvrt(self, tmp_path):
        """Nothing off the seam changes shape because of this PR."""
        sources = [
            self._nodata_tile(
                tmp_path / "a.tif", bounds=(10.0, 0.0, 15.0, 5.0), value=7
            ),
            self._nodata_tile(
                tmp_path / "b.tif", bounds=(15.0, 0.0, 20.0, 5.0), value=9
            ),
        ]
        ours = vrt_module._build_vrt(sources, str(tmp_path / "ours.vrt"), "finest")
        reference = str(tmp_path / "ref.vrt")
        subprocess.run(
            ["gdalbuildvrt", "-resolution", "highest", reference, *sources],
            capture_output=True,
            check=True,
        )

        assert Path(ours).read_bytes() == Path(reference).read_bytes()


# ---------------------------------------------------------------------------
# Site 3: the maxzoom symptom
# ---------------------------------------------------------------------------


# The two-ring seam extent's planar bounds, i.e. what extent_to_span_bbox
# reports for the Pacific COG above.
SEAM_SPAN_BOUNDS = [-180.0, -10.0, 180.0, 10.0]
# The same 10 deg x 20 deg footprint, moved off the seam. Longitude POSITION is
# the only axis that differs, so a maxzoom difference between the two can only
# come from the seam handling.
OFF_SEAM_BOUNDS = [5.0, -10.0, 15.0, 10.0]


def _extent_derived_asset(**overrides) -> RasterAsset:
    """A COG whose maxzoom comes from the extent, not from recorded resolution.

    ``res_x``/``res_y`` are left NULL — the only way into the extent-width
    branch of ``_native_resolution_meters`` — and the pixel grid is anisotropic
    so that longitude is the finer of the two axes. Both matter: see
    ``test_latitude_axis_masks_the_collapse``.
    """
    fields = {
        "dataset_id": uuid.uuid4(),
        "asset_uri": "rasters/test/pacific.cog.tif",
        "storage_backend": "local",
        "epsg": 3832,
        "width": 36000,
        "height": 200,
    }
    fields.update(overrides)
    return RasterAsset(**fields)


class TestMaxzoomSymptom:
    """A 360°-wide extent understates resolution and collapses maxzoom."""

    def test_span_bbox_alone_collapses_maxzoom(self):
        """The symptom, reproduced: 360° of width over 36000 px reads as 1113 m."""
        asset = _extent_derived_asset()

        assert _raster_maxzoom_from_metadata(asset, SEAM_SPAN_BOUNDS) == 8

    def test_honest_lon_span_restores_maxzoom(self):
        """The real 10° over the same 36000 px is 31 m — five zoom levels back."""
        asset = _extent_derived_asset()

        assert (
            _raster_maxzoom_from_metadata(asset, SEAM_SPAN_BOUNDS, lon_span=10.0) == 13
        )

    def test_seam_and_off_seam_extents_agree(self):
        """Same footprint, same latitudes — only the longitude moves."""
        asset = _extent_derived_asset()

        off_seam = _raster_maxzoom_from_metadata(asset, OFF_SEAM_BOUNDS)
        on_seam = _raster_maxzoom_from_metadata(asset, SEAM_SPAN_BOUNDS, lon_span=10.0)

        assert on_seam == off_seam == 13

    def test_genuinely_global_extent_keeps_its_coarse_maxzoom(self):
        """A raster that really is 360° wide is honestly coarse; leave it be."""
        asset = _extent_derived_asset()

        assert (
            _raster_maxzoom_from_metadata(asset, SEAM_SPAN_BOUNDS, lon_span=360.0) == 8
        )

    def test_latitude_axis_masks_the_collapse(self):
        """Documented limit of the symptom, and why the fixture above is skewed.

        ``_native_resolution_meters`` takes ``min()`` across the two axes, so an
        inflated longitude resolution is simply discarded whenever latitude is
        the finer axis — which is the usual case for a square-pixel raster below
        ~88° latitude. The bad width is still recorded, and still wrong; it just
        cannot move the maxzoom for those rasters. Anyone tempted to drop the
        ``lon_span`` plumbing because "the tests pass either way" should start
        here.
        """
        square_pixels = _extent_derived_asset(width=1000, height=2000)

        assert _raster_maxzoom_from_metadata(square_pixels, SEAM_SPAN_BOUNDS) == 8
        assert (
            _raster_maxzoom_from_metadata(
                square_pixels, SEAM_SPAN_BOUNDS, lon_span=10.0
            )
            == 8
        )

    def test_recorded_resolution_still_wins(self):
        """lon_span must not disturb the resolution-metadata path."""
        asset = _extent_derived_asset(epsg=3857, res_x=1.39, res_y=1.39)

        assert (
            _raster_maxzoom_from_metadata(asset, SEAM_SPAN_BOUNDS, lon_span=10.0) == 17
        )


# ---------------------------------------------------------------------------
# Site 3, end to end: the raster tile token
# ---------------------------------------------------------------------------


async def _seed_raster(
    session,
    *,
    extent_wkt: str,
    width: int = 36000,
    height: int = 200,
) -> Dataset:
    admin = (
        await session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
    ).scalar_one()

    record = Record(
        title=f"Antimeridian raster {uuid.uuid4().hex[:6]}",
        summary="Seam-crossing raster for #887",
        theme_category=["test"],
        visibility="public",
        record_status="published",
        record_type="raster_dataset",
        created_by=admin.id,
        updated_by=admin.id,
    )
    record.spatial_extent = func.ST_GeomFromText(extent_wkt, 4326)
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"raster_887_{uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="pacific.tif",
        srid=3832,
    )
    session.add(dataset)
    await session.flush()

    session.add(
        RasterAsset(
            dataset_id=dataset.id,
            asset_uri=f"rasters/{dataset.id}/abc/source.cog.tif",
            storage_backend="local",
            epsg=3832,
            width=width,
            height=height,
        )
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


class TestRasterTokenAcrossTheSeam:
    """Every test here MUST take ``clean_tables``.

    fix(#887): ``test_db_session`` does not roll back — the worker's database is
    shared across the whole session and isolation is by explicit cleanup. A
    committed two-ring extent that outlives its test breaks
    ``test_record_translations_migration``, whose alembic round-trip downgrades
    through ``0030_records_spatial_extent_type``; that downgrade refuses by
    design when any ``catalog.records`` row holds a MULTIPOLYGON (#901), because
    the narrowed column cannot store one. It surfaces as an unrelated migration
    failure on a later test, only under ``-n`` and only when the ordering puts the
    two on the same worker, so it reads exactly like a flake. ``clean_tables``
    truncates ``catalog.records`` afterwards; the sibling
    ``test_antimeridian_rollup.py`` does the same for the same reason.
    """

    async def test_seam_crossing_raster_keeps_a_usable_maxzoom(
        self, client: AsyncClient, test_db_session, clean_tables
    ):
        """The reported symptom: the raster stops rendering as you zoom in.

        The stored extent is the two-ring form, whose planar bounds are
        -180..180; without the honest width the token's maxzoom drops to 8 and
        the layer disappears five zoom levels early.
        """
        dataset = await _seed_raster(
            test_db_session,
            extent_wkt=bbox_to_extent_wkt(175.0, -10.0, -175.0, 10.0),
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 200
        data = resp.json()

        assert data["kind"] == "raster"
        assert data["maxzoom"] == 13
        # The tile source's own bounds stay monotonic (#892) — over-broad, never
        # inverted — even though the maxzoom now uses the real 10 deg width.
        assert data["bounds"][0] == pytest.approx(-180.0)
        assert data["bounds"][2] == pytest.approx(180.0)

    async def test_off_seam_raster_of_the_same_size_matches(
        self, client: AsyncClient, test_db_session, clean_tables
    ):
        """Negative probe: identical footprint and latitudes, moved off the seam."""
        dataset = await _seed_raster(
            test_db_session,
            extent_wkt=bbox_to_extent_wkt(5.0, -10.0, 15.0, 10.0),
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 200

        assert resp.json()["maxzoom"] == 13

    async def test_global_raster_token_is_unchanged(
        self, client: AsyncClient, test_db_session, clean_tables
    ):
        """A raster that really is 360° wide keeps its (honestly coarse) maxzoom."""
        dataset = await _seed_raster(
            test_db_session,
            extent_wkt=bbox_to_extent_wkt(-180.0, -10.0, 180.0, 10.0),
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 200

        assert resp.json()["maxzoom"] == 8
