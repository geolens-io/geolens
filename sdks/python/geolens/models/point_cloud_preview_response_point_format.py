from typing import Literal, cast

PointCloudPreviewResponsePointFormat = Literal[6, 7, 8]

POINT_CLOUD_PREVIEW_RESPONSE_POINT_FORMAT_VALUES: set[
    PointCloudPreviewResponsePointFormat
] = {
    6,
    7,
    8,
}


def check_point_cloud_preview_response_point_format(
    value: int,
) -> PointCloudPreviewResponsePointFormat:
    if value in POINT_CLOUD_PREVIEW_RESPONSE_POINT_FORMAT_VALUES:
        return cast(PointCloudPreviewResponsePointFormat, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {POINT_CLOUD_PREVIEW_RESPONSE_POINT_FORMAT_VALUES!r}"
    )
