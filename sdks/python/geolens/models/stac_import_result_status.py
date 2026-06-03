from typing import Literal, cast

StacImportResultStatus = Literal["created", "error", "skipped"]

STAC_IMPORT_RESULT_STATUS_VALUES: set[StacImportResultStatus] = {
    "created",
    "error",
    "skipped",
}


def check_stac_import_result_status(value: str) -> StacImportResultStatus:
    if value in STAC_IMPORT_RESULT_STATUS_VALUES:
        return cast(StacImportResultStatus, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {STAC_IMPORT_RESULT_STATUS_VALUES!r}"
    )
