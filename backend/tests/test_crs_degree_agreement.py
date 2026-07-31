"""fix(#961): every "is this CRS degree-based" site must give the same answer.

The question is asked in four places, in three languages, and they cannot all
be merged: two Python helpers over a WKT string, one Python helper over a live
``rasterio.crs.CRS``, and two SQL predicates that run inside a query against
``spatial_ref_sys.srtext``, where there is no Python-side CRS object to hand to
PROJ. #961 consolidated what could be consolidated (the unit comparison now
lives once, in ``core.geo.crs_has_degree_unit``) and recorded the SQL pair as a
standing sync obligation. This file is that obligation as a gate rather than a
comment.

The proving case is a grads GEOGCS. EPSG:4807 (NTF Paris) and its relatives —
14 SRIDs in a stock PostGIS ``spatial_ref_sys`` — are geographic with a full
circle of 400, not 360. Every site has to agree that they are lon/lat AND that
they are not degrees, because the two callers do different damage when wrong:
``_shift_zero_to_360_longitudes`` would translate a valid feature by -360 grads
into empty space, and ``vrt.py``'s re-framing would emit a 40-grad hull where
10 was intended (#887).

Reads srtext from the database rather than from fixtures on purpose: the SQL
predicates are only meaningful against the strings PostGIS actually ships, and
a fixture would prove the regexes agree with themselves.
"""

import pytest
from sqlalchemy import text

from app.core.geo import crs_has_degree_unit, wkt_has_degree_unit, wkt_is_geographic
from app.processing.ingest.metadata import (
    _DEGREE_UNIT_SRTEXT_RE,
    _GEOGRAPHIC_SRTEXT_RE,
)
from app.processing.raster.vrt import _is_degree_based

# (srid, geographic, degree-based). The grads rows are the point of the file;
# the others are the controls that keep a trivially-true predicate from passing.
CASES = [
    (4326, True, True),  # WGS 84 — the ordinary case
    (4269, True, True),  # NAD83 — geographic, degrees, different datum
    (4807, True, False),  # NTF (Paris) — geographic, GRADS
    (4901, True, False),  # ATF (Paris) — the same family
    (3857, False, False),  # Web Mercator — projected, X in metres
    (2263, False, False),  # NY Long Island ftUS — projected, X in feet
    # fix(#961 review): a top-level-keyword matrix is not enough. A stock
    # spatial_ref_sys carries 277 COMPD_CS rows and a family of BOUNDCRS-wrapped
    # geographic CRSs whose srtext starts with the WRAPPER, and the sites split
    # on those — see test_the_shift_gate_is_sound_not_complete below for why
    # that split is deliberate rather than a bug to unify away.
    (3823, True, True),  # TWD97 — BOUNDCRS wrapping a degree GEOGCRS
    (4339, True, True),  # Australian Antarctic — same wrapper shape
    (5698, False, False),  # RGF93 / Lambert-93 + height — COMPD_CS over PROJCS
]


async def _srtext(session, srid: int) -> str | None:
    return await session.scalar(
        text("SELECT srtext FROM spatial_ref_sys WHERE srid = :srid"),
        {"srid": srid},
    )


@pytest.mark.anyio
@pytest.mark.parametrize("srid,is_geographic,is_degrees", CASES)
async def test_every_site_agrees_on_the_same_crs(
    test_db_session, srid, is_geographic, is_degrees
):
    srtext = await _srtext(test_db_session, srid)
    if not srtext:
        pytest.skip(f"srid {srid} is not in this PostGIS build's spatial_ref_sys")

    # 1. core.geo, over the stored WKT — what tiles/router.py reads.
    assert wkt_is_geographic(srtext) is is_geographic, srtext
    if is_geographic:
        assert wkt_has_degree_unit(srtext) is is_degrees, srtext

    # 2. core.geo, over a parsed CRS — the shared entry point #961 added.
    from rasterio.crs import CRS

    crs = CRS.from_wkt(srtext)
    if is_geographic:
        assert crs_has_degree_unit(crs) is is_degrees, srtext

    # 3. processing/raster/vrt.py, over the live CRS object it already holds.
    # It folds the geographic precondition in, so it answers the conjunction.
    assert _is_degree_based(crs) is (is_geographic and is_degrees), srtext

    # 4. The #906 degenerate-envelope floor's inline predicate, which its own
    # comment says is "the same keyword logic as core.geo.wkt_is_geographic, in
    # srtext form". Held to that claim, wrappers included — it sees through
    # them the way the Python helper does. Run as SQL, not as a Python regex:
    # `~*` is POSIX and case-insensitive, and the point is what the database
    # decides.
    sql_is_geographic = await test_db_session.scalar(
        text(
            "SELECT srtext ~* 'GEOG(CS|CRS)' AND srtext !~* 'PROJ(CS|CRS)' "
            "FROM spatial_ref_sys WHERE srid = :srid"
        ),
        {"srid": srid},
    )
    assert sql_is_geographic is is_geographic, srtext


