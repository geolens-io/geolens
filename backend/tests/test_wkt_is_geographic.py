"""fix(#569): CRS-class sniffing for honest raster resolution display.

The frontend must not format degree resolutions as meters; this helper
classifies the stored WKT with zero proj dependencies.
"""

from app.core.geo import wkt_is_geographic

WKT2_GEOGRAPHIC = 'GEOGCRS["WGS 84",DATUM["World Geodetic System 1984",ELLIPSOID["WGS 84",6378137,298.257223563]]]'
WKT1_GEOGRAPHIC = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]]]'
)
# WKT1 nests a GEOGCS inside every PROJCS — the projected check must win.
WKT1_PROJECTED = 'PROJCS["WGS 84 / UTM zone 18N",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137]]],PROJECTION["Transverse_Mercator"]]'
WKT2_PROJECTED = (
    'PROJCRS["WGS 84 / UTM zone 18N",BASEGEOGCRS["WGS 84"],CONVERSION["UTM zone 18N"]]'
)
# EPSG:9518-style compound (horizontal geographic + vertical) — geographic.
WKT2_COMPOUND_GEOGRAPHIC = 'COMPOUNDCRS["WGS 84 + EGM2008 height",GEOGCRS["WGS 84",DATUM["World Geodetic System 1984"]],VERTCRS["EGM2008 height"]]'
WKT2_COMPOUND_PROJECTED = 'COMPOUNDCRS["NAD83 / UTM 18N + NAVD88",PROJCRS["NAD83 / UTM zone 18N",BASEGEOGCRS["NAD83"]],VERTCRS["NAVD88 height"]]'
WKT_ENGINEERING = 'ENGCRS["Site grid",EDATUM["Site origin"]]'


def test_geographic_wkt2():
    assert wkt_is_geographic(WKT2_GEOGRAPHIC) is True


def test_geographic_wkt1():
    assert wkt_is_geographic(WKT1_GEOGRAPHIC) is True


def test_projected_wkt1_with_nested_geogcs():
    assert wkt_is_geographic(WKT1_PROJECTED) is False


def test_projected_wkt2():
    assert wkt_is_geographic(WKT2_PROJECTED) is False


def test_compound_geographic():
    assert wkt_is_geographic(WKT2_COMPOUND_GEOGRAPHIC) is True


def test_compound_projected():
    assert wkt_is_geographic(WKT2_COMPOUND_PROJECTED) is False


def test_engineering_and_missing_are_unknown():
    assert wkt_is_geographic(WKT_ENGINEERING) is None
    assert wkt_is_geographic(None) is None
    assert wkt_is_geographic("") is None
