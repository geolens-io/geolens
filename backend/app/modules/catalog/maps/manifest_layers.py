"""Where a manifest map's layers go in the map's stack on a republish."""

from __future__ import annotations

import itertools
from typing import Any

from app.modules.catalog.maps.models import MapLayer
from app.modules.catalog.maps.schemas import MapLayerInput


def kept_layer(layer: MapLayer) -> MapLayerInput:
    """A layer added in GeoLens, as the builder's full save sends it back."""
    return MapLayerInput.model_validate(
        {
            "id": layer.id,
            "dataset_id": layer.dataset_id,
            "sort_order": layer.sort_order,
            "visible": layer.visible,
            "opacity": layer.opacity,
            "paint": layer.paint,
            "layout": layer.layout,
            "display_name": layer.display_name,
            "filter": layer.filter,
            "label_config": layer.label_config,
            "popup_config": layer.popup_config,
            "style_config": layer.style_config,
            "layer_type": layer.layer_type,
            "show_in_legend": layer.show_in_legend,
        }
    )


def plan_layer_stack(
    entry: Any,
    stored: list[tuple[MapLayer, Any]],
    layers: list[MapLayerInput],
    keys: list[str],
) -> tuple[list[MapLayerInput], list[str | None], list[MapLayer], int]:
    """The layers an apply sends, their keys, the keyed layers it removes,
    and how many layers the map then has.

    ``stored`` pairs each of the map's layers with its dataset, None when the
    caller can't read it; ``layers`` and ``keys`` are the manifest's layers
    as stored and their keys. A keyed layer keeps its row. A layer added in GeoLens keeps its slot, and
    so does a keyed layer the caller can't read, which the save keeps; the
    manifest's layers take the other slots in manifest order, the first on
    top. A readable keyed layer the manifest no longer lists is removed.
    """
    listed = {layer.key for layer in entry.layers}
    by_key = {layer.manifest_key: layer for layer, _ in stored if layer.manifest_key}
    kept = [
        (layer, dataset)
        for layer, dataset in stored
        if layer.manifest_key is None
        or (dataset is None and layer.manifest_key not in listed)
    ]
    removed = [
        layer
        for layer, dataset in stored
        if layer.manifest_key is not None
        and dataset is not None
        and layer.manifest_key not in listed
    ]
    reserved = {layer.sort_order for layer, _ in kept}
    free = (order for order in itertools.count() if order not in reserved)
    sent = [
        layer.model_copy(
            update={
                "id": by_key[key].id if key in by_key else None,
                "sort_order": next(free),
            }
        )
        for layer, key in zip(layers, keys, strict=True)
    ]
    readable_kept = [layer for layer, dataset in kept if dataset is not None]
    sent += [kept_layer(layer) for layer in readable_kept]
    sent_keys: list[str | None] = [*keys, *(None for _ in readable_kept)]
    return sent, sent_keys, removed, len(entry.layers) + len(kept)
