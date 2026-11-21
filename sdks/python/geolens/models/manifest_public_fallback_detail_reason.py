from typing import Literal, cast

ManifestPublicFallbackDetailReason = Literal["key", "restriction"]

MANIFEST_PUBLIC_FALLBACK_DETAIL_REASON_VALUES: set[
    ManifestPublicFallbackDetailReason
] = {
    "key",
    "restriction",
}


def check_manifest_public_fallback_detail_reason(
    value: str,
) -> ManifestPublicFallbackDetailReason:
    if value in MANIFEST_PUBLIC_FALLBACK_DETAIL_REASON_VALUES:
        return cast(ManifestPublicFallbackDetailReason, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_PUBLIC_FALLBACK_DETAIL_REASON_VALUES!r}"
    )
