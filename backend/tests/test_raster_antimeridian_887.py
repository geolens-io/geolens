"""Antimeridian handling in the raster pipeline (#887).

Three sites, one seam:

1. ``processing/raster/cog.py`` — ``extract_raster_metadata`` folded the
   reprojected WGS84 bounds into a single hand-built ``POLYGON`` ring. GDAL
   already reports a seam-crossing footprint as ``west > east``, so that ring
   was the *complement*: a Pacific COG spanning 175E..175W registered a valid
   350°-wide rectangle covering 7000 deg² of the wrong side of the world
   instead of its real 200.
2. ``processing/raster/vrt.py`` — ``_write_python_vrt`` took ``min(left)`` /
   ``max(right)`` across sources, so a 10°-wide mosaic straddling the seam was
   allocated 360° wide (3600 x 50 px instead of 100 x 50) with every source at
   the wrong ``dst_x_off``.
3. ``processing/tiles/router.py`` — the user-visible symptom. Source maxzoom is
   derived from extent width when the COG has no recorded resolution, so a
   seam-crossing raster measured 36x too wide, understated its own resolution,
   and stopped rendering as the user zoomed in.

The DB-backed tests need Postgres (``docker compose up -d --wait db``); the rest
are pure rasterio/XML unit tests.
"""

import io
import uuid
from pathlib import Path
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
from app.core.geo import bbox_to_extent_wkt, extent_lon_span, extent_to_bbox
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.raster.cog import extract_raster_metadata
from app.processing.raster.models import RasterAsset
from app.processing.raster.vrt import _seam_frame_origin, _write_python_vrt
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

    buf = io.BytesIO()
    with MemoryFile() as mem:
        with mem.open(**profile) as ds:
            ds.write(np.zeros((height, width), dtype="uint8"), 1)
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


def _dst_x_offs(vrt_path: str) -> list[int]:
    root = parse_vrt(vrt_path).getroot()
    return [int(d.get("xOff")) for d in root.iter("DstRect")]


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
        # 4.0075e7 m of easting at 2e4 m/px: the eastern tile starts 1954 px in.
        assert _vrt_size(out) == (2004, 50)
        assert _dst_x_offs(out) == [0, 1954]

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
    async def test_seam_crossing_raster_keeps_a_usable_maxzoom(
        self, client: AsyncClient, test_db_session
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
        self, client: AsyncClient, test_db_session
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
        self, client: AsyncClient, test_db_session
    ):
        """A raster that really is 360° wide keeps its (honestly coarse) maxzoom."""
        dataset = await _seed_raster(
            test_db_session,
            extent_wkt=bbox_to_extent_wkt(-180.0, -10.0, 180.0, 10.0),
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 200

        assert resp.json()["maxzoom"] == 8
