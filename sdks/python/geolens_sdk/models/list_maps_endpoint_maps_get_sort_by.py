from typing import Literal, cast

ListMapsEndpointMapsGetSortBy = Literal["created_at", "name", "updated_at"]

LIST_MAPS_ENDPOINT_MAPS_GET_SORT_BY_VALUES: set[ListMapsEndpointMapsGetSortBy] = {
    "created_at",
    "name",
    "updated_at",
}


def check_list_maps_endpoint_maps_get_sort_by(
    value: str,
) -> ListMapsEndpointMapsGetSortBy:
    if value in LIST_MAPS_ENDPOINT_MAPS_GET_SORT_BY_VALUES:
        return cast(ListMapsEndpointMapsGetSortBy, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {LIST_MAPS_ENDPOINT_MAPS_GET_SORT_BY_VALUES!r}"
    )
