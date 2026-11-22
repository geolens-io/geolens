from typing import Literal, cast

ManifestMapStyling = Literal["keep", "replace", "replace_if_unedited"]

MANIFEST_MAP_STYLING_VALUES: set[ManifestMapStyling] = {
    "keep",
    "replace",
    "replace_if_unedited",
}


def check_manifest_map_styling(value: str) -> ManifestMapStyling:
    if value in MANIFEST_MAP_STYLING_VALUES:
        return cast(ManifestMapStyling, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_MAP_STYLING_VALUES!r}"
    )
