"""Tests for the Phase 269 H-23 tile column allowlist.

`_select_tile_columns` resolves the per-zoom default + per-dataset
override rules without touching the database, so these tests stay as
pure-Python unit tests (no DB fixture, no asyncpg pool).
"""

from __future__ import annotations

import pytest

from app.processing.tiles.service import (
    _DEFAULT_NO_ATTR_BELOW_ZOOM,
    _build_attr_columns,
    _build_tile_query,
    _select_tile_columns,
)


_DATASET_COLUMNS = [
    {"name": "gid", "type": "integer"},
    {"name": "name", "type": "text"},
    {"name": "category", "type": "text"},
    {"name": "population", "type": "integer"},
    {"name": "geom", "type": "geometry"},
    {"name": "geom_4326", "type": "geometry"},
]


def test_default_no_attrs_below_zoom_threshold():
    """`tile_columns is None` + z<10 → no attribute columns."""
    for z in range(0, _DEFAULT_NO_ATTR_BELOW_ZOOM):
        result = _select_tile_columns(_DATASET_COLUMNS, z, tile_columns=None)
        assert result == [], f"expected empty selection at z={z}, got {result}"


def test_default_all_attrs_at_or_above_zoom_threshold():
    """`tile_columns is None` + z>=10 → all original columns."""
    for z in range(_DEFAULT_NO_ATTR_BELOW_ZOOM, 23):
        result = _select_tile_columns(_DATASET_COLUMNS, z, tile_columns=None)
        assert result == _DATASET_COLUMNS, (
            f"expected full selection at z={z}, got {result}"
        )


def test_empty_allowlist_returns_no_attrs_at_any_zoom():
    """`tile_columns == []` is the admin opt-in for label-free tiles."""
    for z in (0, 5, 9, 10, 14, 22):
        result = _select_tile_columns(_DATASET_COLUMNS, z, tile_columns=[])
        assert result == [], f"empty allowlist must return [] at z={z}"


def test_non_empty_allowlist_filters_to_matched_columns():
    """`tile_columns=['name','category']` projects only the listed columns."""
    result = _select_tile_columns(
        _DATASET_COLUMNS, 5, tile_columns=["name", "category"]
    )
    names = [c["name"] for c in result]
    assert names == ["name", "category"]


def test_allowlist_preserves_original_column_order():
    """Allowlist resolution preserves the column_info iteration order."""
    # Allowlist deliberately reversed; result should still match dataset order.
    result = _select_tile_columns(
        _DATASET_COLUMNS, 14, tile_columns=["population", "name"]
    )
    names = [c["name"] for c in result]
    assert names == ["name", "population"]


def test_allowlist_drops_unmatched_names():
    """Names in `tile_columns` that don't exist in `columns` are silently dropped."""
    result = _select_tile_columns(
        _DATASET_COLUMNS, 14, tile_columns=["name", "no_such_column"]
    )
    names = [c["name"] for c in result]
    assert names == ["name"]


def test_allowlist_rejects_invalid_column_names():
    """Names that don't match `[A-Za-z_][A-Za-z0-9_]*` are dropped (defense)."""
    result = _select_tile_columns(
        _DATASET_COLUMNS,
        14,
        tile_columns=["name", "drop table users;--", "1invalid", "ok_col"],
    )
    names = [c["name"] for c in result]
    # Only "name" matches both the dataset column_info AND the regex.
    assert names == ["name"]


def test_build_attr_columns_filters_excluded_and_validates_names():
    """Generator-side defensive check: `_build_attr_columns` re-validates names."""
    # Even if a malicious column dict slips through (shouldn't happen, but
    # belt-and-suspenders), the SQL builder never emits invalid names.
    columns = [
        {"name": "name"},
        {"name": "geom"},  # excluded
        {"name": "gid"},  # excluded
        {"name": "geom_4326"},  # excluded
        {"name": "drop table"},  # invalid (space)
    ]
    sql = _build_attr_columns(columns)
    assert sql == ", t.name"


def test_build_tile_query_uses_pruned_columns():
    """`_build_tile_query` projects only the supplied columns into MVT."""
    # Empty columns → no extra projection.
    query = _build_tile_query("perf_test", [])
    assert "t.gid" in query
    # No extra columns past gid.
    assert "t.name" not in query
    assert "t.category" not in query

    # Non-empty columns → projection includes them.
    columns = [{"name": "name"}, {"name": "category"}]
    query = _build_tile_query("perf_test", columns)
    assert "t.name" in query
    assert "t.category" in query
