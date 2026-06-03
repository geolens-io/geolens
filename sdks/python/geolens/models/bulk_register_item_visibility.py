from typing import Literal, cast

BulkRegisterItemVisibility = Literal["internal", "private", "public", "restricted"]

BULK_REGISTER_ITEM_VISIBILITY_VALUES: set[BulkRegisterItemVisibility] = {
    "internal",
    "private",
    "public",
    "restricted",
}


def check_bulk_register_item_visibility(value: str) -> BulkRegisterItemVisibility:
    if value in BULK_REGISTER_ITEM_VISIBILITY_VALUES:
        return cast(BulkRegisterItemVisibility, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BULK_REGISTER_ITEM_VISIBILITY_VALUES!r}"
    )
