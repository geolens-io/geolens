"""Where a manifest map's layers go in the map's stack on a republish."""

from __future__ import annotations

import itertools
import uuid
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
    *,
    keep_styling: bool = False,
    remove_missing: bool = True,
) -> tuple[list[MapLayerInput], list[str | None], list[MapLayer], int, list[uuid.UUID]]:
    """The layers an apply sends, their keys, the keyed layers it removes,
    how many layers the map then has, and the stored rows it keeps without
    sending, which the save must not delete.

    ``stored`` pairs each of the map's layers with its dataset, None when the
    caller can't read it; ``layers`` and ``keys`` are the manifest's layers
    as stored and their keys. A keyed layer keeps its row, and with
    ``keep_styling`` its stored styling, dataset and slot too. A layer added
    in GeoLens keeps its slot, and so does a layer the caller can't read,
    which the save keeps; the manifest's other layers take the other slots in
    manifest order, the first on top. A readable keyed layer the manifest no longer
    lists is removed with ``remove_missing`` and kept otherwise.
    """
    listed = {layer.key for layer in entry.layers}
    by_key = {
        layer.manifest_key: (layer, dataset)
        for layer, dataset in stored
        if layer.manifest_key
    }

    def stays(layer: MapLayer, dataset: Any) -> bool:
        """Whether the row keeps its own slot rather than a manifest one."""
        if layer.manifest_key is None:
            return True
        if layer.manifest_key in listed:
            return keep_styling
        return dataset is None or not remove_missing

    kept = [(layer, dataset) for layer, dataset in stored if stays(layer, dataset)]
    removed = [
        layer
        for layer, dataset in stored
        if layer.manifest_key is not None
        and layer.manifest_key not in listed
        and dataset is not None
        and remove_missing
    ]
    reserved = {layer.sort_order for layer, _ in kept}
    free = (order for order in itertools.count() if order not in reserved)
    sent: list[MapLayerInput] = []
    sent_keys: list[str | None] = []
    for layer, key in zip(layers, keys, strict=True):
        match = by_key.get(key)
        if match is not None and stays(*match):
            continue
        sent.append(
            layer.model_copy(
                update={
                    "id": match[0].id if match is not None else None,
                    "sort_order": next(free),
                }
            )
        )
        sent_keys.append(key)
    readable_kept = [layer for layer, dataset in kept if dataset is not None]
    sent += [kept_layer(layer) for layer in readable_kept]
    sent_keys += [layer.manifest_key for layer in readable_kept]
    unsent = [layer.id for layer, dataset in kept if dataset is None]
    unlisted = [layer for layer, _ in kept if layer.manifest_key not in listed]
    return sent, sent_keys, removed, len(entry.layers) + len(unlisted), unsent
