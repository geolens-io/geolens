"""fix(#888): clip_to_mercator_bounds must not lose data silently.

Two distinct silent-data-loss paths used to run through the same function:

1. A source in the 0..360 Pacific longitude convention (common in ocean and
   climate data) had everything east of lon 180 intersected away. The user saw
   a *successful* ingest with half the features missing and no message.
2. Valid polar geometry was clamped to ±85.06° and, for anything beyond that,
   silently reduced to an empty geometry. The clamp itself is intentional (the
   product serves Web Mercator tiles), but the user was never told, so the
   real failure only showed up three steps later as "Analysis produced no
   features to save".

The 0..360 guard is deliberately four conditions wide. #883 established that a
single-condition guard on this class of problem is a coin flip, so the near
misses are pinned here: a dataset ending exactly at lon 180, a dataset that
spans 0..200, a dataset spanning -10..170, a projected CRS whose X happens to
land between 180 and 360, and a dataset whose X runs past 360.
"""

import pytest
from sqlalchemy import text

from app.processing.ingest.metadata import clip_to_mercator_bounds
from app.processing.ingest.warnings import make_mercator_clip_warning

TABLE = "test_mercator_clip_888"


class _FixtureTable:
    """Mixin: DROP the fixture table before and after each DB-backed test.

    Deliberately a mixin rather than a module-level autouse fixture — the
    pure-Python producer tests at the bottom of this file take no session, and
    an autouse fixture that requires one breaks them.
    """

    @pytest.fixture(autouse=True)
    async def _drop_table(self, test_db_session):
        await test_db_session.execute(
            text(f"DROP TABLE IF EXISTS data.{TABLE} CASCADE")
        )
        await test_db_session.commit()
        yield
        await test_db_session.execute(
            text(f"DROP TABLE IF EXISTS data.{TABLE} CASCADE")
        )
        await test_db_session.commit()


async def _seed_points(session, points: list[tuple[float, float]], srid: int = 4326):
    """Create the fixture table with one typed Point row per (x, y) pair."""
    await session.execute(
        text(
            f"CREATE TABLE data.{TABLE} ("
            "  gid serial PRIMARY KEY,"
            "  label text,"
            f"  geom geometry(Point, {srid})"
            ")"
        )
    )
    for x, y in points:
        await session.execute(
            text(
                f"INSERT INTO data.{TABLE} (label, geom) "
                f"VALUES (:label, ST_SetSRID(ST_MakePoint(:x, :y), {srid}))"
            ).bindparams(label=f"{x},{y}", x=x, y=y)
        )
    await session.commit()


async def _seed_wkt(session, wkts: list[str], geom_type: str, srid: int = 4326):
    """Create the fixture table from WKT literals of a single geometry type."""
    await session.execute(
        text(
            f"CREATE TABLE data.{TABLE} ("
            "  gid serial PRIMARY KEY,"
            f"  geom geometry({geom_type}, {srid})"
            ")"
        )
    )
    for wkt in wkts:
        await session.execute(
            text(
                f"INSERT INTO data.{TABLE} (geom) "
                f"VALUES (ST_GeomFromText(:wkt, {srid}))"
            ).bindparams(wkt=wkt)
        )
    await session.commit()


async def _xs(session) -> list[float]:
    """Return ST_X of every non-empty row, ordered by gid."""
    result = await session.execute(
        text(
            f"SELECT ST_X(geom) FROM data.{TABLE} "
            f"WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom) ORDER BY gid"
        )
    )
    return [float(v) for v in result.scalars().all()]


async def _row_count(session) -> int:
    result = await session.execute(text(f"SELECT count(*) FROM data.{TABLE}"))
    return int(result.scalar_one())


async def _nonempty_count(session) -> int:
    result = await session.execute(
        text(
            f"SELECT count(*) FROM data.{TABLE} "
            f"WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)"
        )
    )
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# 1. A genuine 0..360 source is shifted, not clipped
# ---------------------------------------------------------------------------


