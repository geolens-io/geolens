from typing import Literal, cast

TilesetPreviewResponseVersion = Literal["1.0", "1.1"]

TILESET_PREVIEW_RESPONSE_VERSION_VALUES: set[TilesetPreviewResponseVersion] = {
    "1.0",
    "1.1",
}


def check_tileset_preview_response_version(value: str) -> TilesetPreviewResponseVersion:
    if value in TILESET_PREVIEW_RESPONSE_VERSION_VALUES:
        return cast(TilesetPreviewResponseVersion, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {TILESET_PREVIEW_RESPONSE_VERSION_VALUES!r}"
    )
