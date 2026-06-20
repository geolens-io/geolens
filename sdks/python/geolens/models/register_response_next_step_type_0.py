from typing import Literal, cast

RegisterResponseNextStepType0 = Literal["await_approval", "verify_email"]

REGISTER_RESPONSE_NEXT_STEP_TYPE_0_VALUES: set[RegisterResponseNextStepType0] = {
    "await_approval",
    "verify_email",
}


def check_register_response_next_step_type_0(
    value: str,
) -> RegisterResponseNextStepType0:
    if value in REGISTER_RESPONSE_NEXT_STEP_TYPE_0_VALUES:
        return cast(RegisterResponseNextStepType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {REGISTER_RESPONSE_NEXT_STEP_TYPE_0_VALUES!r}"
    )
