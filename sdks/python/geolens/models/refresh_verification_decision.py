from typing import Literal, cast

RefreshVerificationDecision = Literal["allowed", "blocked", "rejected"]

REFRESH_VERIFICATION_DECISION_VALUES: set[RefreshVerificationDecision] = {
    "allowed",
    "blocked",
    "rejected",
}


def check_refresh_verification_decision(value: str) -> RefreshVerificationDecision:
    if value in REFRESH_VERIFICATION_DECISION_VALUES:
        return cast(RefreshVerificationDecision, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {REFRESH_VERIFICATION_DECISION_VALUES!r}"
    )
