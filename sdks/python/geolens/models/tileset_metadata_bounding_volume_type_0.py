from typing import Literal, cast

TilesetMetadataBoundingVolumeType0 = Literal["box", "region", "sphere"]

TILESET_METADATA_BOUNDING_VOLUME_TYPE_0_VALUES: set[
    TilesetMetadataBoundingVolumeType0
] = {
    "box",
    "region",
    "sphere",
}


def check_tileset_metadata_bounding_volume_type_0(
    value: str,
) -> TilesetMetadataBoundingVolumeType0:
    if value in TILESET_METADATA_BOUNDING_VOLUME_TYPE_0_VALUES:
        return cast(TilesetMetadataBoundingVolumeType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {TILESET_METADATA_BOUNDING_VOLUME_TYPE_0_VALUES!r}"
    )
