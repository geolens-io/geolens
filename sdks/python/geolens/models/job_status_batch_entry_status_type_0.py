from typing import Literal, cast

JobStatusBatchEntryStatusType0 = Literal[
    "cancelled", "complete", "failed", "fanned_out", "pending", "running"
]

JOB_STATUS_BATCH_ENTRY_STATUS_TYPE_0_VALUES: set[JobStatusBatchEntryStatusType0] = {
    "cancelled",
    "complete",
    "failed",
    "fanned_out",
    "pending",
    "running",
}


def check_job_status_batch_entry_status_type_0(
    value: str,
) -> JobStatusBatchEntryStatusType0:
    if value in JOB_STATUS_BATCH_ENTRY_STATUS_TYPE_0_VALUES:
        return cast(JobStatusBatchEntryStatusType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {JOB_STATUS_BATCH_ENTRY_STATUS_TYPE_0_VALUES!r}"
    )
