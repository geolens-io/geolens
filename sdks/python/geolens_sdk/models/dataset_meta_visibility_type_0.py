from typing import Literal, cast

DatasetMetaVisibilityType0 = Literal["internal", "private", "public", "restricted"]

DATASET_META_VISIBILITY_TYPE_0_VALUES: set[DatasetMetaVisibilityType0] = {
    "internal",
    "private",
    "public",
    "restricted",
}


def check_dataset_meta_visibility_type_0(value: str) -> DatasetMetaVisibilityType0:
    if value in DATASET_META_VISIBILITY_TYPE_0_VALUES:
        return cast(DatasetMetaVisibilityType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {DATASET_META_VISIBILITY_TYPE_0_VALUES!r}"
    )
