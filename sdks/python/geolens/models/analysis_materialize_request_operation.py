from typing import Literal, cast

AnalysisMaterializeRequestOperation = Literal["buffer", "centroid", "clip", "dissolve"]

ANALYSIS_MATERIALIZE_REQUEST_OPERATION_VALUES: set[
    AnalysisMaterializeRequestOperation
] = {
    "buffer",
    "centroid",
    "clip",
    "dissolve",
}


def check_analysis_materialize_request_operation(
    value: str,
) -> AnalysisMaterializeRequestOperation:
    if value in ANALYSIS_MATERIALIZE_REQUEST_OPERATION_VALUES:
        return cast(AnalysisMaterializeRequestOperation, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {ANALYSIS_MATERIALIZE_REQUEST_OPERATION_VALUES!r}"
    )
