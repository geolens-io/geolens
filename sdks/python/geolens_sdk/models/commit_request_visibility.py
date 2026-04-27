from typing import Literal, cast

CommitRequestVisibility = Literal["internal", "private", "public", "restricted"]

COMMIT_REQUEST_VISIBILITY_VALUES: set[CommitRequestVisibility] = {
    "internal",
    "private",
    "public",
    "restricted",
}


def check_commit_request_visibility(value: str) -> CommitRequestVisibility:
    if value in COMMIT_REQUEST_VISIBILITY_VALUES:
        return cast(CommitRequestVisibility, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {COMMIT_REQUEST_VISIBILITY_VALUES!r}"
    )
