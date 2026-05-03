from typing import Literal, cast

ValidationIssueSeverity = Literal["error", "warning"]

VALIDATION_ISSUE_SEVERITY_VALUES: set[ValidationIssueSeverity] = {
    "error",
    "warning",
}


def check_validation_issue_severity(value: str) -> ValidationIssueSeverity:
    if value in VALIDATION_ISSUE_SEVERITY_VALUES:
        return cast(ValidationIssueSeverity, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {VALIDATION_ISSUE_SEVERITY_VALUES!r}"
    )
