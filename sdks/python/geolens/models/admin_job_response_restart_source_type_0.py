from typing import Literal, cast

AdminJobResponseRestartSourceType0 = Literal["service", "url"]

ADMIN_JOB_RESPONSE_RESTART_SOURCE_TYPE_0_VALUES: set[
    AdminJobResponseRestartSourceType0
] = {
    "service",
    "url",
}


def check_admin_job_response_restart_source_type_0(
    value: str,
) -> AdminJobResponseRestartSourceType0:
    if value in ADMIN_JOB_RESPONSE_RESTART_SOURCE_TYPE_0_VALUES:
        return cast(AdminJobResponseRestartSourceType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {ADMIN_JOB_RESPONSE_RESTART_SOURCE_TYPE_0_VALUES!r}"
    )
