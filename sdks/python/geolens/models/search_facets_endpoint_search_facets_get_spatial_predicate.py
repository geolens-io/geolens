from typing import Literal, cast

SearchFacetsEndpointSearchFacetsGetSpatialPredicate = Literal["intersects", "within"]

SEARCH_FACETS_ENDPOINT_SEARCH_FACETS_GET_SPATIAL_PREDICATE_VALUES: set[
    SearchFacetsEndpointSearchFacetsGetSpatialPredicate
] = {
    "intersects",
    "within",
}


def check_search_facets_endpoint_search_facets_get_spatial_predicate(
    value: str,
) -> SearchFacetsEndpointSearchFacetsGetSpatialPredicate:
    if value in SEARCH_FACETS_ENDPOINT_SEARCH_FACETS_GET_SPATIAL_PREDICATE_VALUES:
        return cast(SearchFacetsEndpointSearchFacetsGetSpatialPredicate, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {SEARCH_FACETS_ENDPOINT_SEARCH_FACETS_GET_SPATIAL_PREDICATE_VALUES!r}"
    )
