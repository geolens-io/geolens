"""Round-trip transforms between GET /api/maps/{id} response and fixture JSON.

Fixtures are hand-authored JSON files stored in scripts/demo/fixtures/maps/.
They must be portable — no UUIDs, no server-generated timestamps. This module
provides the two transforms needed:

  strip_for_fixture  — GET response → fixture JSON. **Author-time tool only**:
                       used manually by a human operator who wants to export
                       a hand-crafted map as a fixture JSON. It is NOT called
                       anywhere in the seeder runtime — the runtime surface is
                       strictly ``resolve_fixture``.
  resolve_fixture    — fixture JSON → PUT body (runtime; called by apply_fixture)

The ``_meta`` block carries human-readable context that is stored in the
fixture but stripped before the PUT. It also carries the ``theme`` field used
by the orchestrator to route each fixture to the correct theme's apply loop.
"""

from __future__ import annotations

from typing import Any, TypedDict, cast

# ---------------------------------------------------------------------------
# Fixture schema (typed) — shared by strip_for_fixture + resolve_fixture
# ---------------------------------------------------------------------------
#
# These TypedDicts document the committed fixture JSON schema. All 8 demo
# fixtures share identical top-level + layer field sets; this just writes
# that invariant down so editors and static analysers can catch drift.
#
# Both are total=False because:
#   - strip_for_fixture builds the dict incrementally key-by-key
#   - resolved PUT bodies replace _stem/_ext with dataset_id, so the "same"
#     layer dict has different keys before vs after resolve_fixture


class FixtureMeta(TypedDict, total=False):
    """Human-readable metadata stored alongside a fixture's portable body."""

    name: str
    description: str
    theme: str
    snapshot_date: str
    exported_at: str


class FixtureLayer(TypedDict, total=False):
    """One entry in ``fixture["layers"]``.

    Two phases:
      - **On disk / pre-resolve** — Requires ``_stem`` and ``_ext`` (for the
        catalog lookup), plus ``sort_order`` and ``layer_type``. All other
        fields are optional style/visibility configuration.
      - **Post-resolve (PUT body)** — ``_stem`` and ``_ext`` are replaced with
        ``dataset_id`` by ``resolve_fixture``. Required fields at that point
        are ``dataset_id``, ``sort_order``, ``layer_type``.

    TypedDict is ``total=False`` because the same class describes both phases.
    """

    _stem: str
    _ext: str
    dataset_id: str
    display_name: str | None
    sort_order: int
    visible: bool
    opacity: float
    paint: dict[str, Any]
    layout: dict[str, Any]
    layer_type: str
    filter: Any | None
    label_config: Any | None
    style_config: dict[str, Any] | None
    show_in_legend: bool


class FixtureDict(TypedDict, total=False):
    """Top-level fixture shape as written to disk by strip_for_fixture."""

    _meta: FixtureMeta
    name: str
    description: str
    center_lng: float
    center_lat: float
    zoom: float
    bearing: float
    pitch: float
    basemap_style: str
    show_basemap_labels: bool
    visibility: str
    widgets: Any | None
    layers: list[FixtureLayer]


# ---------------------------------------------------------------------------
# Fields stripped from the top-level map response
# ---------------------------------------------------------------------------

STRIP_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "id",
        "created_by",
        "created_by_username",
        "created_at",
        "updated_at",
        "thumbnail_url",
        "forked_from_id",
        "forked_from_name",
        "layer_count",
    }
)

# ---------------------------------------------------------------------------
# Fields stripped from each layer in the map response
# ---------------------------------------------------------------------------

STRIP_LAYER: frozenset[str] = frozenset(
    {
        "id",
        "dataset_name",
        "dataset_geometry_type",
        "dataset_table_name",
        "dataset_extent_bbox",
        "dataset_column_info",
        "dataset_feature_count",
        "dataset_sample_values",
        "dataset_record_type",
    }
)


# ---------------------------------------------------------------------------
# strip_for_fixture
# ---------------------------------------------------------------------------


