from typing import Literal, cast

DatabaseImportRequestVisibility = Literal["internal", "private", "public", "restricted"]

DATABASE_IMPORT_REQUEST_VISIBILITY_VALUES: set[DatabaseImportRequestVisibility] = {
    "internal",
    "private",
    "public",
    "restricted",
}


def check_database_import_request_visibility(
    value: str,
) -> DatabaseImportRequestVisibility:
    if value in DATABASE_IMPORT_REQUEST_VISIBILITY_VALUES:
        return cast(DatabaseImportRequestVisibility, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {DATABASE_IMPORT_REQUEST_VISIBILITY_VALUES!r}"
    )
