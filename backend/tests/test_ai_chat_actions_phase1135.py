"""_validate_chat_layers and _schema_cache_key regression pins.

These tests pin two design decisions:

1. `_validate_chat_layers` does NOT filter by layer.visible — its docstring
   must document that analysis sees every layer regardless of visibility
   state, and name the `include_hidden` escape hatch for a future
   visible-only scope.
2. `_schema_cache_key` is partitioned by (map_id, content_hash). Two maps
   with identical layer signatures MUST receive distinct cache keys; the
   same map with the same layers MUST receive equal cache keys.

These tests intentionally make zero DB calls — they validate docstrings and
a pure function. They serve as a low-cost regression net against future
refactors that strip the rationale or shortcut the cache key.
"""

import inspect

from app.processing.ai.router import _validate_chat_layers
from app.processing.ai.schemas import ChatMapLayer
from app.processing.ai.sql_generator import _schema_cache_key


def test_validate_chat_layers_docstring_pins_visibility_decision() -> None:
    """docstring must document the visibility-filter decision explicitly."""
    docstring = inspect.getdoc(_validate_chat_layers) or ""
    # Rationale words: a future refactor that strips the rationale will
    # remove one of these terms; the assertion catches the regression.
    assert "regardless" in docstring.lower(), (
        "_validate_chat_layers docstring must mention 'regardless' "
        "to assert analysis sees all layers regardless of visibility state"
    )
    assert "visibility" in docstring.lower(), (
        "_validate_chat_layers docstring must mention 'visibility' "
        "to explain that visibility is NOT a filter criterion for analysis"
    )
    assert "include_hidden" in docstring, (
        "_validate_chat_layers docstring must name the include_hidden "
        "escape hatch for a future visible-only scope"
    )


def _make_layer(table: str = "data.test_table", geom: str = "Polygon") -> ChatMapLayer:
    """Build a minimal ChatMapLayer fixture for cache-key tests.

    Uses only required + commonly-set fields. If ChatMapLayer adds new
    required fields in a future refactor, extend this fixture inline rather
    than copying it across test files.
    """
    return ChatMapLayer(
        id="layer-1",
        name="Test Layer",
        dataset_id="ds-1",
        dataset_table_name=table,
        geometry_type=geom,
        column_info=[{"name": "col_a", "type": "text"}],
        feature_count=10,
    )


def test_schema_cache_key_isolates_by_map_id() -> None:
    """PERF-04: same layers under different map_id produce distinct cache
    keys (cross-map isolation)."""
    layer = _make_layer()
    key_a = _schema_cache_key([layer], map_id="map-A")
    key_b = _schema_cache_key([layer], map_id="map-B")
    assert key_a != key_b, (
        "Two different map_ids must produce DISTINCT schema cache keys "
        "(PERF-04 cross-map isolation contract)"
    )
    # Verify the tuple shape is exactly (map_key, content_hash)
    assert isinstance(key_a, tuple) and len(key_a) == 2
    assert key_a[0] == "map-A" and key_b[0] == "map-B"
    assert key_a[1] == key_b[1], (
        "Identical layers should produce IDENTICAL content_hash "
        "(the second tuple element); only the map_key (first element) differs"
    )


def test_schema_cache_key_stable_for_same_map_id() -> None:
    """Cache-hit baseline: same layers, same map_id, identical cache key."""
    layer = _make_layer()
    key1 = _schema_cache_key([layer], map_id="map-A")
    key2 = _schema_cache_key([layer], map_id="map-A")
    assert key1 == key2, (
        "Same layers under same map_id must produce IDENTICAL cache keys "
        "(cache-hit baseline)"
    )


def test_schema_cache_key_isolates_by_content_hash_same_map_id() -> None:
    """Within a single map, layers with different table_name produce
    distinct content_hash keys."""
    layer_a = _make_layer(table="data.alpha")
    layer_b = _make_layer(table="data.beta")
    key_a = _schema_cache_key([layer_a], map_id="map-X")
    key_b = _schema_cache_key([layer_b], map_id="map-X")
    assert key_a != key_b, (
        "Different layer signatures under the same map_id must produce "
        "DISTINCT cache keys (content_hash partition)"
    )
    # Verify the map_key (first element) is identical and only the hash differs
    assert key_a[0] == "map-X" and key_b[0] == "map-X"
    assert key_a[1] != key_b[1]
