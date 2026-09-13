from typing import Literal, cast

RefreshVerificationReviewReasonsItem = Literal[
    "destructive_schema_change", "empty_result", "source_count_unavailable"
]

REFRESH_VERIFICATION_REVIEW_REASONS_ITEM_VALUES: set[
    RefreshVerificationReviewReasonsItem
] = {
    "destructive_schema_change",
    "empty_result",
    "source_count_unavailable",
}


def check_refresh_verification_review_reasons_item(
    value: str,
) -> RefreshVerificationReviewReasonsItem:
    if value in REFRESH_VERIFICATION_REVIEW_REASONS_ITEM_VALUES:
        return cast(RefreshVerificationReviewReasonsItem, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {REFRESH_VERIFICATION_REVIEW_REASONS_ITEM_VALUES!r}"
    )
