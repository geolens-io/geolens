"""The layer-name rule shared by every GDAL argv that carries a caller's layer.

ogrinfo and ogr2ogr take the layer as a positional token, so a name starting
with '-' would be parsed as an option. In ``platform/`` because the catalog's
service preview and the ingest spawners both apply it.
"""

from fastapi import HTTPException, status


def is_option_like_layer_name(layer_name: str) -> bool:
    return layer_name.startswith("-")


def reject_option_like_layer_name(layer_name: str | None) -> None:
    """422 for a layer name GDAL would read as an option."""
    if isinstance(layer_name, str) and is_option_like_layer_name(layer_name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid layer_name: must not start with '-'",
        )
