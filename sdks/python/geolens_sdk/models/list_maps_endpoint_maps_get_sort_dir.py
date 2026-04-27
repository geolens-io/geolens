from typing import Literal, cast

ListMapsEndpointMapsGetSortDir = Literal["asc", "desc"]

LIST_MAPS_ENDPOINT_MAPS_GET_SORT_DIR_VALUES: set[ListMapsEndpointMapsGetSortDir] = {
    "asc",
    "desc",
}


def check_list_maps_endpoint_maps_get_sort_dir(
    value: str,
) -> ListMapsEndpointMapsGetSortDir:
    if value in LIST_MAPS_ENDPOINT_MAPS_GET_SORT_DIR_VALUES:
        return cast(ListMapsEndpointMapsGetSortDir, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {LIST_MAPS_ENDPOINT_MAPS_GET_SORT_DIR_VALUES!r}"
    )
