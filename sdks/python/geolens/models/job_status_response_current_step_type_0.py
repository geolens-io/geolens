from typing import Literal, cast

JobStatusResponseCurrentStepType0 = Literal[
    "cog_convert", "complete", "finalize", "ogr2ogr", "quicklook", "validating"
]

JOB_STATUS_RESPONSE_CURRENT_STEP_TYPE_0_VALUES: set[
    JobStatusResponseCurrentStepType0
] = {
    "cog_convert",
    "complete",
    "finalize",
    "ogr2ogr",
    "quicklook",
    "validating",
}


def check_job_status_response_current_step_type_0(
    value: str,
) -> JobStatusResponseCurrentStepType0:
    if value in JOB_STATUS_RESPONSE_CURRENT_STEP_TYPE_0_VALUES:
        return cast(JobStatusResponseCurrentStepType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {JOB_STATUS_RESPONSE_CURRENT_STEP_TYPE_0_VALUES!r}"
    )
