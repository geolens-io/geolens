from typing import Literal, cast

StacImportRequestVisibility = Literal["internal", "private", "public", "restricted"]

STAC_IMPORT_REQUEST_VISIBILITY_VALUES: set[StacImportRequestVisibility] = {
    "internal",
    "private",
    "public",
    "restricted",
}


def check_stac_import_request_visibility(value: str) -> StacImportRequestVisibility:
    if value in STAC_IMPORT_REQUEST_VISIBILITY_VALUES:
        return cast(StacImportRequestVisibility, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {STAC_IMPORT_REQUEST_VISIBILITY_VALUES!r}"
    )
