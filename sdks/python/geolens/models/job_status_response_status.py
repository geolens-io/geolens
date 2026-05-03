from typing import Literal, cast

JobStatusResponseStatus = Literal[
    "cancelled", "complete", "failed", "pending", "running"
]

JOB_STATUS_RESPONSE_STATUS_VALUES: set[JobStatusResponseStatus] = {
    "cancelled",
    "complete",
    "failed",
    "pending",
    "running",
}


def check_job_status_response_status(value: str) -> JobStatusResponseStatus:
    if value in JOB_STATUS_RESPONSE_STATUS_VALUES:
        return cast(JobStatusResponseStatus, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {JOB_STATUS_RESPONSE_STATUS_VALUES!r}"
    )
