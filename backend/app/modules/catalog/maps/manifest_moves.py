"""A kept layer the manifest points at another dataset: it moves there, and
keeps its styling only where that styling fits the dataset."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Iterator, Mapping
from typing import Any, NamedTuple

from app.core.csv_safety import NUMERIC_SQL_TYPES
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.record_types import capabilities
from app.modules.catalog.authorization import datasets_beyond_audience
from app.modules.catalog.datasets.domain.service import (
    is_aggregate_number_type,
    is_date_type,
    is_sortable_column,
)
from app.modules.catalog.maps.dashboard import (
    DATE,
    LISTABLE,
    NUMBER,
    SORTABLE,
    can_drop_widgets,
    drop_repointed,
    stored_widgets,
    widget_columns,
)
from app.modules.catalog.maps.dashboard_filters import (
    column_types,
    composed_filter,
    layer_cql2,
)
from app.modules.catalog.maps.manifest_columns import (
    live_styling,
    named_columns,
    number_columns,
)
from app.modules.catalog.maps.manifest_layers import kept_layer
from app.modules.catalog.maps.manifest_messages import (
    MOVED_LAYER_RESTYLED,
    OTHER_REFUSAL,
    listed,
    message,
    short,
)
from app.modules.catalog.maps.models import MapLayer
from app.modules.catalog.maps.schemas import MapLayerInput

# A graduated style, a heatmap weight or an extrusion height reads the column
# as a number in the tiles, which carry no money type as a number.
_STYLE_NUMBER = "style_number"
# Each need a column read can have: whether a column of a type meets it, and
# how a column that doesn't is named, for one column and for several.
_NEEDS: dict[str, tuple[Any, str, str]] = {
    _STYLE_NUMBER: (
        lambda _, kind: kind in NUMERIC_SQL_TYPES,
        "must be a number",
        "must be numbers",
    ),
    NUMBER: (
        lambda _, kind: is_aggregate_number_type(kind),
        "must be a number",
        "must be numbers",
    ),
    DATE: (lambda _, kind: is_date_type(kind), "must be a date", "must be dates"),
    # The aggregate lists any column but geometry and other extension types.
    LISTABLE: (
        lambda _, kind: kind != "user-defined",
        "can't be listed",
        "can't be listed",
    ),
    SORTABLE: (is_sortable_column, "can't be sorted", "can't be sorted"),
}
# The type families a column keeps across a move, by information_schema
# type; any other type is its own family. Within a family a value reads the
# same in a match label, a comparison or an interpolation.
_TEXT_TYPES = frozenset({"text", "character varying", "character"})
_TIME_ONLY_TYPES = frozenset(
    {"time without time zone", "time with time zone", "interval"}
)
# A single-band raster's colormap, which TiTiler can't apply to several bands;
# gray is its default and is never sent.
_DEFAULT_COLORMAPS = ("", "gray")


class Target(NamedTuple):
    """The dataset the manifest names for a layer key, None when it names
    none, and that dataset as the caller reads it, None when they can't or it
    isn't ready; and the layer as the manifest styles it."""

    dataset_id: uuid.UUID | None
    dataset: Any
    layer: MapLayerInput


def _geometry(dataset: Any) -> str:
    if capabilities(dataset.record_type).map_layer_type == "raster_geolens":
        return "raster"
    kind = (dataset.geometry_type or "").upper().removeprefix("MULTI")
    return kind.lower() or "no geometry"


def _raster_misfits(layer: MapLayerInput, was: Any, now: Any) -> list[str]:
    """What a raster layer's styling needs of the raster that ``now`` lacks:
    a DEM's styling a DEM and other styling any other raster, and a colormap
    a single band."""
    misfits = []
    if bool(was.is_dem) != bool(now.is_dem):
        misfits.append(
            "it is a DEM and the layer's earlier raster wasn't"
            if now.is_dem
            else "it isn't a DEM and the layer's earlier raster was"
        )
    style = layer.style_config if isinstance(layer.style_config, dict) else {}
    builder = style.get("builder") if isinstance(style.get("builder"), dict) else {}
    # Stored under the builder; a paint key only as sent before it was moved.
    colormap = builder.get("colormap", (layer.paint or {}).get("_colormap"))
    if isinstance(colormap, str) and colormap not in _DEFAULT_COLORMAPS:
        if now.band_count is None:
            misfits.append("the colormap needs one band, and its bands aren't recorded")
        elif now.band_count != 1:
            misfits.append(f"the colormap needs one band, and it has {now.band_count}")
    return misfits


def _tile_misfits(
    layer: MapLayerInput, types: Mapping[str, str], was: Any, now: Any
) -> list[str]:
    """The columns the layer reads from its tiles, its styling, labels,
    filter and popup, that ``now``'s tile allowlist leaves out while ``was``
    carried them. The viewer builds a popup from the tile's properties."""
    if now.tile_columns is None:
        return []
    drawn = named_columns(layer)
    left_out = sorted(
        name
        for name in drawn | number_columns(layer)
        if name in types
        and name not in now.tile_columns
        and (was.tile_columns is None or name in was.tile_columns)
    )
    return [f"its tiles leave out {listed(left_out)}"] if left_out else []


