from typing import Literal, cast

ManifestSourceType = Literal["raster_cog", "vector", "vrt"]

MANIFEST_SOURCE_TYPE_VALUES: set[ManifestSourceType] = {
    "raster_cog",
    "vector",
    "vrt",
}


def check_manifest_source_type(value: str) -> ManifestSourceType:
    if value in MANIFEST_SOURCE_TYPE_VALUES:
        return cast(ManifestSourceType, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_SOURCE_TYPE_VALUES!r}"
    )
