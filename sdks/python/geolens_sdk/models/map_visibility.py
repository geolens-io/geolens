from typing import Literal, cast

MapVisibility = Literal["internal", "private", "public"]

MAP_VISIBILITY_VALUES: set[MapVisibility] = {
    "internal",
    "private",
    "public",
}


def check_map_visibility(value: str) -> MapVisibility:
    if value in MAP_VISIBILITY_VALUES:
        return cast(MapVisibility, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {MAP_VISIBILITY_VALUES!r}"
    )