def _filter_misfits(
    layer: MapLayerInput, widgets: Iterable[Any], was: Any, now: Any, types: Any
) -> list[str]:
    """The layer's filter and its widgets' filters, judged as the viewer
    sends them: one that ran on ``was`` and doesn't on ``now``."""
    misfits = []
    before = layer_cql2(layer.filter, was.columns)
    after = layer_cql2(layer.filter, now.columns)
    if before is not None and after is None:
        misfits.append("the layer's filter can't run on it")
    if any(
        composed_filter(getattr(widget, "filter", None), after, types)[0]
        in ("filter_invalid", "filter_too_large")
        for widget in widgets
    ):
        misfits.append("a dashboard widget's filter can't run on it")
    return misfits


def _family(kind: str) -> str:
    if kind in NUMERIC_SQL_TYPES:
        return "number"
    if kind in _TEXT_TYPES:
        return "text"
    if is_date_type(kind) or kind in _TIME_ONLY_TYPES:
        return "date/time"
    if kind == "boolean":
        return "boolean"
    return kind or "no type"


def _family_misfits(
    reads: Iterable[str], before: Mapping[str, str], after: Mapping[str, str]
) -> list[str]:
    """Each column read whose type family changed, as ``name: number before,
    text now``. A column either side lacks is judged elsewhere."""
    changed = [
        f"{short(name)}: {_family(before[name])} before, {_family(after[name])} now"
        for name in sorted(reads)
        if name in before
        and name in after
        and _family(before[name]) != _family(after[name])
    ]
    return changed[:20]


def _column_reads(layer: MapLayerInput, widgets: Iterable[Any]) -> dict[str, set[str]]:
    """Each column the layer's live styling and its widgets read, with what
    they need of it."""
    reads: dict[str, set[str]] = {name: set() for name in named_columns(layer)}
    for name in number_columns(layer):
        reads.setdefault(name, set()).add(_STYLE_NUMBER)
    for widget in widgets:
        for name, needs in widget_columns(widget):
            reads.setdefault(name, set()).update(needs)
    return reads


def _column_misfits(
    reads: Mapping[str, set[str]], types: Mapping[str, str]
) -> tuple[list[str], set[str]]:
    """The reasons for the columns ``types`` lacks or holds as a type a use
    can't take, and the names those reasons cover."""
    missing = sorted(name for name in reads if name not in types)
    covered = set(missing)
    misfits = []
    if missing:
        columns = "column" if len(missing) == 1 else "columns"
        misfits.append(f"it has no {columns} {listed(missing)}")
    for need in _NEEDS:
        meets, one, several = _NEEDS[need]
        failing = sorted(
            name
            for name, needs in reads.items()
            if need in needs and name in types and not meets(name, types[name])
        )
        if failing:
            typed = [f"{short(name)} ({types[name] or 'no type'})" for name in failing]
            misfits.append(f"{listed(typed)} {one if len(typed) == 1 else several}")
            covered.update(failing)
    return misfits, covered


def styling_misfits(
    layer: MapLayerInput,
    widgets: Iterable[Any],
    was: Any,
    now: Any,
    *,
    widens: bool,
) -> list[str]:
    """Why ``layer``'s styling and the dashboard ``widgets`` on it don't fit
    the dataset ``now`` it moves to from ``was``; empty when they fit.

    They fit when the move doesn't widen who reads the layer (``widens``
    false: every reader of ``now`` reads ``was``), and the geometry types
    match, single and multi part alike; for a raster, when ``now`` is a DEM exactly when ``was`` is, and has one band
    under a colormap. Every column the live styling, labels, popup, filter
    and widgets read must be one of ``now``'s, in the type family it had in
    ``was`` (number, text, date and time, boolean, or the type itself), of a
    type that meets each widget's or style's need, and in ``now``'s tiles
    where ``was``'s tiles carried it for drawing. The layer's and each
    widget's filter must still run on ``now``'s columns as the viewer sends
    them.
    """
    widgets = list(widgets)
    live = live_styling(layer)
    misfits = []
    # Its values, such as category labels, may come from the dataset it
    # left, which the map's new readers can't read.
    if widens:
        misfits.append(
            "some who can read it can't read the dataset the layer left, so "
            "the layer's earlier styling isn't carried over"
        )
    if _geometry(was) != _geometry(now):
        misfits.append(f"its geometry is {_geometry(now)}, not {_geometry(was)}")
    elif _geometry(now) == "raster":
        misfits += _raster_misfits(live, was, now)
    reads = _column_reads(live, widgets)
    if not reads:
        return misfits
    if now.columns is None:
        return [*misfits, "its columns aren't recorded"]
    types = column_types(now.columns)
    by_use, covered = _column_misfits(reads, types)
    misfits += by_use
    misfits += _family_misfits(reads.keys() - covered, column_types(was.columns), types)
    misfits += _tile_misfits(live, types, was, now)
    misfits += _filter_misfits(live, widgets, was, now, types)
    return misfits