class TestZeroTo360Shift(_FixtureTable):
    async def test_every_feature_survives_and_lands_in_minus180_to_180(
        self, test_db_session
    ):
        """A 0..360 source keeps ALL features, shifted into -180..180."""
        await _seed_points(
            test_db_session, [(10.0, 0.0), (100.0, 5.0), (200.0, -5.0), (350.0, 10.0)]
        )

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts == {
            "shifted_longitudes": True,
            "dropped_features": 0,
            "clipped_features": 0,
        }
        # Nothing was destroyed...
        assert await _row_count(test_db_session) == 4
        assert await _nonempty_count(test_db_session) == 4
        # ...and the shift landed inside -180..180.
        xs = await _xs(test_db_session)
        assert xs == pytest.approx([10.0, 100.0, -160.0, -10.0])
        assert all(-180.0 <= x <= 180.0 for x in xs)
        # A no-loss clip must not raise a warning at the user.
        assert make_mercator_clip_warning(counts) is None

    async def test_shift_preserves_polygon_area(self, test_db_session):
        """The translate must move the geometry, not reshape it."""
        await _seed_wkt(
            test_db_session,
            ["POLYGON((200 0, 210 0, 210 10, 200 10, 200 0))"],
            "Polygon",
        )
        area_before = (
            await test_db_session.execute(
                text(f"SELECT ST_Area(geom) FROM data.{TABLE}")
            )
        ).scalar_one()

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts is not None and counts["shifted_longitudes"] is True
        row = (
            await test_db_session.execute(
                text(
                    f"SELECT ST_Area(geom), ST_XMin(geom), ST_XMax(geom) "
                    f"FROM data.{TABLE}"
                )
            )
        ).first()
        assert row is not None
        assert float(row[0]) == pytest.approx(float(area_before))
        assert float(row[1]) == pytest.approx(-160.0)
        assert float(row[2]) == pytest.approx(-150.0)

    async def test_pacific_crossing_source_is_preserved_with_a_naive_extent(
        self, test_db_session
    ):
        """Pinning test: a Pacific-crossing 0..360 source keeps all its data.

        A 150..250 source lands half on each side of the antimeridian, which is
        correct per-feature and is the trade this fix makes deliberately: the
        old behaviour destroyed everything past lon 180 instead.

        The cost is that a bare ``ST_Extent`` over the result reads -170..170,
        a 340 deg bbox for a source spanning 100 deg. That is the
        antimeridian-naive extent fold tracked by #886, whose two call sites
        live in ``metadata.py`` and are untouched here. When #886 folds the
        extent properly this assertion should start failing, which is the
        point: it is where the two fixes meet.
        """
        await _seed_points(
            test_db_session,
            [(150.0, 0.0), (170.0, 0.0), (190.0, 0.0), (250.0, 0.0)],
        )

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts is not None
        assert counts["shifted_longitudes"] is True
        assert counts["dropped_features"] == 0
        assert counts["clipped_features"] == 0
        # Every feature survives, on the correct side of the antimeridian.
        assert await _xs(test_db_session) == pytest.approx(
            [150.0, 170.0, -170.0, -110.0]
        )

        extent = (
            await test_db_session.execute(
                text(
                    f"SELECT ST_XMin(bb), ST_XMax(bb) "
                    f"FROM (SELECT ST_Extent(geom) AS bb FROM data.{TABLE}) q"
                )
            )
        ).first()
        assert extent is not None
        assert (float(extent[0]), float(extent[1])) == pytest.approx((-170.0, 170.0))


# ---------------------------------------------------------------------------
# 2. Near misses: the guard must leave these alone
# ---------------------------------------------------------------------------


