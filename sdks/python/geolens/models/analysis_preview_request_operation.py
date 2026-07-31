from typing import Literal, cast

AnalysisPreviewRequestOperation = Literal[
    "buffer",
    "centroid",
    "clip",
    "intersect",
    "measure",
    "select_by_location",
    "spatial_join",
]

ANALYSIS_PREVIEW_REQUEST_OPERATION_VALUES: set[AnalysisPreviewRequestOperation] = {
    "buffer",
    "centroid",
    "clip",
    "intersect",
    "measure",
    "select_by_location",
    "spatial_join",
}


def check_analysis_preview_request_operation(
    value: str,
) -> AnalysisPreviewRequestOperation:
    if value in ANALYSIS_PREVIEW_REQUEST_OPERATION_VALUES:
        return cast(AnalysisPreviewRequestOperation, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {ANALYSIS_PREVIEW_REQUEST_OPERATION_VALUES!r}"
    )
