"""fix(#569): CRS classification for honest raster resolution display.

The frontend must not format degree resolutions as meters, so raster metadata
has to know the stored CRS's class and its angular unit.

fix(#939): PROJ answers both questions whenever it can parse the stored WKT;
the keyword sniff survives only as the fallback for WKT it rejects. Most
fixtures below are deliberately abbreviated so they exercise that fallback —
``test_real_epsg_wkt_round_trips_through_both_helpers`` covers the valid WKT
the producers actually write.
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


def test_cs_marker_inside_a_quoted_axis_name_is_not_structure():
    # fix(#939 codex r8): a quoted axis name containing "CS[" must not be read
    # as a WKT2 coordinate-system marker. PROJ tokenizes quoted names, so this
    # is structurally impossible now; kept as a regression fixture.
    wkt = (
        'GEOGCS["WGS 84",DATUM["WGS_1984",'
        'SPHEROID["WGS 84",6378137,298.257223563]],'
        'UNIT["degree",0.0174532925199433],'
        'AXIS["Latitude CS[ legacy",NORTH],AXIS["Longitude",EAST]]'
    )
    assert wkt_has_degree_unit(wkt) is True


def test_custom_degree_name_is_matched_by_conversion_factor():
    # fix(#939 codex r7): WKT unit semantics live in the radians-per-unit
    # factor, not the name, and rasterio preserves valid custom names — so
    # the check compares factors (as `_is_degree_based` does) either way.
    wkt = (
        'GEOGCS["WGS 84",DATUM["WGS_1984",'
        'SPHEROID["WGS 84",6378137,298.257223563]],'
        'UNIT["arc-degree",0.0174532925199433]]'
    )
    assert wkt_has_degree_unit(wkt) is True

    radians = wkt.replace('"arc-degree",0.0174532925199433', '"radian",1')
    assert wkt_has_degree_unit(radians) is False


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


def test_boundcrs_reports_the_source_crs_units_not_the_targets():
    # fix(#939 codex r5/r6): a BOUNDCRS binds a grads SOURCECRS to a degree
    # TARGETCRS, and the stored resolutions are expressed in the SOURCE. The
    # target declares "degree" twice (its PRIMEM and its axes), so any flat
    # scan of the string finds a degree unit; PROJ resolves the tree and
    # reports the source's grads.
    wkt = (
        'BOUNDCRS[SOURCECRS[GEOGCRS["ATF (Paris)",'
        'DATUM["Ancienne Triangulation Francaise (Paris)",'
        'ELLIPSOID["Plessis 1817",6376523,308.64,LENGTHUNIT["metre",1]]],'
        'PRIMEM["Paris RGS",2.33720833333333,'
        'ANGLEUNIT["degree",0.0174532925199433]],'
        "CS[ellipsoidal,2],"
        'AXIS["latitude",north,ORDER[1],ANGLEUNIT["grad",0.015707963267949]],'
        'AXIS["longitude",east,ORDER[2],ANGLEUNIT["grad",0.015707963267949]]]],'
        'TARGETCRS[GEOGCRS["WGS 84",'
        'DATUM["World Geodetic System 1984",'
        'ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]]],'
        'PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]],'
        "CS[ellipsoidal,2],"
        'AXIS["latitude",north,ORDER[1],ANGLEUNIT["degree",0.0174532925199433]],'
        'AXIS["longitude",east,ORDER[2],'
        'ANGLEUNIT["degree",0.0174532925199433]]]],'
        'ABRIDGEDTRANSFORMATION["ATF to WGS 84",'
        'METHOD["Geocentric translations",ID["EPSG",9603]],'
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


def test_axis_meridian_unit_does_not_masquerade_as_the_axis_unit():
    # fix(#939 codex r9): a geographic 3D CRS whose axes are radians but whose
    # AXIS carries MERIDIAN[...,ANGLEUNIT["degree",...]]. The meridian's unit
    # sits INSIDE the coordinate-system section, so every window-narrowing
    # rule still saw it and reported degrees. PROJ reads the axis unit.
    wkt = (
        'GEOGCRS["synthetic radian 3D",DATUM["World Geodetic System 1984",'
        'ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]]],'
        "CS[ellipsoidal,3],"
        'AXIS["latitude",north,MERIDIAN[0,ANGLEUNIT["degree",0.0174532925199433]],'
        'ANGLEUNIT["radian",1]],'
        'AXIS["longitude",east,MERIDIAN[90,ANGLEUNIT["degree",0.0174532925199433]],'
        'ANGLEUNIT["radian",1]],'
        'AXIS["ellipsoidal height",up,LENGTHUNIT["metre",1]]]'
    )
    assert wkt_is_geographic(wkt) is True
    assert wkt_has_degree_unit(wkt) is False


def test_real_epsg_wkt_round_trips_through_both_helpers():
    """Whatever rasterio actually writes at ingest must classify correctly.

    The hand-written fixtures above are abbreviated on purpose (they exercise
    the sniff fallback); this is the shape the producers really store.
    """
    from rasterio.crs import CRS

    for epsg, geographic, degrees in (
        (4326, True, True),
        (4269, True, True),  # NAD83
        (4258, True, True),  # ETRS89
        (4979, True, True),  # WGS 84 3D — WKT2-only, the r9 shape
        (9518, True, True),  # WGS 84 + EGM2008 height (compound)
        (4807, True, False),  # NTF (Paris) — geographic, grads
        (3857, False, False),
        (32633, False, False),  # UTM 33N
    ):
        wkt = CRS.from_epsg(epsg).to_wkt()
        assert wkt_is_geographic(wkt) is geographic, epsg
        assert wkt_has_degree_unit(wkt) is degrees, epsg


def test_unparseable_wkt_falls_back_to_the_keyword_sniff():
    """PROJ rejects a truncated CRS; the class sniff still answers, and the
    unit test honestly reports "unknown" rather than guessing."""
    truncated = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84"'
    assert wkt_is_geographic(truncated) is True
    assert wkt_has_degree_unit(truncated) is None


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
