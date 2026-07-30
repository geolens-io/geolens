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

import pytest
from geoalchemy2 import WKBElement, WKTElement
from geoalchemy2.shape import from_shape
from shapely import wkt as shapely_wkt
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.geo import bbox_to_extent_wkt, extent_to_bbox, extent_to_span_bbox

# The canonical crossing case: a Fiji-area strip that spans the seam.
FIJI_BBOX = (170.0, -20.0, -170.0, -15.0)

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
        ("bbox", "covered_lons"),
        [
            # west sits on the seam: the west..180 half is padded to a sliver,
            # never dropped — the feature stored at planar +180 must stay
            # covered (fix(#934 codex r2)).
            ((180.0, -20.0, -170.0, -15.0), (180.0, -175.0)),
            # east sits on the seam: same, mirrored.
            ((170.0, -20.0, -180.0, -15.0), (-180.0, 175.0)),
            # Both ends on the seam: two slivers covering both representations
            # of the seam meridian.
            ((180.0, -20.0, -180.0, -15.0), (180.0, -180.0)),
        ],
    )
    def test_degenerate_crossing_halves_never_produce_an_invalid_ring(
        self, bbox, covered_lons
    ):
        """A remote bbox with west == 180 (or east == -180) would otherwise emit
        a zero-width ring — an invalid geometry, the exact defect class this
        helper exists to prevent. fix(#934 codex r2): nor may the degenerate
        half be dropped, which uncovered the feature at planar +180 and made
        the read-back stop reporting a crossing."""
        from shapely.geometry import Point

        shape = shapely_wkt.loads(bbox_to_extent_wkt(*bbox))
        assert shape.is_valid
        assert shape.geom_type == "MultiPolygon"
        for lon in covered_lons:
            assert shape.intersects(Point(lon, -17.5)), lon
        # The read-back still identifies the extent as crossing.
        read = extent_to_bbox(_extent(bbox_to_extent_wkt(*bbox)))
        assert read is not None
        assert read[0] > read[2]


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


def test_map_layer_response_bbox_stays_monotonic():
    """fix(#892 codex P2): ``dataset_extent_bbox`` is documented as
    ``[minx, miny, maxx, maxy]`` and feeds map viewers, not a standards
    serializer.

    A west > east pair there breaks three things at once. MapLibre bounds the
    layer's tile source to no tiles at all (``map-sync.ts``), so a seam-crossing
    layer renders blank; the builder's auto-fit and Zoom to Layer both reject an
    inverted bbox and silently do nothing. Build the response for real, so this
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
    assert resp.dataset_extent_bbox == [-180.0, -20.0, 180.0, -15.0]
    assert resp.dataset_extent_bbox[0] < resp.dataset_extent_bbox[2]


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
