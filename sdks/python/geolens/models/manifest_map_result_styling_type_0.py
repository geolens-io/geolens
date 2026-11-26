from typing import Literal, cast

ManifestMapResultStylingType0 = Literal["applied", "kept"]

MANIFEST_MAP_RESULT_STYLING_TYPE_0_VALUES: set[ManifestMapResultStylingType0] = {
    "applied",
    "kept",
}


def check_manifest_map_result_styling_type_0(
    value: str,
) -> ManifestMapResultStylingType0:
    if value in MANIFEST_MAP_RESULT_STYLING_TYPE_0_VALUES:
        return cast(ManifestMapResultStylingType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_MAP_RESULT_STYLING_TYPE_0_VALUES!r}"
    )
