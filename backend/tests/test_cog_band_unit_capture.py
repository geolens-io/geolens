"""RHYD-01 (v1041 follow-up): band unit capture in extract_raster_metadata.

COG ingest was writing band_info entries without a ``unit`` key, so
``_extract_dem_vertical_units`` always returned None even for rasters that
carry GDAL-level band unit strings (``src.units``).  This module pins:

1. When ``src.units`` contains a non-empty unit string, the corresponding
   band_info entry includes ``"unit": <value>`` and
   ``_extract_dem_vertical_units`` returns it.
2. When ``src.units`` is empty / all blank, no ``unit`` key is written to
   band_info (no None litter).
3. When ``src.units`` is shorter than ``src.count`` (partial tuple), the
   missing bands don't get a ``unit`` key.
"""

from unittest import mock


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_fake_src(
    *,
    count: int = 1,
    dtypes: tuple = ("float32",),
    nodata: float | None = None,
    units: tuple = (),
    colorinterp=None,
    crs=None,
    bounds=None,
    transform=None,
    overviews: list | None = None,
    profile: dict | None = None,
    tags: dict | None = None,
) -> mock.MagicMock:
    """Build a minimal rasterio dataset mock for extract_raster_metadata."""
    import rasterio
    from rasterio.crs import CRS

    if crs is None:
        crs = CRS.from_epsg(4326)
    if bounds is None:
        from rasterio.coords import BoundingBox

        bounds = BoundingBox(left=-74.1, bottom=40.6, right=-73.9, top=40.8)
    if colorinterp is None:
        colorinterp = [rasterio.enums.ColorInterp.gray] * count
    if profile is None:
        profile = {
            "compress": "deflate",
            "blockxsize": 512,
            "blockysize": 512,
            "tiled": True,
            "driver": "GTiff",
        }
    if overviews is None:
        overviews = [2, 4, 8]

    # Build a plain mock for the affine transform so we can set .a/.e/.b/.d
    # freely — rasterio.Affine is a named tuple and its attributes are
    # read-only, so we cannot assign to a real Affine instance.
    fake_transform = mock.MagicMock()
    fake_transform.a = (bounds.right - bounds.left) / 256
    fake_transform.e = -(bounds.top - bounds.bottom) / 256
    fake_transform.b = 0.0
    fake_transform.d = 0.0

    src = mock.MagicMock()
    src.crs = crs
    src.count = count
    src.dtypes = dtypes
    src.nodata = nodata
    src.units = units
    src.colorinterp = colorinterp
    src.bounds = bounds
    src.transform = fake_transform
    src.width = 256
    src.height = 256
    src.profile = profile
    src.overviews = mock.Mock(return_value=overviews)
    src.tags = mock.Mock(return_value=tags or {})
    return src


def _run_extract(fake_src, monkeypatch) -> dict:
    """Patch rasterio.open and run extract_raster_metadata."""
    import rasterio
    from app.processing.raster.cog import extract_raster_metadata

    ctx = mock.MagicMock()
    ctx.__enter__.return_value = fake_src
    ctx.__exit__.return_value = False
    monkeypatch.setattr(rasterio, "open", lambda *_a, **_kw: ctx)
    return extract_raster_metadata("/fake/path.tif")


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


