from typing import Literal, cast

ManifestApplyEntryResultAction = Literal["create", "error", "skip", "update"]

MANIFEST_APPLY_ENTRY_RESULT_ACTION_VALUES: set[ManifestApplyEntryResultAction] = {
    "create",
    "error",
    "skip",
    "update",
}


def check_manifest_apply_entry_result_action(
    value: str,
) -> ManifestApplyEntryResultAction:
    if value in MANIFEST_APPLY_ENTRY_RESULT_ACTION_VALUES:
        return cast(ManifestApplyEntryResultAction, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_APPLY_ENTRY_RESULT_ACTION_VALUES!r}"
    )