class TestZeroTo360GuardNearMisses(_FixtureTable):
    async def test_dataset_ending_exactly_at_180_is_not_shifted(self, test_db_session):
        """Eastern hemisphere up to the antimeridian: max X == 180, so no shift.

        Guard condition 3 (max X > 180). Without it, every Africa/Europe/Asia
        dataset would be flung into -360..-180.
        """
        await _seed_points(test_db_session, [(0.0, 0.0), (90.0, 10.0), (180.0, -10.0)])

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts == {
            "shifted_longitudes": False,
            "dropped_features": 0,
            "clipped_features": 0,
        }
        assert await _xs(test_db_session) == pytest.approx([0.0, 90.0, 180.0])

    async def test_dataset_spanning_0_to_200_shifts_only_out_of_range_rows(
        self, test_db_session
    ):
        """A 0..200 source is recognised, but in-range rows are NOT moved.

        This is the #883 trap in miniature: the dataset as a whole must not be
        bulk-translated, or the prime-meridian half lands in -360..-190. Only
        the rows that are genuinely outside -180..180 move.
        """
        await _seed_points(test_db_session, [(0.0, 0.0), (170.0, 0.0), (200.0, 0.0)])

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts is not None
        assert counts["shifted_longitudes"] is True
        assert counts["dropped_features"] == 0
        assert counts["clipped_features"] == 0
        # lon 0 and lon 170 keep their exact coordinates; only lon 200 moves.
        assert await _xs(test_db_session) == pytest.approx([0.0, 170.0, -160.0])
        assert await _nonempty_count(test_db_session) == 3

    async def test_dataset_spanning_minus10_to_170_is_not_shifted(
        self, test_db_session
    ):
        """Any negative longitude means the source is already -180..180.

        Guard condition 2 (min X >= 0).
        """
        await _seed_points(test_db_session, [(-10.0, 0.0), (0.0, 0.0), (170.0, 0.0)])

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts == {
            "shifted_longitudes": False,
            "dropped_features": 0,
            "clipped_features": 0,
        }
        assert await _xs(test_db_session) == pytest.approx([-10.0, 0.0, 170.0])

    async def test_projected_crs_is_never_shifted(self, test_db_session):
        """Guard condition 1: X in a projected CRS is metres, not longitude.

        SRID 3857 points at X=100/200 m satisfy every *numeric* condition
        (min >= 0, max > 180, max <= 360). Only the CRS check stops them.
        """
        await _seed_points(test_db_session, [(100.0, 0.0), (200.0, 0.0)], srid=3857)

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts == {
            "shifted_longitudes": False,
            "dropped_features": 0,
            "clipped_features": 0,
        }
        assert await _xs(test_db_session) == pytest.approx([100.0, 200.0])

    async def test_grads_based_geographic_crs_is_not_shifted(self, test_db_session):
        """Guard condition 1b: a geographic CRS in grads is not degree-based.

        fix(#899 codex r1): EPSG:4807 (NTF Paris) and 13 more SRIDs in a stock
        ``spatial_ref_sys`` are ``GEOGCS`` with ``UNIT["grad"]``, where a full
        circle is 400. Translating one of those by -360 would move a valid
        feature to a wrong place, so the prefix test alone is not enough.

        This drives ``_shift_zero_to_360_longitudes`` directly rather than the
        public entry point: ``ST_Transform`` collapses the global Mercator
        envelope into a degenerate polygon in 4807, so the clip that follows
        would empty every row and hide what the shift did or did not do. The
        4326 positive control below proves the unit check is what differs.
        """
        from app.processing.ingest.metadata import _shift_zero_to_360_longitudes

        await _seed_points(test_db_session, [(100.0, 10.0), (200.0, 10.0)], srid=4807)

        shifted = await _shift_zero_to_360_longitudes(
            test_db_session, TABLE, "data", 4807
        )

        assert shifted is False
        assert await _xs(test_db_session) == pytest.approx([100.0, 200.0])

    async def test_degree_based_geographic_crs_is_shifted(self, test_db_session):
        """Positive control for the grads case above: same numbers, SRID 4326."""
        from app.processing.ingest.metadata import _shift_zero_to_360_longitudes

        await _seed_points(test_db_session, [(100.0, 10.0), (200.0, 10.0)], srid=4326)

        shifted = await _shift_zero_to_360_longitudes(
            test_db_session, TABLE, "data", 4326
        )

        assert shifted is True
        assert await _xs(test_db_session) == pytest.approx([100.0, -160.0])

    async def test_longitudes_past_360_are_not_shifted(self, test_db_session):
        """Guard condition 4: past 360 is not the 0..360 convention at all."""
        await _seed_points(test_db_session, [(0.0, 0.0), (400.0, 0.0)])

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts is not None
        assert counts["shifted_longitudes"] is False
        # The lon-400 point is real out-of-range data: it is clamped away, and
        # #888's whole point is that the user is told about it.
        assert counts["dropped_features"] == 1
        assert await _xs(test_db_session) == pytest.approx([0.0])

    async def test_3d_column_keeps_z_through_the_shift(self, test_db_session):
        """A shifted 3D column must stay 3D, or the UPDATE fails outright.

        ``geometry(PointZ, 4979)`` is the shape a 4979 source with elevation
        gets. ``ST_Translate(geom, -360, 0)`` has to return PointZ; a 2D result
        would be rejected with "Column has Z dimension but geometry does not".
        """
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{TABLE} ("
                "  gid serial PRIMARY KEY,"
                "  geom geometry(PointZ, 4979)"
                ")"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{TABLE} (geom) "
                f"VALUES (ST_SetSRID(ST_MakePoint(200, 10, 137.5), 4979))"
            )
        )
        await test_db_session.commit()

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts is not None
        assert counts["shifted_longitudes"] is True
        assert counts["dropped_features"] == 0
        row = (
            await test_db_session.execute(
                text(f"SELECT ST_X(geom), ST_Z(geom), ST_NDims(geom) FROM data.{TABLE}")
            )
        ).first()
        assert row is not None
        assert float(row[0]) == pytest.approx(-160.0)
        assert float(row[1]) == pytest.approx(137.5)
        assert int(row[2]) == 3

    async def test_empty_table_is_not_shifted(self, test_db_session):
        """No rows means no extent to read; the probe must not raise."""
        await _seed_points(test_db_session, [])

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts == {
            "shifted_longitudes": False,
            "dropped_features": 0,
            "clipped_features": 0,
        }


