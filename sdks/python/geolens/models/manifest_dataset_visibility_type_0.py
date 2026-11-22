from typing import Literal, cast

ManifestDatasetVisibilityType0 = Literal["internal", "private", "public"]

MANIFEST_DATASET_VISIBILITY_TYPE_0_VALUES: set[ManifestDatasetVisibilityType0] = {
    "internal",
    "private",
    "public",
}


def check_manifest_dataset_visibility_type_0(
    value: str,
) -> ManifestDatasetVisibilityType0:
    if value in MANIFEST_DATASET_VISIBILITY_TYPE_0_VALUES:
        return cast(ManifestDatasetVisibilityType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_DATASET_VISIBILITY_TYPE_0_VALUES!r}"
    )
