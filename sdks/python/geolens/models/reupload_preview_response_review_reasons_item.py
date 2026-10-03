from typing import Literal, cast

ReuploadPreviewResponseReviewReasonsItem = Literal[
    "arcgis_id_coverage_unavailable",
    "arcgis_source_membership_changed",
    "coordinate_dimension_reduced",
    "destructive_schema_change",
    "empty_result",
    "geometry_type_changed",
    "source_count_unavailable",
    "srid_changed",
]

REUPLOAD_PREVIEW_RESPONSE_REVIEW_REASONS_ITEM_VALUES: set[
    ReuploadPreviewResponseReviewReasonsItem
] = {
    "arcgis_id_coverage_unavailable",
    "arcgis_source_membership_changed",
    "coordinate_dimension_reduced",
    "destructive_schema_change",
    "empty_result",
    "geometry_type_changed",
    "source_count_unavailable",
    "srid_changed",
}


def check_reupload_preview_response_review_reasons_item(
    value: str,
) -> ReuploadPreviewResponseReviewReasonsItem:
    if value in REUPLOAD_PREVIEW_RESPONSE_REVIEW_REASONS_ITEM_VALUES:
        return cast(ReuploadPreviewResponseReviewReasonsItem, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {REUPLOAD_PREVIEW_RESPONSE_REVIEW_REASONS_ITEM_VALUES!r}"
    )
