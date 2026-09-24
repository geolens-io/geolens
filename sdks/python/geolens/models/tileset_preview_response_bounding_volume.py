from typing import Literal, cast

TilesetPreviewResponseBoundingVolume = Literal["box", "region", "sphere"]

TILESET_PREVIEW_RESPONSE_BOUNDING_VOLUME_VALUES: set[
    TilesetPreviewResponseBoundingVolume
] = {
    "box",
    "region",
    "sphere",
}


def check_tileset_preview_response_bounding_volume(
    value: str,
) -> TilesetPreviewResponseBoundingVolume:
    if value in TILESET_PREVIEW_RESPONSE_BOUNDING_VOLUME_VALUES:
        return cast(TilesetPreviewResponseBoundingVolume, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {TILESET_PREVIEW_RESPONSE_BOUNDING_VOLUME_VALUES!r}"
    )
