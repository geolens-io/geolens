from typing import Literal, cast

JobStatusBatchEntryCurrentStepType0 = Literal[
    "analyzing",
    "cog_convert",
    "complete",
    "downloading",
    "finalize",
    "ogr2ogr",
    "queued",
    "quicklook",
    "registering",
    "validating",
]

JOB_STATUS_BATCH_ENTRY_CURRENT_STEP_TYPE_0_VALUES: set[
    JobStatusBatchEntryCurrentStepType0
] = {
    "analyzing",
    "cog_convert",
    "complete",
    "downloading",
    "finalize",
    "ogr2ogr",
    "queued",
    "quicklook",
    "registering",
    "validating",
}


def check_job_status_batch_entry_current_step_type_0(
    value: str,
) -> JobStatusBatchEntryCurrentStepType0:
    if value in JOB_STATUS_BATCH_ENTRY_CURRENT_STEP_TYPE_0_VALUES:
        return cast(JobStatusBatchEntryCurrentStepType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {JOB_STATUS_BATCH_ENTRY_CURRENT_STEP_TYPE_0_VALUES!r}"
    )