@pytest.mark.anyio
@pytest.mark.parametrize("srid,is_geographic,is_degrees", CASES)
async def test_the_shift_gate_is_sound_not_complete(
    test_db_session, srid, is_geographic, is_degrees
):
    """The 0..360 gate may decline; it may never fire wrongly.

    `_shift_zero_to_360_longitudes` is the one site here whose answer MOVES
    geometry, by 360 degrees, so its predicate is held to soundness rather than
    to agreement: whenever it says "degree lon/lat", PROJ must agree.

    It is deliberately incomplete in the other direction. Its
    `_GEOGRAPHIC_SRTEXT_RE` is anchored, so a wrapped CRS (BOUNDCRS, COMPD_CS)
    reads as not-lon/lat and nothing shifts. Un-anchoring it was tried and
    reverted (#961 review): `_DEGREE_UNIT_SRTEXT_RE` is a flat substring scan,
    so on `BOUNDCRS[SOURCECRS[GEOGCS[...UNIT["grad"...]]], TARGETCRS[...]]` it
    finds an unrelated `degree` on the target or a PRIMEM and reports degrees —
    and the shift then subtracts 360 from coordinates whose full turn is 400.
    `test_wkt_is_geographic.py::test_boundcrs_reports_the_source_crs_units_not_the_targets`
    pins the same shape on the Python side. A flat scan cannot decide which
    subtree a token belongs to; that is `core.geo._parse_crs`'s whole thesis.

    Declining costs a clip that is reported to the user. Firing wrongly
    corrupts coordinates silently. So: sound, not complete.
    """
    srtext = await _srtext(test_db_session, srid)
    if not srtext:
        pytest.skip(f"srid {srid} is not in this PostGIS build's spatial_ref_sys")

    fires = await test_db_session.scalar(
        text(
            "SELECT srtext ~* :geographic AND srtext ~* :degree_unit "
            "FROM spatial_ref_sys WHERE srid = :srid"
        ).bindparams(
            geographic=_GEOGRAPHIC_SRTEXT_RE,
            degree_unit=_DEGREE_UNIT_SRTEXT_RE,
            srid=srid,
        )
    )
    if fires:
        assert is_geographic and is_degrees, (
            f"srid {srid} would be shifted by 360 but PROJ reports "
            f"geographic={is_geographic} degrees={is_degrees}: {srtext}"
        )

    # And the incompleteness is exactly where it is claimed to be: a top-level
    # GEOGCS in degrees is never declined, so the conservatism costs nothing on
    # the ordinary case.
    if is_geographic and is_degrees and srtext.upper().startswith("GEOG"):
        assert fires, f"srid {srid} is a plain degree GEOGCS and must qualify"


@pytest.mark.anyio
async def test_grads_srids_are_not_a_theoretical_class(test_db_session):
    """The grads family is really in there, so the guard is load-bearing.

    #899 counted 14 such SRIDs in a stock spatial_ref_sys. Asserting a floor
    rather than the exact count: the number moves with the PROJ database
    version, but "several" is the fact the guards are built on, and zero would
    mean this whole file proves nothing.
    """
    grads_count = await test_db_session.scalar(
        text(
            "SELECT count(*) FROM spatial_ref_sys "
            "WHERE srtext ~* :geographic AND srtext !~* :degree_unit"
        ).bindparams(
            geographic=_GEOGRAPHIC_SRTEXT_RE,
            degree_unit=_DEGREE_UNIT_SRTEXT_RE,
        )
    )
    assert grads_count >= 10, (
        f"only {grads_count} non-degree geographic SRIDs found; if PROJ has "
        "stopped shipping the Paris-meridian family, the 0..360 and VRT "
        "re-framing guards need re-justifying, not deleting"
    )


def test_unknown_units_resolve_to_the_safe_side_at_each_caller():
    """The two callers read "unknown" oppositely, on purpose.

    ``crs_has_degree_unit`` returns None when PROJ cannot report a factor.
    ``_is_degree_based`` turns that into False, because a CRS it cannot
    classify must not be shifted by 360. ``tiles/router.py`` tests
    ``is not False``, so an unparseable CRS keeps the historical degrees
    assumption instead of losing five zoom levels. Pinned here because a
    single shared helper makes it tempting to unify the two readings.
    """

    class _NoUnits:
        is_geographic = True

        @property
        def units_factor(self):
            raise ValueError("PROJ cannot answer")

    crs = _NoUnits()
    assert crs_has_degree_unit(crs) is None
    assert _is_degree_based(crs) is False
    assert (crs_has_degree_unit(crs) is not False) is True
