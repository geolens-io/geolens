"""Unit tests for seed_tiles tile math functions."""

import math

import pytest

from scripts.seed_tiles import bbox_to_tiles, lat_to_tile_y, lng_to_tile_x


class TestLngToTileX:
    def test_zero_lng_z0(self):
        # At z=0 there is only one tile (x=0); longitude 0 maps to x=0
        assert lng_to_tile_x(0.0, 0) == 0

    def test_negative_180_z1(self):
        # Westmost edge maps to tile x=0
        assert lng_to_tile_x(-180.0, 1) == 0

    def test_positive_180_z1(self):
        # 180° wraps back to tile x=2 at z=1 (tiles are 0 and 1 for 0..1)
        # Standard formula: int((180+180)/360 * 2) = int(2.0) = 2; clamp to n-1=1 done in bbox_to_tiles
        assert lng_to_tile_x(180.0, 1) == 2

    def test_zero_lng_z1(self):
        # 0° at z=1: int((0+180)/360 * 2) = int(1.0) = 1
        assert lng_to_tile_x(0.0, 1) == 1

    def test_known_value_z10(self):
        # New York City approx lng=-74, z=10
        # int((-74+180)/360 * 1024) = int(106/360 * 1024) = int(301.51) = 301
        assert lng_to_tile_x(-74.0, 10) == 301


class TestLatToTileY:
    def test_equator_z0(self):
        # At z=0 there is only tile y=0; equator maps to 0
        assert lat_to_tile_y(0.0, 0) == 0

    def test_north_pole_z1(self):
        # Near north pole at z=1 → tile y=0
        assert lat_to_tile_y(85.0, 1) == 0

    def test_south_pole_z1(self):
        # Near south pole at z=1 → tile y=1 (clamped to 85.0511 before calling)
        assert lat_to_tile_y(-85.0, 1) == 1

    def test_equator_z1(self):
        # 0° lat at z=1 → tile y=1 (middle of 2 tiles)
        assert lat_to_tile_y(0.0, 1) == 1

    def test_known_value_z10(self):
        # New York City approx lat=40.7, z=10
        lat_rad = math.radians(40.7)
        n = 1 << 10
        expected = int(
            (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
            / 2.0
            * n
        )
        assert lat_to_tile_y(40.7, 10) == expected


class TestBboxToTiles:
    def test_global_z0_yields_single_tile(self):
        tiles = list(bbox_to_tiles(-180, -85.0511, 180, 85.0511, z=0))
        assert tiles == [(0, 0, 0)]

    def test_global_z1_yields_four_tiles(self):
        tiles = list(bbox_to_tiles(-180, -85.0511, 180, 85.0511, z=1))
        assert len(tiles) == 4
        # All tiles should be at zoom level 1
        assert all(t[0] == 1 for t in tiles)

    def test_small_bbox_z0_yields_single_tile(self):
        # Any bbox at z=0 should return exactly one tile
        tiles = list(bbox_to_tiles(0, 0, 10, 10, z=0))
        assert tiles == [(0, 0, 0)]

    def test_small_city_bbox_z10_reasonable_count(self):
        # A small city-sized bbox (~0.2 degrees) at z=10 should yield ~tens of tiles
        tiles = list(bbox_to_tiles(-74.1, 40.65, -73.9, 40.85, z=10))
        count = len(tiles)
        assert 5 <= count <= 500, f"Expected ~tens of tiles, got {count}"
        # All should be at zoom 10
        assert all(t[0] == 10 for t in tiles)

    def test_latitude_clamped_above_85(self):
        # bbox_to_tiles clamps north to 85.0511 — should not raise
        tiles = list(bbox_to_tiles(-180, -90, 180, 90, z=0))
        assert tiles == [(0, 0, 0)]

    def test_latitude_clamped_below_neg_85(self):
        # Should not raise even with extreme south
        tiles = list(bbox_to_tiles(-10, -90, 10, 10, z=1))
        assert len(tiles) >= 1

    def test_tile_format_is_z_x_y(self):
        tiles = list(bbox_to_tiles(-180, -85.0511, 180, 85.0511, z=1))
        for tile in tiles:
            assert len(tile) == 3
            z, x, y = tile
            assert z == 1

    def test_antimeridian_bbox_z1(self):
        # A bbox that straddles the antimeridian via negative west
        # west > east edge case: treat as normal (no special wrapping required)
        tiles = list(bbox_to_tiles(170, -10, 180, 10, z=1))
        assert len(tiles) >= 1

    def test_northern_polar_bbox(self):
        # High-latitude bbox (near pole)
        tiles = list(bbox_to_tiles(-20, 80, 20, 85, z=1))
        assert len(tiles) >= 1

    def test_no_tiles_for_inverted_bbox(self):
        # east < west (degenerate bbox) should return empty or minimal tiles
        # Our implementation: x_min > x_max → empty range
        tiles = list(bbox_to_tiles(10, 40, 5, 50, z=10))
        assert len(tiles) == 0