# ---------------------------------------------------------------------------
# 3. The clamp still clamps — but now it says so
# ---------------------------------------------------------------------------


class TestClipAccounting(_FixtureTable):
    async def test_polar_point_drop_is_counted(self, test_db_session):
        """A point at lat -89.95 is dropped; the count names it."""
        await _seed_points(
            test_db_session, [(0.0, -89.95), (-73.985, 40.748), (10.0, 89.99)]
        )

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts is not None
        assert counts["dropped_features"] == 2
        assert counts["clipped_features"] == 0
        # The rows survive as attributes; only their geometry is gone.
        assert await _row_count(test_db_session) == 3
        assert await _nonempty_count(test_db_session) == 1

    async def test_polar_drop_produces_a_warning_naming_the_count(
        self, test_db_session
    ):
        """The dropped count reaches the structured ingest-warning channel."""
        await _seed_points(test_db_session, [(0.0, -89.95)])

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)
        warning = make_mercator_clip_warning(counts)

        assert warning == {
            "kind": "mercator_clip",
            "details": {"dropped_features": 1, "clipped_features": 0},
        }

    async def test_partial_clip_is_counted_separately_from_a_drop(
        self, test_db_session
    ):
        """A polygon straddling ±85.06° survives in reduced form."""
        await _seed_wkt(
            test_db_session,
            ["POLYGON((0 80, 10 80, 10 89, 0 89, 0 80))"],
            "Polygon",
        )

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts is not None
        assert counts["dropped_features"] == 0
        assert counts["clipped_features"] == 1
        ymax = (
            await test_db_session.execute(
                text(f"SELECT ST_YMax(geom) FROM data.{TABLE}")
            )
        ).scalar_one()
        assert float(ymax) == pytest.approx(85.06)
        assert make_mercator_clip_warning(counts) == {
            "kind": "mercator_clip",
            "details": {"dropped_features": 0, "clipped_features": 1},
        }

    async def test_in_bounds_dataset_reports_no_loss(self, test_db_session):
        """The overwhelmingly common case stays a silent no-op."""
        await _seed_points(test_db_session, [(-73.985, 40.748), (2.35, 48.85)])

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts == {
            "shifted_longitudes": False,
            "dropped_features": 0,
            "clipped_features": 0,
        }
        assert make_mercator_clip_warning(counts) is None

    async def test_already_empty_rows_do_not_inflate_the_counts(self, test_db_session):
        """A row that arrived empty was not clipped, so it must not be counted."""
        await _seed_points(test_db_session, [(0.0, -89.95)])
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{TABLE} (label, geom) "
                f"VALUES ('empty', ST_SetSRID('POINT EMPTY'::geometry, 4326))"
            )
        )
        await test_db_session.commit()

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts is not None
        assert counts["dropped_features"] == 1
        assert counts["clipped_features"] == 0

    async def test_unregistered_geometry_column_returns_none(self, test_db_session):
        """No geometry_columns row means nothing was inspected."""
        await test_db_session.execute(
            text(f"CREATE TABLE data.{TABLE} (gid serial PRIMARY KEY, label text)")
        )
        await test_db_session.commit()

        assert await clip_to_mercator_bounds(test_db_session, TABLE) is None
        assert make_mercator_clip_warning(None) is None


# ---------------------------------------------------------------------------
# 3b. fix(#906): degenerate-envelope skip for narrow-validity CRSs
# ---------------------------------------------------------------------------


