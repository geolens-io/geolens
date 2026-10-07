from typing import Literal, cast

RefreshVerificationReviewReasonsItem = Literal[
    "arcgis_id_coverage_unavailable",
    "arcgis_source_membership_changed",
    "coordinate_dimension_reduced",
    "destructive_schema_change",
    "empty_result",
    "geometry_type_changed",
    "live_data_changed",
    "source_count_unavailable",
    "srid_changed",
]

REFRESH_VERIFICATION_REVIEW_REASONS_ITEM_VALUES: set[
    RefreshVerificationReviewReasonsItem
] = {
    "arcgis_id_coverage_unavailable",
    "arcgis_source_membership_changed",
    "coordinate_dimension_reduced",
    "destructive_schema_change",
    "empty_result",
    "geometry_type_changed",
    "live_data_changed",
    "source_count_unavailable",
    "srid_changed",
}


def check_refresh_verification_review_reasons_item(
    value: str,
) -> RefreshVerificationReviewReasonsItem:
    if value in REFRESH_VERIFICATION_REVIEW_REASONS_ITEM_VALUES:
        return cast(RefreshVerificationReviewReasonsItem, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {REFRESH_VERIFICATION_REVIEW_REASONS_ITEM_VALUES!r}"
    )
