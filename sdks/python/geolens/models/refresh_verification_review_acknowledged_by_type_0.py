from typing import Literal, cast

RefreshVerificationReviewAcknowledgedByType0 = Literal["accepted_run", "preview"]

REFRESH_VERIFICATION_REVIEW_ACKNOWLEDGED_BY_TYPE_0_VALUES: set[
    RefreshVerificationReviewAcknowledgedByType0
] = {
    "accepted_run",
    "preview",
}


def check_refresh_verification_review_acknowledged_by_type_0(
    value: str,
) -> RefreshVerificationReviewAcknowledgedByType0:
    if value in REFRESH_VERIFICATION_REVIEW_ACKNOWLEDGED_BY_TYPE_0_VALUES:
        return cast(RefreshVerificationReviewAcknowledgedByType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {REFRESH_VERIFICATION_REVIEW_ACKNOWLEDGED_BY_TYPE_0_VALUES!r}"
    )
