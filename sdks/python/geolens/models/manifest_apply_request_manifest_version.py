from typing import Literal, cast

ManifestApplyRequestManifestVersion = Literal["1", "2"]

MANIFEST_APPLY_REQUEST_MANIFEST_VERSION_VALUES: set[
    ManifestApplyRequestManifestVersion
] = {
    "1",
    "2",
}


def check_manifest_apply_request_manifest_version(
    value: str,
) -> ManifestApplyRequestManifestVersion:
    if value in MANIFEST_APPLY_REQUEST_MANIFEST_VERSION_VALUES:
        return cast(ManifestApplyRequestManifestVersion, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_APPLY_REQUEST_MANIFEST_VERSION_VALUES!r}"
    )
