"""fix(#569): CRS-class sniffing for honest raster resolution display.

The frontend must not format degree resolutions as meters; this helper
classifies the stored WKT with zero proj dependencies.
"""

from app.core.geo import wkt_has_degree_unit, wkt_is_geographic

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
# fix(#939): degree-unit fixtures for wkt_has_degree_unit. Grads GEOGCS is
# geographic per the keyword test but its resolutions are not degrees.
WKT1_GEOGRAPHIC_DEGREE = 'GEOGCS["NAD83",DATUM["North_American_Datum_1983",SPHEROID["GRS 1980",6378137,298.257222101]],UNIT["degree",0.0174532925199433]]'
WKT2_GEOGRAPHIC_DEGREE = 'GEOGCRS["WGS 84",DATUM["World Geodetic System 1984",ELLIPSOID["WGS 84",6378137,298.257223563]],CS[ellipsoidal,2],AXIS["latitude",north],AXIS["longitude",east],ANGLEUNIT["degree",0.0174532925199433]]'
WKT1_GEOGRAPHIC_GRADS = 'GEOGCS["NTF (Paris)",DATUM["Nouvelle_Triangulation_Francaise_Paris",SPHEROID["Clarke 1880 (IGN)",6378249.2,293.4660212936265]],PRIMEM["Paris",2.33722917],UNIT["grad",0.01570796326794897]]'


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


# fix(#939): wkt_has_degree_unit — the companion unit test wkt_is_geographic
# deliberately does not perform.


def test_degree_unit_wkt1():
    assert wkt_has_degree_unit(WKT1_GEOGRAPHIC_DEGREE) is True


def test_degree_unit_wkt2_angleunit():
    # WKT2 spells it ANGLEUNIT["degree"...] — must match too.
    assert wkt_has_degree_unit(WKT2_GEOGRAPHIC_DEGREE) is True


def test_grads_geogcs_is_geographic_but_not_degrees():
    assert wkt_is_geographic(WKT1_GEOGRAPHIC_GRADS) is True
    assert wkt_has_degree_unit(WKT1_GEOGRAPHIC_GRADS) is False


def test_degree_unit_missing_wkt_is_unknown():
    assert wkt_has_degree_unit(None) is None
    assert wkt_has_degree_unit("") is None


def test_non_string_inputs_are_unknown_not_a_crash():
    # fix(#939 codex r2): callers hand these whatever sits on
    # RasterAsset.crs_wkt, including MagicMock in unit tests.
    from unittest.mock import MagicMock

    assert wkt_is_geographic(MagicMock()) is None  # type: ignore[arg-type]
    assert wkt_has_degree_unit(MagicMock()) is None  # type: ignore[arg-type]
    assert wkt_is_geographic(12345) is None  # type: ignore[arg-type]


def test_long_quoted_name_cannot_hide_the_keywords():
    # fix(#939 codex r2): quoted content is blanked BEFORE the 2000-char
    # truncation, so a pathologically long name containing PROJCS cannot
    # misclassify (or declassify) the WKT.
    long_name = ("PROJCS padding " * 200)[:2500]
    wkt = f'GEOGCRS["{long_name}",DATUM["World Geodetic System 1984"]]'
    assert wkt_is_geographic(wkt) is True


def test_keywords_inside_quoted_names_are_ignored():
    # fix(#939 codex r1): a CRS name or remark mentioning PROJCS must not
    # flip a geographic WKT to projected (and vice versa).
    geographic_with_projcs_in_name = 'GEOGCRS["adjusted from PROJCS NAD27",DATUM["North American Datum 1927",ELLIPSOID["Clarke 1866",6378206.4,294.978698213898]],ANGLEUNIT["degree",0.0174532925199433]]'
    assert wkt_is_geographic(geographic_with_projcs_in_name) is True

    projected_with_geogcrs_in_remark = 'PROJCS["UTM 18N",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137]]],PROJECTION["Transverse_Mercator"],REMARK["see GEOGCRS 4326"]]'
    assert wkt_is_geographic(projected_with_geogcrs_in_remark) is False
