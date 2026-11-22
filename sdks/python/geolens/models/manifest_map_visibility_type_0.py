from typing import Literal, cast

ManifestMapVisibilityType0 = Literal["internal", "private", "public"]

MANIFEST_MAP_VISIBILITY_TYPE_0_VALUES: set[ManifestMapVisibilityType0] = {
    "internal",
    "private",
    "public",
}


def check_manifest_map_visibility_type_0(value: str) -> ManifestMapVisibilityType0:
    if value in MANIFEST_MAP_VISIBILITY_TYPE_0_VALUES:
        return cast(ManifestMapVisibilityType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_MAP_VISIBILITY_TYPE_0_VALUES!r}"
    )