def strip_for_fixture(
    map_response: dict[str, Any],
    stem_lookup: dict[str, tuple[str, str]],
    *,
    theme: str = "",
    snapshot_date: str = "",
) -> FixtureDict:
    """Convert a GET /api/maps/{id} response into a portable fixture dict.

    Args:
        map_response: Raw JSON response from GET /api/maps/{id}.
        stem_lookup: Mapping from ``dataset_id (UUID str) → (stem, ext)``
            where ``ext`` is one of ``.zip``, ``.tif``, ``.geojson``.
            A KeyError for any UUID in a layer is a hard error (planning bug).
        theme: Human-readable theme name stored in ``_meta.theme``.
        snapshot_date: ISO date string (e.g. ``"2025-01-01"``) for ``_meta``.

    Returns:
        Fixture dict suitable for writing as JSON. The ``_meta`` block is
        prepended; top-level server fields and per-layer server fields are
        stripped; each layer's ``dataset_id`` is replaced with ``_stem``
        and ``_ext``.

    Raises:
        KeyError: If a layer's ``dataset_id`` is not found in ``stem_lookup``.
    """
    # Build as a plain dict first (TypedDict forbids dynamic string keys), then
    # view through the FixtureDict type at the return statement.
    fixture: dict[str, Any] = {}

    # Prepend _meta block.
    # Intentionally omitting ``exported_at`` to avoid diff noise on re-exports
    # — prior versions wrote a timestamp that made every re-export look dirty.
    fixture["_meta"] = {
        "name": map_response.get("name", ""),
        "description": map_response.get("description") or "",
        "theme": theme,
        "snapshot_date": snapshot_date,
    }

    # Copy top-level fields, skipping stripped ones
    for k, v in map_response.items():
        if k not in STRIP_TOP_LEVEL and k != "layers":
            fixture[k] = v

    # Transform layers
    fixture["layers"] = []
    for layer in map_response.get("layers", []):
        dataset_id = layer.get("dataset_id")
        if dataset_id is None:
            raise KeyError(f"Layer has no dataset_id: {layer!r}")

        dataset_id_str = str(dataset_id)
        if dataset_id_str not in stem_lookup:
            raise KeyError(
                f"dataset_id {dataset_id_str!r} not found in stem_lookup — "
                "add it before calling strip_for_fixture"
            )

        stem, ext = stem_lookup[dataset_id_str]

        # Build layer as plain dict (see note on fixture above).
        stripped_layer: dict[str, Any] = {}
        for k, v in layer.items():
            if k in STRIP_LAYER:
                continue
            if k == "dataset_id":
                # Replace with stem + ext
                stripped_layer["_stem"] = stem
                stripped_layer["_ext"] = ext
            else:
                stripped_layer[k] = v

        fixture["layers"].append(stripped_layer)

    # cast via dict → FixtureDict (runtime is identical; only annotation changes)
    return cast(FixtureDict, fixture)


# ---------------------------------------------------------------------------
# resolve_fixture
# ---------------------------------------------------------------------------


def resolve_fixture(
    fixture: FixtureDict,
    existing: dict[str, str],
) -> dict[str, Any]:
    """Convert a fixture dict into a PUT /api/maps/{id} body.

    This is the reverse of :func:`strip_for_fixture`. It:
    - Strips the ``_meta`` block.
    - Replaces each layer's ``_stem`` + ``_ext`` with a live ``dataset_id``
      looked up via ``existing[stem + ext]``.

    Args:
        fixture: Fixture dict loaded from disk (as produced by strip_for_fixture).
        existing: Mapping from ``source_filename → dataset_id (UUID str)``
            as returned by ``fetch_existing_datasets``.

    Returns:
        Dict ready for use as the body of PUT /api/maps/{id}.

    Raises:
        KeyError: If a layer's ``_stem + _ext`` is not found in ``existing``.
    """
    resolved: dict[str, Any] = {}

    for k, v in fixture.items():
        if k in ("_meta", "layers"):
            continue
        resolved[k] = v

    resolved["layers"] = []
    for layer in fixture.get("layers", []):
        stem = layer.get("_stem")
        ext = layer.get("_ext")
        if stem is None or ext is None:
            raise KeyError(f"Layer missing _stem or _ext: {layer!r}")

        source_filename = f"{stem}{ext}"
        if source_filename not in existing:
            theme_name = fixture.get("_meta", {}).get("theme", "unknown")
            sample_keys = sorted(existing.keys())[:5]
            raise KeyError(
                f"[Theme: {theme_name}] Dataset {source_filename!r} not in catalog. "
                f"Did the ingest step for this theme fail? "
                f"Sample of {len(existing)} available datasets: {sample_keys}..."
            )

        resolved_layer: dict[str, Any] = {}
        for k, v in layer.items():
            if k in ("_stem", "_ext"):
                continue
            resolved_layer[k] = v
        resolved_layer["dataset_id"] = existing[source_filename]

        resolved["layers"].append(resolved_layer)

    return resolved