class TestDegenerateEnvelopeSkip(_FixtureTable):
    """fix(#906): ST_Transform of the global safe envelope collapses for
    narrow-validity CRSs (4415 of 8500 stock SRIDs measure zero-area or
    collapsed, 108 more error), and the clip's intersection would then empty
    the whole table with a *successful* ingest. The guard skips the clip and
    records ``clip_skipped`` so the skip is visible, not silent."""

    async def test_narrow_validity_grads_crs_preserves_features(self, test_db_session):
        """EPSG:4807 (NTF Paris): the measured collapse — every envelope X
        becomes 197.396. Pre-guard, this ingest emptied the table."""
        await _seed_points(test_db_session, [(2.0, 54.0), (3.0, 55.0)], srid=4807)

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts == {
            "shifted_longitudes": False,
            "dropped_features": 0,
            "clipped_features": 0,
            "clip_skipped": True,
        }
        assert await _nonempty_count(test_db_session) == 2
        assert await _xs(test_db_session) == pytest.approx([2.0, 3.0])
        warning = make_mercator_clip_warning(counts)
        assert warning is not None
        assert warning["details"]["clip_skipped"] is True

    async def test_utm_source_preserves_features(self, test_db_session):
        """Every UTM zone collapses the global envelope too (measured on
        32633): lon ±180 is far outside the zone's validity."""
        await _seed_points(
            test_db_session, [(500000.0, 5000000.0), (510000.0, 5010000.0)], srid=32633
        )

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts is not None
        assert counts.get("clip_skipped") is True
        assert counts["dropped_features"] == 0
        assert await _nonempty_count(test_db_session) == 2

    async def test_partial_collapse_with_positive_area_is_detected(
        self, test_db_session
    ):
        """EPSG:2263 (NY Long Island, ftUS) leaves a 19-square-foot 'world' —
        positive area, so a bare area check misses it, but clipping real NY
        data against it would still destroy everything. The sliver test
        (area under 1e-6 of the envelope's own bbox area) catches it."""
        await _seed_points(
            test_db_session,
            [(984000.0, 150000.0), (1030000.0, 200000.0)],
            srid=2263,
        )

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts is not None
        assert counts.get("clip_skipped") is True
        assert await _xs(test_db_session) == pytest.approx([984000.0, 1030000.0])

    async def test_ordinary_web_mercator_source_still_clips_normally(
        self, test_db_session
    ):
        """EPSG:3857 transforms the envelope sanely; the guard must not fire
        and the counts shape stays exactly as before (no clip_skipped key)."""
        await _seed_points(test_db_session, [(100.0, 0.0), (200.0, 0.0)], srid=3857)

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts == {
            "shifted_longitudes": False,
            "dropped_features": 0,
            "clipped_features": 0,
        }

    async def test_data_wider_than_the_envelope_is_still_clipped(self, test_db_session):
        """fix(#906 codex r1): a 3857 table with a feature genuinely beyond
        ±20 037 508 m is WIDER than its correctly transformed envelope. The
        degeneracy floor must be absolute (envelope size), never relative to
        the data extent, or exactly the geometry this routine exists to trim
        would skip the clip."""
        await _seed_points(
            test_db_session,
            [(0.0, 0.0), (25_000_000.0, 0.0)],
            srid=3857,
        )

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts is not None
        assert "clip_skipped" not in counts
        assert counts["dropped_features"] == 1
        # The in-bounds feature survives; the out-of-bounds one is emptied.
        assert await _nonempty_count(test_db_session) == 1

    async def test_compound_geographic_crs_polar_clip_is_unchanged(
        self, test_db_session
    ):
        """fix(#906 codex r2): EPSG:5498 (NAD83 + NAVD88 height) is a
        COMPD_CS whose horizontal axes are degrees. The floor's geographic
        test must see through the compound prefix, or its valid
        360x170-degree envelope trips the 1000-unit floor and every ingest in
        that CRS skips the polar clip."""
        await _seed_points(test_db_session, [(10.0, -89.95), (20.0, 45.0)], srid=5498)

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts == {
            "shifted_longitudes": False,
            "dropped_features": 1,
            "clipped_features": 0,
        }

    async def test_geographic_3d_crs_polar_clip_is_unchanged(self, test_db_session):
        """EPSG:4979 stays on the clip path: geographic transforms cannot
        collapse, and genuinely polar geometry must keep being clipped with
        the same counts as before the guard existed."""
        await _seed_points(test_db_session, [(10.0, -89.95), (20.0, 45.0)], srid=4979)

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts == {
            "shifted_longitudes": False,
            "dropped_features": 1,
            "clipped_features": 0,
        }

    async def test_shift_still_runs_before_a_skipped_clip(
        self, test_db_session, monkeypatch
    ):
        """Ordering constraint from the issue: skipping the clip must still
        leave the 0..360 shift applied. No real degree-geographic CRS
        degenerates, so the probe is forced True to pin the ordering."""
        from app.processing.ingest import metadata as metadata_module

        async def _always_degenerate(*_args, **_kwargs):
            return True

        monkeypatch.setattr(
            metadata_module,
            "_mercator_envelope_degenerates",
            _always_degenerate,
        )
        await _seed_points(test_db_session, [(100.0, 10.0), (200.0, 10.0)], srid=4269)

        counts = await clip_to_mercator_bounds(test_db_session, TABLE)

        assert counts == {
            "shifted_longitudes": True,
            "dropped_features": 0,
            "clipped_features": 0,
            "clip_skipped": True,
        }
        assert await _xs(test_db_session) == pytest.approx([100.0, -160.0])


