from typing import Literal, cast

ManifestMapResultAction = Literal["create", "error", "skip", "update"]

MANIFEST_MAP_RESULT_ACTION_VALUES: set[ManifestMapResultAction] = {
    "create",
    "error",
    "skip",
    "update",
}


def check_manifest_map_result_action(value: str) -> ManifestMapResultAction:
    if value in MANIFEST_MAP_RESULT_ACTION_VALUES:
        return cast(ManifestMapResultAction, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_MAP_RESULT_ACTION_VALUES!r}"
    )
