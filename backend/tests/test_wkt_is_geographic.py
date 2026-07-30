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


def test_wkt2_grads_axes_with_degree_prime_meridian_are_not_degrees():
    # fix(#939 codex r4): EPSG:4901's WKT2 expresses the PRIME meridian in
    # degrees while both ellipsoidal axes are grads — the unit test must read
    # the coordinate-system section, not the first angular unit anywhere.
    wkt = (
        'GEOGCRS["ATF (Paris)",'
        'DATUM["Ancienne Triangulation Francaise (Paris)",'
        'ELLIPSOID["Plessis 1817",6376523,308.64,LENGTHUNIT["metre",1]]],'
        'PRIMEM["Paris RGS",2.33720833333333,ANGLEUNIT["degree",0.0174532925199433]],'
        "CS[ellipsoidal,2],"
        'AXIS["geodetic latitude (Lat)",north,ANGLEUNIT["grad",0.015707963267949]],'
        'AXIS["geodetic longitude (Lon)",east,ANGLEUNIT["grad",0.015707963267949]]]'
    )
    assert wkt_is_geographic(wkt) is True
    assert wkt_has_degree_unit(wkt) is False


def test_degree_unit_missing_wkt_is_unknown():
    assert wkt_has_degree_unit(None) is None
    assert wkt_has_degree_unit("") is None


def test_wkt2_2015_geodcrs_ellipsoidal_is_geographic():
    # fix(#939 codex r3): WKT2:2015 spells geographic CRSs GEODCRS; rasterio
    # still emits this form (CRS.from_epsg(4269).to_wkt(version="WKT2_2015")).
    wkt = (
        'GEODCRS["NAD83",DATUM["North American Datum 1983",'
        'ELLIPSOID["GRS 1980",6378137,298.257222101]],CS[ellipsoidal,2],'
        'AXIS["geodetic latitude (Lat)",north],AXIS["geodetic longitude (Lon)",east],'
        'ANGLEUNIT["degree",0.0174532925199433]]'
    )
    assert wkt_is_geographic(wkt) is True
    assert wkt_has_degree_unit(wkt) is True


def test_wkt2_2015_geodcrs_geocentric_is_not_geographic():
    # A GEODCRS with a Cartesian CS is geocentric XYZ metres, not lon/lat.
    wkt = (
        'GEODCRS["WGS 84 (geocentric)",DATUM["World Geodetic System 1984",'
        'ELLIPSOID["WGS 84",6378137,298.257223563]],CS[Cartesian,3],'
        'AXIS["(X)",geocentricX],AXIS["(Y)",geocentricY],AXIS["(Z)",geocentricZ],'
        'LENGTHUNIT["metre",1]]'
    )
    assert wkt_is_geographic(wkt) is False


def test_wkt2_2015_compound_geodcrs_is_geographic():
    wkt = (
        'COMPOUNDCRS["NAD83 + height",'
        'GEODCRS["NAD83",DATUM["North American Datum 1983",'
        'ELLIPSOID["GRS 1980",6378137,298.257222101]],CS[ellipsoidal,2],'
        'ANGLEUNIT["degree",0.0174532925199433]],'
        'VERTCRS["NAVD88 height",VDATUM["NAVD88"],CS[vertical,1],'
        'LENGTHUNIT["metre",1]]]'
    )
    assert wkt_is_geographic(wkt) is True


def test_boundcrs_target_degree_unit_does_not_leak_into_the_source():
    # fix(#939 codex r5): a BOUNDCRS binds a grads SOURCECRS to a degree
    # TARGETCRS; the unit scan must stop at the source's CS section instead
    # of finding the target's degree unit further down the string.
    wkt = (
        'BOUNDCRS[SOURCECRS[GEOGCRS["ATF (Paris)",'
        'DATUM["Ancienne Triangulation Francaise (Paris)",'
        'ELLIPSOID["Plessis 1817",6376523,308.64]],'
        "CS[ellipsoidal,2],"
        'AXIS["latitude",north,ANGLEUNIT["grad",0.015707963267949]],'
        'AXIS["longitude",east,ANGLEUNIT["grad",0.015707963267949]]]],'
        'TARGETCRS[GEOGCRS["WGS 84",'
        'DATUM["World Geodetic System 1984",'
        'ELLIPSOID["WGS 84",6378137,298.257223563]],'
        # fix(#939 codex r6): the target's PRIMEM declares its degree unit
        # BEFORE the target's own CS, so a next-CS window boundary alone
        # still leaked it into the scan.
        'PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]],'
        "CS[ellipsoidal,2],"
        'ANGLEUNIT["degree",0.0174532925199433]]],'
        'ABRIDGEDTRANSFORMATION["ATF to WGS 84",'
        'METHOD["Geocentric translations"],'
        'PARAMETER["X-axis translation",-168],'
        'PARAMETER["Y-axis translation",-60],'
        'PARAMETER["Z-axis translation",320]]]'
    )
    assert wkt_has_degree_unit(wkt) is False

    degree_source = wkt.replace(
        'ANGLEUNIT["grad",0.015707963267949]',
        'ANGLEUNIT["degree",0.0174532925199433]',
    )
    assert wkt_has_degree_unit(degree_source) is True


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
