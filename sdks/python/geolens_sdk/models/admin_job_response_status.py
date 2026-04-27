from typing import Literal, cast

AdminJobResponseStatus = Literal[
    "cancelled", "complete", "failed", "pending", "running"
]

ADMIN_JOB_RESPONSE_STATUS_VALUES: set[AdminJobResponseStatus] = {
    "cancelled",
    "complete",
    "failed",
    "pending",
    "running",
}


def check_admin_job_response_status(value: str) -> AdminJobResponseStatus:
    if value in ADMIN_JOB_RESPONSE_STATUS_VALUES:
        return cast(AdminJobResponseStatus, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {ADMIN_JOB_RESPONSE_STATUS_VALUES!r}"
    )
