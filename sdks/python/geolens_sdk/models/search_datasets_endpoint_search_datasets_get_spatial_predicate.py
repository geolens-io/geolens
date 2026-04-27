from typing import Literal, cast

SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate = Literal[
    "intersects", "within"
]

SEARCH_DATASETS_ENDPOINT_SEARCH_DATASETS_GET_SPATIAL_PREDICATE_VALUES: set[
    SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate
] = {
    "intersects",
    "within",
}


def check_search_datasets_endpoint_search_datasets_get_spatial_predicate(
    value: str,
) -> SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate:
    if value in SEARCH_DATASETS_ENDPOINT_SEARCH_DATASETS_GET_SPATIAL_PREDICATE_VALUES:
        return cast(SearchDatasetsEndpointSearchDatasetsGetSpatialPredicate, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {SEARCH_DATASETS_ENDPOINT_SEARCH_DATASETS_GET_SPATIAL_PREDICATE_VALUES!r}"
    )
