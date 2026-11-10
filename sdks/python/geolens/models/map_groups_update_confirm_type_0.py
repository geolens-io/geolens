from typing import Literal, cast

MapGroupsUpdateConfirmType0 = Literal["map_only", "share_datasets"]

MAP_GROUPS_UPDATE_CONFIRM_TYPE_0_VALUES: set[MapGroupsUpdateConfirmType0] = {
    "map_only",
    "share_datasets",
}


def check_map_groups_update_confirm_type_0(value: str) -> MapGroupsUpdateConfirmType0:
    if value in MAP_GROUPS_UPDATE_CONFIRM_TYPE_0_VALUES:
        return cast(MapGroupsUpdateConfirmType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MAP_GROUPS_UPDATE_CONFIRM_TYPE_0_VALUES!r}"
    )