class TestBandUnitCaptureWithUnits:
    def test_unit_key_present_when_src_units_nonempty(self, monkeypatch):
        """Band entry has ``unit`` when src.units carries a non-empty string."""
        fake_src = _make_fake_src(units=("metre",))
        meta = _run_extract(fake_src, monkeypatch)
        band_info = meta["band_info"]
        assert len(band_info) == 1
        assert band_info[0]["unit"] == "metre"

    def test_unit_key_present_for_feet(self, monkeypatch):
        """'feet' (US customary) is captured faithfully."""
        fake_src = _make_fake_src(units=("feet",))
        meta = _run_extract(fake_src, monkeypatch)
        assert meta["band_info"][0]["unit"] == "feet"

    def test_unit_value_is_stripped(self, monkeypatch):
        """Leading/trailing whitespace in the unit string is stripped."""
        fake_src = _make_fake_src(units=("  meter  ",))
        meta = _run_extract(fake_src, monkeypatch)
        assert meta["band_info"][0]["unit"] == "meter"

    def test_multi_band_units(self, monkeypatch):
        """Each band gets its own unit when the units tuple is multi-valued."""
        import rasterio

        fake_src = _make_fake_src(
            count=2,
            dtypes=("float32", "float32"),
            units=("metre", "metre"),
            colorinterp=[
                rasterio.enums.ColorInterp.gray,
                rasterio.enums.ColorInterp.gray,
            ],
        )
        meta = _run_extract(fake_src, monkeypatch)
        band_info = meta["band_info"]
        assert band_info[0]["unit"] == "metre"
        assert band_info[1]["unit"] == "metre"


class TestBandUnitCaptureWithoutUnits:
    def test_no_unit_key_when_units_empty_tuple(self, monkeypatch):
        """Empty units tuple → no ``unit`` key in band_info (no None litter)."""
        fake_src = _make_fake_src(units=())
        meta = _run_extract(fake_src, monkeypatch)
        band_info = meta["band_info"]
        assert len(band_info) == 1
        assert "unit" not in band_info[0]

    def test_no_unit_key_when_unit_is_blank_string(self, monkeypatch):
        """Blank unit string → no ``unit`` key (guards against GDAL empty-string noise)."""
        fake_src = _make_fake_src(units=("",))
        meta = _run_extract(fake_src, monkeypatch)
        assert "unit" not in meta["band_info"][0]

    def test_no_unit_key_when_unit_is_whitespace(self, monkeypatch):
        """Whitespace-only unit string → no ``unit`` key."""
        fake_src = _make_fake_src(units=("   ",))
        meta = _run_extract(fake_src, monkeypatch)
        assert "unit" not in meta["band_info"][0]

    def test_no_unit_key_when_units_is_none(self, monkeypatch):
        """``src.units = None`` → no ``unit`` key (rasterio may return None)."""
        fake_src = _make_fake_src(units=None)
        meta = _run_extract(fake_src, monkeypatch)
        assert "unit" not in meta["band_info"][0]

    def test_partial_units_tuple_shorter_than_band_count(self, monkeypatch):
        """Units tuple shorter than band count: only bands with a unit get the key."""
        import rasterio

        fake_src = _make_fake_src(
            count=2,
            dtypes=("float32", "float32"),
            units=("metre",),  # only 1 entry for 2 bands
            colorinterp=[
                rasterio.enums.ColorInterp.gray,
                rasterio.enums.ColorInterp.gray,
            ],
        )
        meta = _run_extract(fake_src, monkeypatch)
        band_info = meta["band_info"]
        assert band_info[0]["unit"] == "metre"
        assert "unit" not in band_info[1]


class TestExtractDemVerticalUnitsRoundTrip:
    """End-to-end: band_info produced by cog.py flows correctly into
    _extract_dem_vertical_units (service_shared.py)."""

    def test_round_trip_unit_metre(self, monkeypatch):
        """Units written at ingest are read back by _extract_dem_vertical_units."""
        from app.modules.catalog.maps.service_shared import _extract_dem_vertical_units

        fake_src = _make_fake_src(units=("metre",))
        meta = _run_extract(fake_src, monkeypatch)
        result = _extract_dem_vertical_units(meta["band_info"])
        assert result == "metre"

    def test_round_trip_no_units_returns_none(self, monkeypatch):
        """No units at ingest → _extract_dem_vertical_units returns None."""
        from app.modules.catalog.maps.service_shared import _extract_dem_vertical_units

        fake_src = _make_fake_src(units=())
        meta = _run_extract(fake_src, monkeypatch)
        result = _extract_dem_vertical_units(meta["band_info"])
        assert result is None
