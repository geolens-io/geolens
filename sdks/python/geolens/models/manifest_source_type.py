from typing import Literal, cast

ManifestSourceType = Literal["raster_cog", "vector"]

MANIFEST_SOURCE_TYPE_VALUES: set[ManifestSourceType] = {
    "raster_cog",
    "vector",
}


def check_manifest_source_type(value: str) -> ManifestSourceType:
    if value in MANIFEST_SOURCE_TYPE_VALUES:
        return cast(ManifestSourceType, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_SOURCE_TYPE_VALUES!r}"
    )
