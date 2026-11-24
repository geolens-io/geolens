from typing import Literal, cast

ManifestCollectionRefusedDetailReason = Literal["busy", "refused"]

MANIFEST_COLLECTION_REFUSED_DETAIL_REASON_VALUES: set[
    ManifestCollectionRefusedDetailReason
] = {
    "busy",
    "refused",
}


def check_manifest_collection_refused_detail_reason(
    value: str,
) -> ManifestCollectionRefusedDetailReason:
    if value in MANIFEST_COLLECTION_REFUSED_DETAIL_REASON_VALUES:
        return cast(ManifestCollectionRefusedDetailReason, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_COLLECTION_REFUSED_DETAIL_REASON_VALUES!r}"
    )
