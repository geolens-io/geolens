"""ArcGIS sub-layer kinds the wizard can import.

A service root lists composite layers (group, topology, utility network)
whose rows live in their sublayers, plus raster and annotation layers that are
not feature data for the catalog. The probe flags them and the preview refuses
them rather than creating an empty dataset. A layer is composite when it names
sublayers, whatever its type string, so composite types a server adds later are
caught too. A server that omits the type stays importable.
"""

from collections.abc import Callable

from fastapi import HTTPException, status

UNSUPPORTED_ARCGIS_LAYER_TYPES = frozenset(
    {
        "Group Layer",
        "Raster Layer",
        "Annotation Layer",
        "Topology Layer",
        "Utility Network Layer",
    }
)


def is_importable_arcgis_layer(layer: dict) -> bool:
    """True unless the layer JSON (root entry or own metadata) holds no rows.

    Root entries name children in ``subLayerIds``; a layer's own metadata uses
    ``subLayers``.
    """
    layer_type = layer.get("type")
    if isinstance(layer_type, str) and layer_type in UNSUPPORTED_ARCGIS_LAYER_TYPES:
        return False
    return not (layer.get("subLayerIds") or layer.get("subLayers"))


def reject_unsupported_arcgis_type(meta: dict) -> None:
    """Raise a coded 422 when the layer JSON describes a layer without rows."""
    if is_importable_arcgis_layer(meta):
        return
    layer_type = meta.get("type")
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": "unsupported_layer_type",
            "message": (
                f"{layer_type or 'This layer'} cannot be imported because it holds no features. "
                "Import one of its feature layers or tables instead."
            ),
            "layer_type": layer_type,
        },
    )


def arcgis_probe_layers(
    data: dict,
    service_oid: str | None,
    normalize_geometry: Callable[[str | None], str | None],
) -> list[dict]:
    """Layer and table entries of a service root, with ArcGIS type and parent.

    Root layer lists usually omit objectIdField, and a guessed name makes the
    server reject the query; the worker reads the layer's own JSON.
    """
    layers = []
    for layer in data.get("layers", []):
        parent = layer.get("parentLayerId")
        arcgis_type = layer.get("type")
        layers.append(
            {
                "id": layer["id"],
                "name": layer["name"],
                "title": layer.get("title"),
                "geometry_type": normalize_geometry(layer.get("geometryType")),
                "type": "layer",
                "arcgis_type": arcgis_type if isinstance(arcgis_type, str) else None,
                "importable": is_importable_arcgis_layer(layer),
                "parent_layer_id": parent
                if isinstance(parent, int) and parent >= 0
                else None,
                "object_id_field": layer.get("objectIdField") or service_oid,
            }
        )
    for table in data.get("tables", []):
        layers.append(
            {
                "id": table["id"],
                "name": table["name"],
                "title": table.get("title"),
                "geometry_type": None,
                "type": "table",
                "arcgis_type": "Table",
                "importable": True,
                "parent_layer_id": None,
            }
        )
    return layers
