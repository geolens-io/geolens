from typing import Literal, cast

StacSearchRequestCloudCoverModeType0 = Literal["filter", "query"]

STAC_SEARCH_REQUEST_CLOUD_COVER_MODE_TYPE_0_VALUES: set[
    StacSearchRequestCloudCoverModeType0
] = {
    "filter",
    "query",
}


def check_stac_search_request_cloud_cover_mode_type_0(
    value: str,
) -> StacSearchRequestCloudCoverModeType0:
    if value in STAC_SEARCH_REQUEST_CLOUD_COVER_MODE_TYPE_0_VALUES:
        return cast(StacSearchRequestCloudCoverModeType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {STAC_SEARCH_REQUEST_CLOUD_COVER_MODE_TYPE_0_VALUES!r}"
    )
