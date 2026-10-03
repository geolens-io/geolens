from typing import Literal, cast

StacNextPageMethod = Literal["GET", "POST"]

STAC_NEXT_PAGE_METHOD_VALUES: set[StacNextPageMethod] = {
    "GET",
    "POST",
}


def check_stac_next_page_method(value: str) -> StacNextPageMethod:
    if value in STAC_NEXT_PAGE_METHOD_VALUES:
        return cast(StacNextPageMethod, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {STAC_NEXT_PAGE_METHOD_VALUES!r}"
    )
