from typing import Literal, cast

ManifestGroupsLeftOffDetailReason = Literal["held_back", "left_off", "refused"]

MANIFEST_GROUPS_LEFT_OFF_DETAIL_REASON_VALUES: set[
    ManifestGroupsLeftOffDetailReason
] = {
    "held_back",
    "left_off",
    "refused",
}


def check_manifest_groups_left_off_detail_reason(
    value: str,
) -> ManifestGroupsLeftOffDetailReason:
    if value in MANIFEST_GROUPS_LEFT_OFF_DETAIL_REASON_VALUES:
        return cast(ManifestGroupsLeftOffDetailReason, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MANIFEST_GROUPS_LEFT_OFF_DETAIL_REASON_VALUES!r}"
    )
