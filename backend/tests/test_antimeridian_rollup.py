"""fix(#886): extent rollups across the antimeridian.

Distinct from #892/#884: here *no individual record wraps*, but the aggregate
does. Two ordinary Fiji datasets at lon 179 and -179 used to roll up to
``-180..180`` --- a global bbox for two footprints 2 degrees apart --- because
the min/max fold spans the globe the wrong way.

The fix aggregates in two longitude domains (as stored, and ``+360``-shifted)
and keeps whichever range is narrower, so ``rollup_bbox`` emits the RFC 7946
§5.2 ``west > east`` pair when that is the honest answer and
``rollup_span_bbox`` keeps the over-broad-but-monotonic form for consumers that
cannot express a crossing box.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2 import WKTElement
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.geo import (
    bbox_to_extent_wkt,
    merge_bboxes,
    rollup_bbox,
    rollup_bbox_columns,
    rollup_span_bbox,
    wrap_longitude,
)
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from tests.factories import get_user_id

# Two ordinary Fiji-area datasets, one either side of the seam, over ONE
# latitude band. The reported case.
FIJI_WEST = "POLYGON((178.5 -20,179.5 -20,179.5 -15,178.5 -15,178.5 -20))"
FIJI_EAST = "POLYGON((-179.5 -20,-178.5 -20,-178.5 -15,-179.5 -15,-179.5 -20))"

# What a 0..360 Pacific source spanning 150..250 becomes once
# ``clip_to_mercator_bounds`` shifts it into -180..180 (#888/#899): half on each
# side of the seam. A bare ST_Extent over it reads -170..170 --- 340 degrees for
# a 100-degree footprint.
PACIFIC_WEST = "POLYGON((150 -5,170 -5,170 5,150 5,150 -5))"
PACIFIC_EAST = "POLYGON((-170 -5,-110 -5,-110 5,-170 5,-170 -5))"

# A single record already stored in the two-ring seam form (#892).
FIJI_SEAM_MULTIPOLYGON = bbox_to_extent_wkt(170.0, -20.0, -170.0, -15.0)

# Crosses the prime meridian, over the same latitude band as the Fiji pair.
# ST_ShiftLongitude tears this one apart vertex-by-vertex, so the rollup must
# translate the whole footprint instead.
EUROPE_LIKE = "POLYGON((-10 -20,30 -20,30 -15,-10 -15,-10 -20))"

# The same shape with mantissas that survive neither +360 nor -360 intact. Found
# by brute force; it is the case where the two domains measure the same footprint
# differently and the shifted one wins on noise alone.
_UGLY_W, _UGLY_E = -4.761789777127049, 33.035082006073026
_UGLY_S, _UGLY_N = -74.15992890150827, -69.77548044709921
UGLY_MERIDIAN_CROSSER = (
    f"POLYGON(({_UGLY_W} {_UGLY_S},{_UGLY_E} {_UGLY_S},{_UGLY_E} {_UGLY_N},"
    f"{_UGLY_W} {_UGLY_N},{_UGLY_W} {_UGLY_S}))"
)


# ---------------------------------------------------------------------------
# merge_bboxes / rollup_bbox arithmetic (no DB)
# ---------------------------------------------------------------------------


def _span(bbox: list[float]) -> float:
    """Longitude width of a possibly-crossing bbox."""
    west, east = bbox[0], bbox[2]
    return east - west if west <= east else east + 360.0 - west


class TestWrapLongitude:
    def test_shifted_domain_folds_back(self):
        assert wrap_longitude(181.5) == -178.5
        assert wrap_longitude(390.0) == 30.0

    def test_in_range_values_and_the_seam_itself_are_untouched(self):
        assert wrap_longitude(0.0) == 0.0
        assert wrap_longitude(-179.0) == -179.0
        # 180 must not flip to -180: it is a legitimate eastern edge.
        assert wrap_longitude(180.0) == 180.0

    def test_below_range_folds_up(self):
        assert wrap_longitude(-190.0) == 170.0


class TestMergeBboxes:
    def test_fiji_pair_yields_west_greater_than_east(self):
        """The reported case: 359 degrees of nothing becomes 3 degrees of Fiji."""
        merged = merge_bboxes([[178.5, -20, 179.5, -15], [-179.5, -20, -178.5, -15]])
        assert merged == [178.5, -20.0, -178.5, -15.0]
        assert merged[0] > merged[2]
        assert _span(merged) == pytest.approx(3.0)

    def test_a_tie_keeps_the_unshifted_domain(self):
        """Records at 0 and 170 span 170 either way; nothing may be inverted."""
        merged = merge_bboxes([[0, 0, 10, 5], [160, 0, 170, 5]])
        assert merged == [0.0, 0.0, 170.0, 5.0]
        assert merged[0] < merged[2]

    def test_three_footprints_get_a_valid_covering_range(self):
        merged = merge_bboxes([[-170, 0, -169, 1], [0, 0, 1, 1], [169, 0, 170, 1]])
        assert merged == [0.0, 0.0, -169.0, 1.0]
        assert _span(merged) == pytest.approx(191.0)

    def test_a_crossing_input_bbox_merges_with_a_neighbour(self):
        """Inputs may themselves be west > east (extent_to_bbox of a seam form)."""
        merged = merge_bboxes([[170, -20, -170, -15], [160, -25, 165, -15]])
        assert merged == [160.0, -25.0, -170.0, -15.0]
        assert _span(merged) == pytest.approx(30.0)

    def test_prime_meridian_crosser_is_shifted_as_one_piece(self):
        """A per-vertex shift would claim 30..350 for Europe and then emit a
        bbox that excludes Europe itself. Shifting the whole interval keeps the
        result covering."""
        merged = merge_bboxes(
            [[-10, -20, 30, -15], [178.5, -20, 179.5, -15], [-179.5, -20, -178.5, -15]]
        )
        assert merged == [178.5, -20.0, 30.0, -15.0]
        assert _span(merged) == pytest.approx(211.5)
        # Covering: Europe's west edge sits inside the emitted range.
        assert merged[0] > merged[2]
        assert -10.0 <= merged[2]

    def test_documented_ceiling_is_covering_but_not_minimal(self):
        """Both cut points fall inside data, so neither domain finds the largest
        gap (-160..-20, worth a 220-degree cover). 325 degrees instead --- valid,
        just broad. Closing that needs a largest-gap-on-a-circle search,
        deliberately out of scope."""
        merged = merge_bboxes(
            [
                [-170, 0, -160, 1],
                [-20, 0, -15, 1],
                [20, 0, 25, 1],
                [160, 0, 165, 1],
            ]
        )
        assert merged == [20.0, 0.0, -15.0, 1.0]
        assert _span(merged) == pytest.approx(325.0)

    def test_wholly_western_footprints_are_untouched(self):
        assert merge_bboxes([[-170, 0, -160, 5], [-120, 1, -110, 6]]) == [
            -170.0,
            0.0,
            -110.0,
            6.0,
        ]

    def test_empty_and_missing_inputs(self):
        assert merge_bboxes([]) is None
        assert merge_bboxes([None, None]) is None
        assert merge_bboxes([None, [1, 2, 3, 4]]) == [1.0, 2.0, 3.0, 4.0]
        # A short row is skipped rather than crashing the fold.
        assert merge_bboxes([[1, 2], [1, 2, 3, 4]]) == [1.0, 2.0, 3.0, 4.0]


class TestRollupRowHelpers:
    def test_spec_form_and_span_form_diverge_only_when_crossing(self):
        crossing = [-180.0, -20.0, 180.0, -15.0, 178.5, 181.5]
        assert rollup_bbox(crossing) == [178.5, -20.0, -178.5, -15.0]
        assert rollup_span_bbox(crossing) == [-180.0, -20.0, 180.0, -15.0]

        plain = [0.0, 0.0, 10.0, 5.0, 0.0, 10.0]
        assert rollup_bbox(plain) == rollup_span_bbox(plain) == [0.0, 0.0, 10.0, 5.0]

    def test_a_genuinely_global_rollup_stays_global(self):
        """A -180..180 footprint shifts to 180..540: same 360-degree span, so the
        tie keeps the unshifted domain instead of inventing a crossing box."""
        values = [-180.0, -90.0, 180.0, 90.0, 180.0, 540.0]
        assert rollup_bbox(values) == [-180.0, -90.0, 180.0, 90.0]

    def test_null_and_short_rows_return_none(self):
        assert rollup_bbox([None, None, None, None, None, None]) is None
        assert rollup_span_bbox([1.0, 2.0, 3.0, 4.0, 5.0, None]) is None
        assert rollup_bbox([1.0, 2.0, 3.0]) is None
        assert rollup_bbox(None) is None

    def test_float_noise_cannot_flip_a_prime_meridian_extent(self):
        """A Europe-shaped extent measures the *same* span in both domains, but
        not to the last bit: `(-4.761789777127049 + 360) - 360` comes back as
        `-4.761789777127035`, and the shifted span computed 37.79687178320006
        against a normal 37.796871783200075. Without _DOMAIN_MARGIN that noise
        wins the comparison and rewrites an ordinary, non-crossing bbox with
        drifted edges. Found by brute-forcing the covering property over random
        footprint sets."""
        west, east = -4.761789777127049, 33.035082006073026
        assert (east + 360.0) - (west + 360.0) < east - west  # the noise itself

        bbox = rollup_bbox([west, -74.1, east, -69.7, west + 360.0, east + 360.0])
        # Byte-identical to the input, not the round-tripped approximation.
        assert bbox == [west, -74.1, east, -69.7]
        assert bbox[0] != wrap_longitude(west + 360.0)

    def test_a_real_narrowing_still_beats_the_margin(self):
        """The margin must not swallow a genuine improvement. A tenth of a degree
        is eight orders of magnitude above it.

        This one also pins the documented residual: `359.95 - 360` is
        `-0.05000000000001137`, so a winning shifted edge can sit ~1e-14 degrees
        (a few nanometres) inside the true union. Correcting that soundly means
        widening every crossing edge unconditionally, which would put the same
        noise into the exact cases for no operational gain.
        """
        values = [-180.0, 0.0, 180.0, 1.0, 0.05, 359.95]
        bbox = rollup_bbox(values)
        assert bbox == pytest.approx([0.05, 0.0, -0.05, 1.0])
        assert bbox[0] > bbox[2]
        assert abs(bbox[2] - -0.05) < 6e-14


# ---------------------------------------------------------------------------
# The SQL fold (rollup_bbox_columns) against live PostGIS
# ---------------------------------------------------------------------------


async def _insert_records(session, wkts: list[str]) -> list[uuid.UUID]:
    """Insert bare published records carrying the given extents."""
    ids: list[uuid.UUID] = []
    created_by = await get_user_id(session, "admin")
    for wkt in wkts:
        record = Record(
            title=f"rollup-{uuid.uuid4()}",
            visibility="public",
            record_status="published",
            record_type="vector_dataset",
            created_by=created_by,
            spatial_extent=WKTElement(wkt, srid=4326),
        )
        session.add(record)
        await session.flush()
        ids.append(record.id)
    await session.commit()
    return ids


async def _sql_rollup(session, ids: list[uuid.UUID]) -> list[float] | None:
    """Run the aggregate the routers run, scoped to the given records."""
    stmt = select(*rollup_bbox_columns(Record.spatial_extent)).where(Record.id.in_(ids))
    row = (await session.execute(stmt)).one()
    return rollup_bbox(row[:6])


@pytest.mark.anyio
class TestSqlRollup:
    async def test_fiji_pair_no_longer_folds_to_a_global_bbox(
        self, test_db_session, clean_tables
    ):
        del clean_tables
        ids = await _insert_records(test_db_session, [FIJI_WEST, FIJI_EAST])
        assert await _sql_rollup(test_db_session, ids) == [178.5, -20.0, -178.5, -15.0]

    async def test_shifted_pacific_source_measures_its_own_footprint(
        self, test_db_session, clean_tables
    ):
        """The other half of ``clip_to_mercator_bounds`` (#888/#899).

        ``test_pacific_crossing_source_is_preserved_with_a_naive_extent`` pins
        the raw ``ST_Extent`` at -170..170 for a 150..250 source, and says the
        340-degree reading is the extent fold this issue owns. Same footprint,
        rolled up here: 100 degrees, west > east.
        """
        del clean_tables
        ids = await _insert_records(test_db_session, [PACIFIC_WEST, PACIFIC_EAST])

        naive = (
            await test_db_session.execute(
                text(
                    "SELECT ST_XMin(bb), ST_XMax(bb) FROM (SELECT "
                    "ST_Extent(spatial_extent) AS bb FROM catalog.records "
                    "WHERE id = ANY(:ids)) q"
                ).bindparams(ids=ids)
            )
        ).one()
        assert (float(naive[0]), float(naive[1])) == pytest.approx((-170.0, 170.0))

        bbox = await _sql_rollup(test_db_session, ids)
        assert bbox == [150.0, -5.0, -110.0, 5.0]
        assert _span(bbox) == pytest.approx(100.0)

    async def test_stored_seam_form_record_rolls_up_to_its_own_bbox(
        self, test_db_session, clean_tables
    ):
        """A single two-ring record reads -180..180 planar; the shifted domain
        recovers the 20-degree strip it actually describes."""
        del clean_tables
        ids = await _insert_records(test_db_session, [FIJI_SEAM_MULTIPOLYGON])
        assert await _sql_rollup(test_db_session, ids) == [170.0, -20.0, -170.0, -15.0]

    async def test_seam_form_plus_a_neighbour_west_of_the_seam(
        self, test_db_session, clean_tables
    ):
        del clean_tables
        ids = await _insert_records(
            test_db_session,
            [
                FIJI_SEAM_MULTIPOLYGON,
                "POLYGON((160 -25,165 -25,165 -15,160 -15,160 -25))",
            ],
        )
        assert await _sql_rollup(test_db_session, ids) == [160.0, -25.0, -170.0, -15.0]

    async def test_prime_meridian_crosser_keeps_the_rollup_covering(
        self, test_db_session, clean_tables
    ):
        """A bare ``ST_ShiftLongitude`` second domain shifts each *vertex*, so a
        Europe-like footprint becomes the pair (350, 30) and the rollup emits
        30..-10 --- a bbox that excludes Europe. Verified against PostGIS:
        ``covers-all-inputs=False``. The guarded expression translates whole
        footprints that reach the prime meridian instead.
        """
        del clean_tables
        ids = await _insert_records(
            test_db_session, [EUROPE_LIKE, FIJI_WEST, FIJI_EAST]
        )
        bbox = await _sql_rollup(test_db_session, ids)
        assert bbox == [178.5, -20.0, 30.0, -15.0]

        # Ask PostGIS whether the emitted range really covers every record.
        covered = (
            await test_db_session.execute(
                text(
                    "SELECT bool_and(ST_CoveredBy(spatial_extent, "
                    "ST_GeomFromText(:cover, 4326))) FROM catalog.records "
                    "WHERE id = ANY(:ids)"
                ).bindparams(cover=bbox_to_extent_wkt(*bbox), ids=ids)
            )
        ).scalar_one()
        assert covered is True

    async def test_postgis_shows_the_same_last_bit_asymmetry(
        self, test_db_session, clean_tables
    ):
        """The margin is needed on the SQL side too, not just the Python fold.

        ``ST_Translate(g, 360, 0)`` rounds exactly like Python's ``x + 360``, so
        PostGIS hands back a shifted span of 37.79687178320006 against an
        unshifted 37.796871783200075 for the same footprint --- a bare ``<``
        picks the shifted domain for an extent that never crosses the seam. Both
        paths funnel through one ``_narrower_domain``, so one margin covers
        both; this pins that the *inputs* really do disagree, which is the part
        a Python-only unit test cannot show.
        """
        del clean_tables
        ids = await _insert_records(test_db_session, [UGLY_MERIDIAN_CROSSER])
        row = (
            await test_db_session.execute(
                select(*rollup_bbox_columns(Record.spatial_extent)).where(
                    Record.id.in_(ids)
                )
            )
        ).one()
        xmin, xmax, sxmin, sxmax = (float(row[i]) for i in (0, 2, 4, 5))

        # PostGIS itself disagrees with itself, in the direction that matters.
        assert sxmax - sxmin < xmax - xmin
        # ...but not by enough to clear the margin, so the extent is untouched.
        assert rollup_bbox(row[:6]) == [xmin, float(row[1]), xmax, float(row[3])]
        assert rollup_bbox(row[:6])[0] != wrap_longitude(sxmin)

    async def test_a_non_crossing_catalog_is_unchanged(
        self, test_db_session, clean_tables
    ):
        """The regression guard: ordinary catalogs must fold exactly as before."""
        del clean_tables
        ids = await _insert_records(
            test_db_session,
            [
                "POLYGON((-74.1 40.5,-73.7 40.5,-73.7 40.9,-74.1 40.9,-74.1 40.5))",
                "POLYGON((-118.5 33.7,-117.9 33.7,-117.9 34.1,-118.5 34.1,-118.5 33.7))",
            ],
        )
        assert await _sql_rollup(test_db_session, ids) == [
            -118.5,
            33.7,
            -73.7,
            40.9,
        ]

    async def test_span_form_never_inverts(self, test_db_session, clean_tables):
        del clean_tables
        ids = await _insert_records(test_db_session, [FIJI_WEST, FIJI_EAST])
        stmt = select(*rollup_bbox_columns(Record.spatial_extent)).where(
            Record.id.in_(ids)
        )
        row = (await test_db_session.execute(stmt)).one()
        assert rollup_span_bbox(row[:6]) == [-180.0, -20.0, 180.0, -15.0]

    async def test_no_visible_records_yields_no_extent(
        self, test_db_session, clean_tables
    ):
        del clean_tables
        assert await _sql_rollup(test_db_session, [uuid.uuid4()]) is None


@pytest.mark.anyio
async def test_rolled_up_bbox_covers_the_data_and_not_the_complement(
    test_db_session, clean_tables
):
    """The area/complement property, not just the numbers.

    Round-tripping both bboxes through ``bbox_to_extent_wkt`` shows the cost of
    the old fold: 1795 deg² sweeping the whole -20..-15 band versus 15 deg²
    over Fiji. The negative probe sits in that **same latitude band** and differs
    only in longitude (mid-Pacific, the far side of the seam) --- a probe that
    also differed in latitude would pass before and after the fix and prove
    nothing.
    """
    del clean_tables
    ids = await _insert_records(test_db_session, [FIJI_WEST, FIJI_EAST])
    stmt = select(*rollup_bbox_columns(Record.spatial_extent)).where(Record.id.in_(ids))
    row = (await test_db_session.execute(stmt)).one()
    bbox = rollup_bbox(row[:6])
    naive = [float(row[0]), float(row[1]), float(row[2]), float(row[3])]

    probe = (
        await test_db_session.execute(
            text(
                "SELECT ST_Area(ST_GeomFromText(:rolled, 4326)) AS rolled_area,"
                " ST_Area(ST_GeomFromText(:naive, 4326)) AS naive_area,"
                " ST_Intersects(ST_GeomFromText(:rolled, 4326),"
                "   ST_MakeEnvelope(178.6, -19, 179.4, -16, 4326)) AS hits_fiji_west,"
                " ST_Intersects(ST_GeomFromText(:rolled, 4326),"
                "   ST_MakeEnvelope(-179.4, -19, -178.6, -16, 4326)) AS hits_fiji_east,"
                " ST_Intersects(ST_GeomFromText(:rolled, 4326),"
                "   ST_MakeEnvelope(-150, -19, -140, -16, 4326)) AS hits_mid_pacific,"
                " ST_Intersects(ST_GeomFromText(:naive, 4326),"
                "   ST_MakeEnvelope(-150, -19, -140, -16, 4326)) AS naive_hits_pacific"
            ).bindparams(
                rolled=bbox_to_extent_wkt(*bbox),
                naive=bbox_to_extent_wkt(*naive),
            )
        )
    ).one()

    # 3 degrees of longitude over a 5-degree band, not 359 over the same band.
    assert float(probe.rolled_area) == pytest.approx(15.0)
    assert float(probe.naive_area) == pytest.approx(1795.0)
    assert probe.hits_fiji_west is True
    assert probe.hits_fiji_east is True
    # The discriminating assertion: same latitude band, wrong side of the seam.
    assert probe.hits_mid_pacific is False
    assert probe.naive_hits_pacific is True


# ---------------------------------------------------------------------------
# Which surface gets which form
# ---------------------------------------------------------------------------


async def _seed_crossing_collection(session) -> tuple[Collection, list[uuid.UUID]]:
    """A Collection holding two published raster datasets either side of the seam."""
    coll = Collection(name=f"Fiji Seam {uuid.uuid4().hex[:8]}", description="Rollup")
    session.add(coll)
    created_by = await get_user_id(session, "admin")
    dataset_ids: list[uuid.UUID] = []
    for wkt in (FIJI_WEST, FIJI_EAST):
        record = Record(
            title=f"rollup-{uuid.uuid4()}",
            visibility="public",
            record_status="published",
            record_type="raster_dataset",
            created_by=created_by,
            spatial_extent=WKTElement(wkt, srid=4326),
        )
        session.add(record)
        await session.flush()
        dataset = Dataset(
            record_id=record.id,
            table_name=f"ds_{uuid.uuid4().hex[:12]}",
            srid=4326,
            source_format="geotiff",
            source_filename="test.tif",
        )
        session.add(dataset)
        await session.flush()
        session.add(CollectionDataset(collection_id=coll.id, dataset_id=dataset.id))
        dataset_ids.append(dataset.id)
    await session.commit()
    await session.refresh(coll)
    return coll, dataset_ids


@pytest.mark.anyio
async def test_stac_collection_extent_uses_the_spec_west_greater_than_east_form(
    client: AsyncClient, test_db_session
):
    """STAC inherits RFC 7946 §5.2, so a crossing Collection extent is west > east.

    Covers both STAC rollup sites: the per-collection detail query and the
    grouped listing query, which share ``_parse_extent_row``.
    """
    coll, _ = await _seed_crossing_collection(test_db_session)

    detail = await client.get(f"/stac/collections/{coll.id}")
    assert detail.status_code == 200
    bbox = detail.json()["extent"]["spatial"]["bbox"][0]
    assert bbox == [178.5, -20.0, -178.5, -15.0]
    assert bbox[0] > bbox[2]

    listing = await client.get("/stac/collections")
    assert listing.status_code == 200
    entry = next(c for c in listing.json()["collections"] if c["id"] == str(coll.id))
    assert entry["extent"]["spatial"]["bbox"][0] == [178.5, -20.0, -178.5, -15.0]


@pytest.mark.anyio
async def test_collections_api_extent_bbox_uses_the_spec_form(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """``CollectionResponse.extent_bbox`` is the RFC 7946 §5.2 pair.

    fix(#1006): this pinned the monotonic span form under #886, when
    CollectionCard's BBoxPreview had no crossing guard. #903 added one
    (``crossesAntimeridian``, ``splitBbox``), and the span form then defeated
    it: ``rollup_span_bbox`` collapses a crossing rollup to
    ``[-180, s, 180, n]``, which is bit-identical to what a genuinely global
    collection produces, so no client-side test could tell them apart and a
    Fiji-shaped collection drew a band across the whole world.

    Rewritten rather than deleted --- it is the contract pin for this field, and
    it now pins the opposite half of the same contract. Mirrors the sibling
    per-dataset ``extent_bbox``, flipped in #1004."""
    coll, _ = await _seed_crossing_collection(test_db_session)

    resp = await client.get(
        f"/catalog/collections/{coll.id}", headers=admin_auth_header
    )
    assert resp.status_code == 200
    bbox = resp.json()["extent_bbox"]
    assert bbox == [178.5, -20.0, -178.5, -15.0]
    assert bbox[0] > bbox[2]


@pytest.mark.anyio
async def test_ogc_catalog_collection_extent_comes_from_the_rollup_helper(
    test_db_session,
):
    """The OGC "datasets" collection extent is catalog-wide, so its value depends
    on whatever else the session DB holds. Pin the wiring instead: the builder
    must return ``rollup_bbox`` over the same anonymous-visible aggregate, which
    the old GeoJSON min/max fold cannot satisfy whenever the catalog crosses.
    """
    from app.modules.catalog.search import router as search_router

    search_router._COLLECTION_META_CACHE.clear()
    ids = await _insert_records(test_db_session, [FIJI_WEST, FIJI_EAST])
    # Deterministic, independent of the rest of the catalog.
    assert await _sql_rollup(test_db_session, ids) == [178.5, -20.0, -178.5, -15.0]

    stmt = (
        select(*rollup_bbox_columns(Record.spatial_extent))
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id)
    )
    stmt = apply_visibility_filter(stmt, None, set(), Record, DatasetGrant)
    expected = rollup_bbox((await test_db_session.execute(stmt)).one()[:6])

    meta = await search_router._build_collection_metadata(
        test_db_session, None, "https://api.example.test"
    )
    search_router._COLLECTION_META_CACHE.clear()
    served = meta.get("extent", {}).get("spatial", {}).get("bbox")
    assert (served[0] if served else None) == expected


def _map_spec(center_lng: float, center_lat: float = -17.5):
    from app.processing.ai.schemas import LLMLayerSpec, LLMMapSpec

    return LLMMapSpec(
        name="Fiji",
        center_lng=center_lng,
        center_lat=center_lat,
        zoom=6.0,
        layers=[LLMLayerSpec(dataset_id=str(uuid.uuid4()))],
    )


class TestAiViewportSnap:
    """``spec.center_lng`` used to be overwritten with the centroid of a global
    bbox --- lon 0, the Gulf of Guinea --- whenever the layer datasets sat
    either side of the seam. The margin comparison also has to run in the
    unwrapped domain, or a centre that *is* over the data reads as outside it.
    """

    @staticmethod
    def _snap(spec, wkts: list[str]) -> None:
        from app.processing.ai.service import _snap_viewport_to_extent

        _snap_viewport_to_extent(spec, [WKTElement(w, srid=4326) for w in wkts])

    def test_crossing_layers_no_longer_snap_to_the_gulf_of_guinea(self):
        spec = _map_spec(2.0)
        self._snap(spec, [FIJI_WEST, FIJI_EAST])
        assert spec.center_lng == pytest.approx(180.0)
        assert spec.center_lat == pytest.approx(-17.5)

    @pytest.mark.parametrize("lng", [179.5, -179.5, 179.0])
    def test_a_centre_over_crossing_data_is_left_alone(self, lng):
        spec = _map_spec(lng)
        self._snap(spec, [FIJI_WEST, FIJI_EAST])
        assert spec.center_lng == pytest.approx(lng)

    def test_non_crossing_layers_keep_the_previous_behaviour(self):
        nyc = "POLYGON((-74.1 40.5,-73.7 40.5,-73.7 40.9,-74.1 40.9,-74.1 40.5))"
        inside = _map_spec(-73.9, 40.7)
        self._snap(inside, [nyc])
        assert inside.center_lng == pytest.approx(-73.9)

        outside = _map_spec(2.0, 47.0)
        self._snap(outside, [nyc])
        assert outside.center_lng == pytest.approx(-73.9)
        assert outside.center_lat == pytest.approx(40.7)

    def test_a_centre_just_inside_the_margin_of_a_normal_extent_survives(self):
        """The unwrap must not fire for a monotonic extent, or a nearby centre
        would be shifted +360 and read as far outside."""
        spec = _map_spec(-3.0, 2.0)
        self._snap(spec, ["POLYGON((0 0,10 0,10 5,0 5,0 0))"])
        assert spec.center_lng == pytest.approx(-3.0)

    def test_no_extents_leaves_the_spec_untouched(self):
        spec = _map_spec(2.0)
        from app.processing.ai.service import _snap_viewport_to_extent

        _snap_viewport_to_extent(spec, [None, None])
        assert spec.center_lng == pytest.approx(2.0)