class Moves(NamedTuple):
    """What a kept publish does to the keyed layers it moves."""

    layers: dict[uuid.UUID, MapLayerInput]
    """Each moved layer as the save sends it, by layer id."""
    keep_widgets_of: list[uuid.UUID]
    """The moved layers whose dashboard widgets fit their new dataset."""
    warnings: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    """Moves the map can't make, which refuse the whole map."""


def _moving(
    stored: Iterable[tuple[MapLayer, Any]], targets: Mapping[str, Target]
) -> Iterator[tuple[MapLayer, Any, Target]]:
    """Each matched keyed layer whose manifest dataset is another one the
    caller can read, on a stored dataset the caller can read."""
    for layer, was in stored:
        target = targets.get(layer.manifest_key) if layer.manifest_key else None
        if (
            was is not None
            and target is not None
            and target.dataset is not None
            and target.dataset_id != layer.dataset_id
        ):
            yield layer, was, target


async def widening_moves(
    session: AsyncSession,
    stored: Iterable[tuple[MapLayer, Any]],
    targets: Mapping[str, Target],
) -> set[tuple[uuid.UUID, uuid.UUID]]:
    """The ``(from, to)`` dataset pairs of the layers a kept publish may move
    where somebody who reads ``to`` may be unable to read ``from``."""
    pairs = sorted(
        {
            (layer.dataset_id, target.dataset_id)
            for layer, _, target in _moving(stored, targets)
        }
    )
    if not pairs:
        return set()
    beyond = await datasets_beyond_audience(session, [(b, a) for a, b in pairs])
    return {pair for pair, flag in zip(pairs, beyond, strict=True) if flag}


def move_kept_layers(
    stored: Iterable[tuple[MapLayer, Any]],
    targets: Mapping[str, Target],
    dashboard: Any,
    *,
    kept: bool,
    widening: Collection[tuple[uuid.UUID, uuid.UUID]],
) -> Moves:
    """When the publish ``kept`` the map's styling: each matched keyed layer
    whose manifest dataset is another one the caller can read.

    A moved layer keeps its id, key and slot. It keeps its styling and its
    dashboard widgets when they fit the new dataset. Otherwise it takes the
    manifest's styling, loses its widgets as any layer moved to another
    dataset does, and gets a warning naming what didn't fit. A layer on a
    dataset the caller can't read stays as it is, since its styling can't be
    judged without reading that dataset. ``widening`` holds the moves
    ``widening_moves`` found widening who reads the layer; such a move is an
    error when the map's dashboard holds widgets this server can't read,
    since it can't remove them.
    """
    moves = Moves({}, [], [], [])
    if not kept:
        return moves
    widgets = stored_widgets(dashboard)
    for layer, was, target in _moving(stored, targets):
        as_stored = kept_layer(layer)
        on_layer = [w for w in widgets if getattr(w, "layer_id", None) == layer.id]
        widens = (layer.dataset_id, target.dataset_id) in widening
        misfits = styling_misfits(
            as_stored, on_layer, was, target.dataset, widens=widens
        )
        if not misfits:
            moves.layers[layer.id] = as_stored.model_copy(
                update={"dataset_id": target.dataset_id}
            )
            moves.keep_widgets_of.append(layer.id)
            continue
        if widens and not can_drop_widgets(dashboard):
            moves.errors.append(
                message(
                    OTHER_REFUSAL,
                    "error",
                    f"Layer {short(layer.manifest_key)} can't move to the dataset "
                    "the manifest names: some who can read that dataset can't "
                    "read the one it left, and this map's dashboard holds "
                    "widgets this server can't read, saved by a newer GeoLens, "
                    "so it can't remove the ones that may show the old "
                    "dataset's values.",
                    fix="Remove the layer's dashboard widgets in the GeoLens "
                    "that added them, or keep the layer on its dataset.",
                    layer=layer.manifest_key,
                )
            )
            continue
        # Hidden in GeoLens stays hidden; the flag holds no dataset values.
        moves.layers[layer.id] = target.layer.model_copy(
            update={
                "id": layer.id,
                "sort_order": layer.sort_order,
                "visible": layer.visible,
            }
        )
        removed = (
            " Its dashboard widgets are removed."
            if drop_repointed(dashboard, [layer.id]) is not dashboard
            else ""
        )
        moves.warnings.append(
            message(
                MOVED_LAYER_RESTYLED,
                "warning",
                f"Layer {short(layer.manifest_key)} moved to the dataset the "
                "manifest names and took the manifest's styling, because its "
                f"styling doesn't fit that dataset: {'; '.join(misfits)}.{removed}",
                fix="Check the layer's styling in GeoLens.",
                layer=layer.manifest_key,
            )
        )
    return moves
