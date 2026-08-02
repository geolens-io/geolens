"""fix(#892): antimeridian-crossing extent representation.

``catalog.records.spatial_extent`` used to be ``geometry(Polygon, 4326)``, which
cannot hold the west > east bbox RFC 7946 §5.2 and STAC use for a crossing
extent. It is now generic ``geometry(Geometry, 4326)`` guarded by
``chk_records_spatial_extent_type``, a seam-crossing extent is stored as a
two-ring MULTIPOLYGON, and ``extent_to_bbox`` reads that back as west > east
while ``extent_to_span_bbox`` keeps monotonic bounds for consumers that cannot
take an inverted pair.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from geoalchemy2 import WKBElement, WKTElement
from geoalchemy2.shape import from_shape
from shapely import wkt as shapely_wkt
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.geo import bbox_to_extent_wkt, extent_to_bbox, extent_to_span_bbox

# The canonical crossing case: a Fiji-area strip that spans the seam.
FIJI_BBOX = (170.0, -20.0, -170.0, -15.0)

# fix(#944): the sliver bbox_to_extent_wkt widens a degenerate axis to.
PAD = 1e-9

ORDINARY_POLYGON = "POLYGON((0 0,10 0,10 5,0 5,0 0))"
SEAM_MULTIPOLYGON = bbox_to_extent_wkt(*FIJI_BBOX)
# Two real footprints on opposite sides of the world. Neither touches ±180, so
# nothing about it may be read as a seam split.
NON_SEAM_MULTIPOLYGON = (
    "MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)),((10 0,11 0,11 1,10 1,10 0)))"
)
# Both halves touch the seam, but over unrelated latitude bands — two separate
# footprints, not one crossing box.
SEAM_TOUCHING_DIFFERENT_LATITUDES = (
    "MULTIPOLYGON(((170 -20,180 -20,180 -15,170 -15,170 -20)),"
    "((-180 50,-170 50,-170 55,-180 55,-180 50)))"
)
# get_extent() pads a POINT/LINESTRING source into a tiny square so it satisfies
# the polygon shape; that padding must survive both helpers untouched.
DEGENERATE_PADDED_ENVELOPE = (
    "POLYGON((-0.001 -0.001,0.001 -0.001,0.001 0.001,-0.001 0.001,-0.001 -0.001))"
)


def _extent(wkt: str) -> WKBElement:
    """Build the WKB element form a loaded ORM column value actually has.

    SQLAlchemy hands ``Record.spatial_extent`` to these helpers as a
    ``WKBElement``, so the unit tests exercise that path rather than the WKT one
    that only appears when a test hand-writes a literal.
    """
    return from_shape(shapely_wkt.loads(wkt), srid=4326)


# ---------------------------------------------------------------------------
# extent_to_bbox / extent_to_span_bbox
# ---------------------------------------------------------------------------


class TestExtentToBbox:
    def test_ordinary_polygon_is_plain_bounds(self):
        assert extent_to_bbox(_extent(ORDINARY_POLYGON)) == [0.0, 0.0, 10.0, 5.0]

    def test_seam_crossing_multipolygon_returns_west_greater_than_east(self):
        bbox = extent_to_bbox(_extent(SEAM_MULTIPOLYGON))
        assert bbox == [170.0, -20.0, -170.0, -15.0]
        assert bbox[0] > bbox[2]

    def test_genuine_two_part_multipolygon_is_not_mistaken_for_a_crosser(self):
        bbox = extent_to_bbox(_extent(NON_SEAM_MULTIPOLYGON))
        assert bbox == [0.0, 0.0, 11.0, 1.0]
        assert bbox[0] < bbox[2]

    def test_seam_halves_over_different_latitudes_are_not_a_crosser(self):
        bbox = extent_to_bbox(_extent(SEAM_TOUCHING_DIFFERENT_LATITUDES))
        assert bbox == [-180.0, -20.0, 180.0, 55.0]

    def test_whole_world_polygon_is_not_a_crosser(self):
        whole = "POLYGON((-180 -90,180 -90,180 90,-180 90,-180 -90))"
        assert extent_to_bbox(_extent(whole)) == [-180.0, -90.0, 180.0, 90.0]

    def test_degenerate_padded_envelope_is_unchanged(self):
        assert extent_to_bbox(_extent(DEGENERATE_PADDED_ENVELOPE)) == [
            -0.001,
            -0.001,
            0.001,
            0.001,
        ]

    def test_three_part_multipolygon_containing_a_seam_pair_is_not_a_crosser(self):
        """The detector keys on exactly two parts; a third part means the pair is
        no longer the whole extent, so the honest answer is the planar bounds."""
        three = (
            "MULTIPOLYGON(((170 -20,180 -20,180 -15,170 -15,170 -20)),"
            "((-180 -20,-170 -20,-170 -15,-180 -15,-180 -20)),"
            "((0 0,1 0,1 1,0 1,0 0)))"
        )
        assert extent_to_bbox(_extent(three)) == [-180.0, -20.0, 180.0, 1.0]

    def test_wkt_element_form_agrees_with_the_wkb_form(self):
        """to_shape accepts both element types; the detector must not care which."""
        assert extent_to_bbox(WKTElement(SEAM_MULTIPOLYGON, srid=4326)) == [
            170.0,
            -20.0,
            -170.0,
            -15.0,
        ]

    def test_none_and_garbage_return_none(self):
        assert extent_to_bbox(None) is None
        assert extent_to_bbox("not-a-geometry") is None
        assert extent_to_bbox(object()) is None


class TestExtentToSpanBbox:
    def test_ordinary_polygon_matches_the_spec_helper(self):
        el = _extent(ORDINARY_POLYGON)
        assert extent_to_span_bbox(el) == extent_to_bbox(el)

    def test_seam_crossing_multipolygon_stays_monotonic(self):
        bbox = extent_to_span_bbox(_extent(SEAM_MULTIPOLYGON))
        # Over-broad, but never inverted — the property tile/WKT consumers need.
        assert bbox == [-180.0, -20.0, 180.0, -15.0]
        assert bbox[0] < bbox[2]

    def test_degenerate_padded_envelope_is_unchanged(self):
        assert extent_to_span_bbox(_extent(DEGENERATE_PADDED_ENVELOPE)) == [
            -0.001,
            -0.001,
            0.001,
            0.001,
        ]

    def test_none_and_garbage_return_none(self):
        assert extent_to_span_bbox(None) is None
        assert extent_to_span_bbox("not-a-geometry") is None


class TestBboxToExtentWkt:
    def test_non_crossing_bbox_stays_a_single_polygon_ring(self):
        assert bbox_to_extent_wkt(1, 2, 3, 4) == "POLYGON((1 2,3 2,3 4,1 4,1 2))"

    def test_crossing_bbox_becomes_two_rings_split_at_180(self):
        shape = shapely_wkt.loads(bbox_to_extent_wkt(*FIJI_BBOX))
        assert shape.geom_type == "MultiPolygon"
        assert len(shape.geoms) == 2
        assert shape.is_valid
        # One half runs west..180, the other -180..east, over the same latitudes.
        halves = sorted(g.bounds for g in shape.geoms)
        assert halves == [(-180.0, -20.0, -170.0, -15.0), (170.0, -20.0, 180.0, -15.0)]

    def test_round_trips_through_extent_to_bbox(self):
        """The producer/reader pair is the contract every downstream fix leans on."""
        for bbox in (FIJI_BBOX, (1.0, 2.0, 3.0, 4.0), (179.5, 0.0, -179.5, 1.0)):
            wkt = bbox_to_extent_wkt(*bbox)
            assert extent_to_bbox(_extent(wkt)) == list(bbox)

    @pytest.mark.parametrize(
        ("bbox", "expected_type", "expected_bounds"),
        [
            # west sits on the seam: the west..180 half has zero width.
            ((180.0, -20.0, -170.0, -15.0), "Polygon", (-180.0, -20.0, -170.0, -15.0)),
            # east sits on the seam: the -180..east half has zero width.
            ((170.0, -20.0, -180.0, -15.0), "Polygon", (170.0, -20.0, 180.0, -15.0)),
            # Both ends on the seam: fall back to the full band, never to nothing.
            ((180.0, -20.0, -180.0, -15.0), "Polygon", (-180.0, -20.0, 180.0, -15.0)),
        ],
    )
    def test_degenerate_crossing_halves_never_produce_an_invalid_ring(
        self, bbox, expected_type, expected_bounds
    ):
        """A remote bbox with west == 180 (or east == -180) would otherwise emit a
        zero-width ring — an invalid geometry, the exact defect class this helper
        exists to prevent.

        fix(#934 codex r2): the zero-width half is dropped here, and that stays
        right for this helper's callers, which all pass a continuous rectangle
        (a raster footprint, a STAC item bbox) with nothing in the dropped half
        to lose. The discrete-row case, where a feature really does sit at the
        planar +180 the surviving ring misses, is padded upstream by
        ``seam_extent_wkt_for_table`` — see
        ``test_extent_producers_934.TestGetExtent``.
        """
        shape = shapely_wkt.loads(bbox_to_extent_wkt(*bbox))
        assert shape.is_valid
        assert shape.geom_type == expected_type
        assert shape.bounds == expected_bounds

    @pytest.mark.parametrize(
        ("bbox", "expected_type", "expected_bounds"),
        [
            # A run of points on one parallel: zero height, non-crossing.
            ((1.0, 2.0, 3.0, 2.0), "Polygon", (1.0, 2.0 - PAD, 3.0, 2.0 + PAD)),
            # The same, crossing the seam — both halves must stay valid.
            (
                (170.0, -20.0, -170.0, -20.0),
                "MultiPolygon",
                (-180.0, -20.0 - PAD, 180.0, -20.0 + PAD),
            ),
            # A meridian-aligned run: zero width, non-crossing.
            ((5.0, 1.0, 5.0, 4.0), "Polygon", (5.0 - PAD, 1.0, 5.0 + PAD, 4.0)),
            # A single point: degenerate on both axes at once.
            (
                (5.0, 6.0, 5.0, 6.0),
                "Polygon",
                (5.0 - PAD, 6.0 - PAD, 5.0 + PAD, 6.0 + PAD),
            ),
            # On the antimeridian, where an outward pad would leave the domain:
            # the sliver grows inward instead of emitting longitude 180.000…001.
            ((180.0, 1.0, 180.0, 4.0), "Polygon", (180.0 - PAD, 1.0, 180.0, 4.0)),
            ((-180.0, 1.0, -180.0, 4.0), "Polygon", (-180.0, 1.0, -180.0 + PAD, 4.0)),
            # The same at a pole.
            ((1.0, 90.0, 3.0, 90.0), "Polygon", (1.0, 90.0 - PAD, 3.0, 90.0)),
            ((1.0, -90.0, 3.0, -90.0), "Polygon", (1.0, -90.0, 3.0, -90.0 + PAD)),
        ],
    )
    def test_degenerate_span_is_padded_to_a_valid_ring(
        self, bbox, expected_type, expected_bounds
    ):
        """fix(#944): a zero-span axis builds four collinear points — zero area,
        and not a valid polygon.

        Only the width case was guarded before, and only on the crossing
        branch, so a single-parallel source stored an invalid ring through the
        STAC import path. Pad both axes on both branches, following the
        ``ST_Expand`` convention the producer paths already use.
        """
        shape = shapely_wkt.loads(bbox_to_extent_wkt(*bbox))
        assert shape.is_valid
        assert shape.geom_type == expected_type
        assert shape.bounds == pytest.approx(expected_bounds)
        assert shape.area > 0

    @pytest.mark.parametrize(
        "bbox",
        [
            FIJI_BBOX,
            (1.0, 2.0, 3.0, 4.0),
            (179.5, 0.0, -179.5, 1.0),
            (0.0, 0.0, 1e-9, 1e-9),
        ],
    )
    def test_padding_never_moves_a_genuine_bbox(self, bbox):
        """The pad triggers below 1e-12, so a real extent round-trips exactly.

        The last case is the tightest bbox the ``ST_Expand`` producers emit: it
        must be treated as genuine, not re-padded.
        """
        assert extent_to_bbox(_extent(bbox_to_extent_wkt(*bbox))) == list(bbox)

    @pytest.mark.parametrize(
        "bbox",
        [
            # NaN latitude: falls past the span test into the clamp, where
            # max/min substitute -90/+90.
            (1.0, float("nan"), 3.0, float("nan")),
            # NaN longitude: fails `west <= east`, then loses both crossing
            # halves to the `x0 < x1` filter and lands on the full-band
            # fallback. Pre-dates the padding; same silent globalisation.
            (float("nan"), 1.0, float("nan"), 4.0),
            (1.0, float("-inf"), 3.0, float("inf")),
        ],
    )
    def test_a_non_finite_bbox_is_refused_not_widened_to_the_globe(self, bbox):
        """fix(#944 codex r1): NaN compares False against everything.

        Every guard in this helper is an ordered comparison, so a NaN slips
        through all of them and comes out the far side as an almost-global
        extent — from a malformed STAC bbox, since ``StacImportItem.bbox`` is
        an unconstrained float list. "An extent must never silently narrow to
        nothing" has a mirror, and this is it.
        """
        with pytest.raises(ValueError, match="finite"):
            bbox_to_extent_wkt(*bbox)


# ---------------------------------------------------------------------------
# chk_records_spatial_extent_type (migration 0030)
# ---------------------------------------------------------------------------


async def _insert_record_with_extent(db, extent_wkt: str | None) -> uuid.UUID:
    record_id = uuid.uuid4()
    extent_sql = "NULL" if extent_wkt is None else "ST_GeomFromText(:wkt, 4326)"
    params: dict[str, object] = {
        "id": record_id,
        "title": f"extent-type-{record_id}",
    }
    if extent_wkt is not None:
        params["wkt"] = extent_wkt
    await db.execute(
        text(
            "INSERT INTO catalog.records "
            "(id, title, visibility, record_status, record_type, spatial_extent) "
            "VALUES (:id, :title, 'private', 'draft', 'vector_dataset', "
            f"{extent_sql})"  # noqa: S608 -- literal NULL or a bound-param call
        ),
        params,
    )
    return record_id


@pytest.mark.anyio
class TestSpatialExtentTypeConstraint:
    async def test_polygon_and_multipolygon_are_accepted(
        self, test_db_session, clean_tables
    ):
        del clean_tables
        for wkt, expected in (
            (ORDINARY_POLYGON, "POLYGON"),
            (SEAM_MULTIPOLYGON, "MULTIPOLYGON"),
            (NON_SEAM_MULTIPOLYGON, "MULTIPOLYGON"),
            (None, None),
        ):
            record_id = await _insert_record_with_extent(test_db_session, wkt)
            stored = (
                await test_db_session.execute(
                    text(
                        "SELECT GeometryType(spatial_extent) AS gtype "
                        "FROM catalog.records WHERE id = :rid"
                    ).bindparams(rid=record_id)
                )
            ).scalar_one()
            assert stored == expected

    @pytest.mark.parametrize(
        "wkt",
        [
            "POINT(1 2)",
            "LINESTRING(0 0,1 1)",
            "GEOMETRYCOLLECTION(POINT(1 2))",
        ],
    )
    async def test_non_areal_extents_are_rejected(
        self, test_db_session, clean_tables, wkt
    ):
        """The old POLYGON typmod caught an extent-write path that tried to store
        a POINT; widening the column must not give that back up."""
        del clean_tables
        with pytest.raises(IntegrityError, match="chk_records_spatial_extent_type"):
            async with test_db_session.begin_nested():
                await _insert_record_with_extent(test_db_session, wkt)

    async def test_column_typmod_is_generic_geometry(
        self, test_db_session, clean_tables
    ):
        del clean_tables
        row = (
            await test_db_session.execute(
                text(
                    "SELECT type, srid FROM geometry_columns "
                    "WHERE f_table_schema = 'catalog' AND f_table_name = 'records' "
                    "AND f_geometry_column = 'spatial_extent'"
                )
            )
        ).one()
        assert row.type == "GEOMETRY"
        assert row.srid == 4326

    async def test_gist_index_survives_the_type_change(
        self, test_db_session, clean_tables
    ):
        """The ALTER COLUMN TYPE rewrite rebuilds indexes; assert the GiST index
        is still there rather than trusting that."""
        del clean_tables
        indexdef = (
            await test_db_session.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = 'catalog' AND tablename = 'records' "
                    "AND indexname = 'idx_records_spatial_extent'"
                )
            )
        ).scalar_one()
        assert "USING gist" in indexdef


# ---------------------------------------------------------------------------
# Stored-extent spatial correctness (the property that actually matters)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_seam_extent_covers_the_data_and_not_the_complementary_340_degrees(
    test_db_session, clean_tables
):
    """fix(#884)/fix(#892): what the old single ring actually did.

    ``POLYGON((170 -20,-170 -20,-170 -15,170 -15,170 -20))`` is a *valid* simple
    rectangle, not a self-intersecting one. Its defect is the area: it spans
    longitude -170..170, so it covered 1700 deg² of the wrong side of the world
    instead of the intended 100 deg², **missed the Fiji data it described**, and
    matched anything in the same -20..-15 latitude band at any other longitude.

    So the discriminating assertions are the Fiji hit (False under the old ring)
    and the same-latitude South Atlantic miss (True under the old ring). A probe
    over central France is *not* discriminating: at latitude 47 it fell outside
    the old ring's latitude band too. It stays here only as a coarse check that
    the extent has not gone global.
    """
    del clean_tables
    record_id = await _insert_record_with_extent(test_db_session, SEAM_MULTIPOLYGON)
    row = (
        await test_db_session.execute(
            text(
                "SELECT GeometryType(spatial_extent) AS gtype,"
                " ST_NumGeometries(spatial_extent) AS parts,"
                " ST_IsValid(spatial_extent) AS valid,"
                " ST_Area(spatial_extent) AS area,"
                " ST_Intersects("
                "   spatial_extent, ST_MakeEnvelope(177, -19, 179, -16, 4326)"
                " ) AS hits_fiji,"
                " ST_Intersects("
                "   spatial_extent, ST_MakeEnvelope(-179, -19, -177, -16, 4326)"
                " ) AS hits_east_of_seam,"
                " ST_Intersects("
                "   spatial_extent, ST_MakeEnvelope(-1, -19, 1, -16, 4326)"
                " ) AS hits_south_atlantic,"
                " ST_Intersects("
                "   spatial_extent, ST_MakeEnvelope(1.5, 46.5, 2.5, 47.5, 4326)"
                " ) AS hits_france"
                " FROM catalog.records WHERE id = :rid"
            ).bindparams(rid=record_id)
        )
    ).one()

    assert row.gtype == "MULTIPOLYGON"
    assert row.parts == 2
    assert row.valid is True
    # 10° west of the seam plus 10° east, over a 5° latitude band.
    assert row.area == pytest.approx(100.0)
    # Both halves of the strip are reachable.
    assert row.hits_fiji is True
    assert row.hits_east_of_seam is True
    # The regression: the old ring matched this and every other longitude in the
    # band, while missing the data itself.
    assert row.hits_south_atlantic is False
    assert row.hits_france is False


@pytest.mark.anyio
async def test_make_bbox_filter_finds_a_seam_extent_from_either_side(
    test_db_session, clean_tables
):
    """The stored two-ring form has to stay reachable through the query path that
    already splits a west > east *query* bbox — that pairing is why the geometry
    column, not a pair of scalar bbox columns, is the right representation."""
    del clean_tables
    from app.core.geo import make_bbox_filter
    from app.modules.catalog.datasets.domain.models import Record
    from sqlalchemy import select

    record_id = await _insert_record_with_extent(test_db_session, SEAM_MULTIPOLYGON)

    async def _matches(bbox: list[float]) -> bool:
        stmt = select(Record.id).where(
            Record.id == record_id,
            make_bbox_filter(Record.spatial_extent, bbox),
        )
        return (await test_db_session.execute(stmt)).scalar_one_or_none() is not None

    # A crossing query bbox, and one bbox wholly inside each hemisphere half.
    assert await _matches([175.0, -19.0, -175.0, -16.0]) is True
    assert await _matches([175.0, -19.0, 179.0, -16.0]) is True
    assert await _matches([-179.0, -19.0, -175.0, -16.0]) is True
    # Central France stays a miss through the query path too.
    assert await _matches([1.5, 46.5, 2.5, 47.5]) is False


# ---------------------------------------------------------------------------
# Which surfaces get which form
# ---------------------------------------------------------------------------


def test_map_layer_response_bbox_uses_the_spec_form():
    """fix(#1112): ``dataset_extent_bbox`` carries the seam to the map builder.

    Held the span form under #892, when all three consumers were seam-blind. The
    two builder fit paths have since grown #903 guards that unwrap a crossing
    pair past 180, and the span form made them unreachable — it flattens a Fiji
    extent to the same ``[-180, s, 180, n]`` a genuinely global dataset
    produces, so auto-fit and Zoom to Layer framed the whole world with nothing
    left to detect. The third consumer still needs the span, because a MapLibre
    source ``bounds`` matches no tile at all when inverted, but it converts at
    that boundary (``normalizeRasterBounds`` in ``layer-adapters/shared.ts``)
    instead of demanding it on the wire. Build the response for real, so this
    holds through any refactor of the helper.
    """
    from app.modules.catalog.maps._router_helpers import _build_layer_response
    from app.modules.catalog.maps.models import MapLayer

    layer = MapLayer(
        id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        display_name="Fiji Seam Crosser",
        sort_order=0,
        visible=True,
        opacity=1.0,
        paint={},
        layout={},
        filter=None,
        label_config=None,
        popup_config=None,
        style_config=None,
        show_in_legend=True,
    )
    resp = _build_layer_response(layer, {"extent": _extent(SEAM_MULTIPOLYGON)})
    assert resp.dataset_extent_bbox == [170.0, -20.0, -170.0, -15.0]
    assert resp.dataset_extent_bbox[0] > resp.dataset_extent_bbox[2]


def test_dataset_response_bbox_uses_the_spec_form():
    """fix(#1004): the mirror of the pin above, on the same database column.

    ``DatasetResponse.extent_bbox`` feeds the dataset detail page, whose three
    camera/extent sites all carry #903 seam guards. The span form flattened a
    crossing extent to ``[-180, s, 180, n]`` — bit-identical to what a genuinely
    global dataset produces — so ``isLargeExtent`` fired first and the guards
    were unreachable. The seam has to survive the wire.

    These two tests sit together deliberately: one column, two response fields
    that reached opposite forms at different times (#1004, then #1112). Both are
    the spec form now, and the span conversion has moved to the one consumer
    that needs it, at that consumer's own boundary.
    """
    from app.modules.catalog.datasets.domain.helpers import dataset_to_response
    from app.modules.catalog.datasets.domain.models import Dataset, Record

    now = datetime(2026, 7, 31, tzinfo=UTC)
    record = Record(
        id=uuid.uuid4(),
        title="Fiji Seam Crosser",
        visibility="public",
        record_status="published",
        record_type="vector_dataset",
        spatial_extent=_extent(SEAM_MULTIPOLYGON),
        created_at=now,
        updated_at=now,
    )
    dataset = Dataset(
        id=uuid.uuid4(),
        record_id=record.id,
        table_name="ds_fiji_seam",
        srid=4326,
        geometry_type="Point",
        feature_count=3,
        current_version=1,
    )
    dataset.record = record

    resp = dataset_to_response(dataset)
    assert resp.extent_bbox == [170.0, -20.0, -170.0, -15.0]
    assert resp.extent_bbox[0] > resp.extent_bbox[2]


def test_standards_record_bbox_keeps_the_spec_form():
    """The mirror of the above, also behavioral: ``extract_bbox`` backs the
    STAC/OGC record ``bbox``, which must NOT be moved to the span or a
    seam-crossing dataset advertises a global footprint again."""
    from types import SimpleNamespace

    from app.modules.catalog.datasets.domain.utils import extract_bbox

    dataset = SimpleNamespace(
        record=SimpleNamespace(spatial_extent=_extent(SEAM_MULTIPOLYGON))
    )
    bbox = extract_bbox(dataset)
    assert bbox == [170.0, -20.0, -170.0, -15.0]
    assert bbox[0] > bbox[2]