# ---------------------------------------------------------------------------
# 4. Producer contract
# ---------------------------------------------------------------------------


class TestMercatorClipWarningProducer:
    def test_returns_none_for_non_counts_input(self):
        assert make_mercator_clip_warning(None) is None
        assert make_mercator_clip_warning({}) is None  # type: ignore[arg-type]
        assert (
            make_mercator_clip_warning(
                {"dropped_features": "1", "clipped_features": 0}  # type: ignore[typeddict-item]
            )
            is None
        )

    def test_warns_when_either_count_is_positive(self):
        dropped_only = make_mercator_clip_warning(
            {
                "shifted_longitudes": False,
                "dropped_features": 3,
                "clipped_features": 0,
            }
        )
        assert dropped_only is not None
        assert dropped_only["details"]["dropped_features"] == 3

        clipped_only = make_mercator_clip_warning(
            {
                "shifted_longitudes": True,
                "dropped_features": 0,
                "clipped_features": 7,
            }
        )
        assert clipped_only is not None
        assert clipped_only["details"]["clipped_features"] == 7

    def test_warning_validates_against_the_api_contract(self):
        """The producer output must satisfy the router's Pydantic model."""
        from app.platform.jobs.schemas import MercatorClipWarning

        warning = make_mercator_clip_warning(
            {
                "shifted_longitudes": False,
                "dropped_features": 2,
                "clipped_features": 1,
            }
        )
        assert warning is not None
        parsed = MercatorClipWarning.model_validate(warning)
        assert parsed.kind == "mercator_clip"
        assert parsed.details.dropped_features == 2
        assert parsed.details.clipped_features == 1

    def test_warns_when_clip_was_skipped(self):
        """fix(#906): a skipped clip lost nothing but must not be silent."""
        warning = make_mercator_clip_warning(
            {
                "shifted_longitudes": False,
                "dropped_features": 0,
                "clipped_features": 0,
                "clip_skipped": True,
            }
        )
        assert warning is not None
        assert warning["details"]["clip_skipped"] is True
        assert warning["details"]["dropped_features"] == 0

        from app.platform.jobs.schemas import MercatorClipWarning

        parsed = MercatorClipWarning.model_validate(warning)
        assert parsed.details.clip_skipped is True

    def test_pre_906_stored_warning_still_validates(self):
        """Old warnings in user_metadata carry no clip_skipped; the API model
        must default it False rather than reject them."""
        from app.platform.jobs.schemas import MercatorClipWarning

        parsed = MercatorClipWarning.model_validate(
            {
                "kind": "mercator_clip",
                "details": {"dropped_features": 1, "clipped_features": 0},
            }
        )
        assert parsed.details.clip_skipped is False


# ---------------------------------------------------------------------------
# 5. The task-layer emitter
# ---------------------------------------------------------------------------


class TestAppendMercatorClipWarning:
    def _job(self):
        class _Job:
            user_metadata: dict = {}

        return _Job()

    def test_appends_to_the_job_warnings_list(self):
        from app.processing.ingest.tasks_common import _append_mercator_clip_warning

        job = self._job()
        _append_mercator_clip_warning(
            job,
            {
                "shifted_longitudes": False,
                "dropped_features": 4,
                "clipped_features": 0,
            },
        )

        assert job.user_metadata["warnings"] == [
            {
                "kind": "mercator_clip",
                "details": {"dropped_features": 4, "clipped_features": 0},
            }
        ]

    def test_no_op_for_a_clean_clip(self):
        from app.processing.ingest.tasks_common import _append_mercator_clip_warning

        job = self._job()
        _append_mercator_clip_warning(
            job,
            {
                "shifted_longitudes": False,
                "dropped_features": 0,
                "clipped_features": 0,
            },
        )
        _append_mercator_clip_warning(job, None)

        assert job.user_metadata == {}
