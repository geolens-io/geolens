"""Save-time checks of dashboard widget filters against the aggregate endpoint.

A widget's request carries its layer's filter ANDed with its own, as the
viewer composes them. A save refuses a widget whose filter names a column its
layer lacks, whose composed filter passes the aggregate's value, depth or
length limit, or that the aggregate's own compiler refuses with the dataset's
live columns. The filter is compiled only, never run. A save that changes a
layer's filter is refused when it puts a widget on that layer past the limits.
"""

import json
import uuid
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.service import compile_layer_filter
from app.modules.catalog.maps.dashboard import (
    DashboardConfigInput,
    refuse_widgets,
    stored_widgets,
)
from app.modules.catalog.maps.filter_grammar import FilterValidationError
from app.modules.catalog.maps.models import MapLayer
from app.modules.catalog.widgets.filter_shapes import (
    MAX_CQL2_DEPTH,
    measure_cql2,
    widget_filter_cql2,
)

_BIND_PREFIX = "widget_filter"


def column_types(column_info: Any) -> dict[str, str]:
    """A dataset's ``column_info`` as column name to lower-case type."""
    return {
        col["name"]: str(col.get("type") or "").lower()
        for col in column_info or []
        if isinstance(col, dict) and isinstance(col.get("name"), str)
    }


def _layer_cql2(layer_filter: Any, types: Mapping[str, str]) -> dict | None:
    """The layer's filter as the viewer sends it, or None when it sends none.

    With column types known, the viewer drops a filter on a column outside them.
    """
    try:
        layer = widget_filter_cql2(layer_filter, types)
    except FilterValidationError:
        return None
    return None if types and not layer.columns <= types.keys() else layer.cql2


def composed_filter(
    widget_filter: Any, layer_filter: Any, types: Mapping[str, str]
) -> tuple[str | None, dict | None]:
    """A refusal reason, or None and the CQL2 a widget's request carries.

    ``filter_column`` names a column outside ``types``; ``filter_invalid`` has a
    literal or operator the viewer won't send for its column's type;
    ``filter_too_large`` passes the aggregate's value, depth or length limit.
    The viewer drops a layer filter it can't convert, and so does this.
    """
    from app.standards.ogc.filtering import (
        MAX_FEATURE_FILTER_BINDS,
        MAX_FEATURE_FILTER_LENGTH,
    )

    try:
        own = widget_filter_cql2(widget_filter)
        if not own.columns <= types.keys():
            return "filter_column", None
        # With the column types: a literal the viewer won't send for its column.
        own = widget_filter_cql2(widget_filter, types)
    except FilterValidationError:
        return "filter_invalid", None
    layer = _layer_cql2(layer_filter, types)
    parts = [part for part in (layer, own.cql2) if part is not None]
    if not parts:
        return None, None
    cql2 = parts[0] if len(parts) == 1 else {"op": "and", "args": parts}
    values, depth = measure_cql2(cql2)
    text = json.dumps(cql2, ensure_ascii=False, separators=(",", ":"))
    too_large = (
        values > MAX_FEATURE_FILTER_BINDS
        or depth > MAX_CQL2_DEPTH
        or len(text) > MAX_FEATURE_FILTER_LENGTH
    )
    return ("filter_too_large", None) if too_large else (None, cql2)


async def _compiles(session: AsyncSession, dataset: Dataset, cql2: dict) -> bool:
    try:
        await compile_layer_filter(session, dataset, cql2, bind_prefix=_BIND_PREFIX)
    except ValueError:
        return False
    return True


async def widget_filter_refusals(
    session: AsyncSession,
    sent: DashboardConfigInput | None,
    layers: Sequence[MapLayer],
    hidden_layer_ids: Collection[uuid.UUID],
) -> dict[str, str]:
    """Why each sent widget's filter can't be saved, by widget id.

    Widgets on hidden layers are left to ``merge_dashboard``'s layer check.
    ``filter_invalid`` is the aggregate compiler's refusal: a literal its
    column's type can't hold, an invalid date, a column CQL2 can't filter, or
    an operator the type doesn't take.
    """
    by_id = {layer.id: layer for layer in layers}
    widgets = [
        (widget, by_id[widget.layer_id])
        for widget in (sent.widgets if sent is not None else [])
        if getattr(widget, "filter", None) is not None
        and widget.layer_id in by_id
        and widget.layer_id not in hidden_layer_ids
    ]
    if not widgets:
        return {}
    dataset_ids = {layer.dataset_id for _, layer in widgets}
    datasets = {
        dataset.id: dataset
        for dataset in await session.scalars(
            select(Dataset).where(Dataset.id.in_(dataset_ids))
        )
    }
    refusals: dict[str, str] = {}
    for widget, layer in widgets:
        dataset = datasets.get(layer.dataset_id)
        types = column_types(dataset.column_info if dataset is not None else None)
        layer_filter = layer.filter
        if dataset is not None and layer_filter is not None:
            layer_cql2 = _layer_cql2(layer_filter, types)
            if layer_cql2 is None or not await _compiles(session, dataset, layer_cql2):
                layer_filter = None
        reason, cql2 = composed_filter(widget.filter, layer_filter, types)
        if reason is None and cql2 is not None:
            if dataset is None or not await _compiles(session, dataset, cql2):
                reason = "filter_invalid"
        if reason is not None:
            refusals[str(widget.id)] = reason
    return refusals


async def refuse_layer_filter_past_limits(
    session: AsyncSession,
    dashboard: Any,
    layers: Sequence[MapLayer],
    filters_before: Mapping[uuid.UUID, Any],
) -> None:
    """Refuse (422) a save whose layer filter puts a widget past the aggregate's limits.

    Checks every stored widget this server parses, shown or kept, on a layer
    that is new or whose ``filter`` differs from ``filters_before``: the layer's
    filter alone, or ANDed with the widget's own. Other layers are left as stored.
    """
    changed = {
        layer.id: layer
        for layer in layers
        if layer.id not in filters_before or filters_before[layer.id] != layer.filter
    }
    widgets = [
        widget
        for widget in (stored_widgets(dashboard) if changed else [])
        if getattr(widget, "layer_id", None) in changed
    ]
    if not widgets:
        return
    dataset_ids = {changed[widget.layer_id].dataset_id for widget in widgets}
    rows = await session.execute(
        select(Dataset.id, Dataset.column_info).where(Dataset.id.in_(dataset_ids))
    )
    columns = {dataset_id: info for dataset_id, info in rows.all()}
    refused: list[dict[str, str | None]] = []
    for widget in widgets:
        layer = changed[widget.layer_id]
        types = column_types(columns.get(layer.dataset_id))
        reason, _ = composed_filter(
            getattr(widget, "filter", None), layer.filter, types
        )
        if reason == "filter_too_large":
            refused.append(
                {"id": str(widget.id), "layer_id": str(layer.id), "reason": reason}
            )
    refuse_widgets(refused)
