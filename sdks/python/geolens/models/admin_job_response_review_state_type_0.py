from typing import Literal, cast

AdminJobResponseReviewStateType0 = Literal["awaiting", "resolved"]

ADMIN_JOB_RESPONSE_REVIEW_STATE_TYPE_0_VALUES: set[AdminJobResponseReviewStateType0] = {
    "awaiting",
    "resolved",
}


def check_admin_job_response_review_state_type_0(
    value: str,
) -> AdminJobResponseReviewStateType0:
    if value in ADMIN_JOB_RESPONSE_REVIEW_STATE_TYPE_0_VALUES:
        return cast(AdminJobResponseReviewStateType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {ADMIN_JOB_RESPONSE_REVIEW_STATE_TYPE_0_VALUES!r}"
    )
