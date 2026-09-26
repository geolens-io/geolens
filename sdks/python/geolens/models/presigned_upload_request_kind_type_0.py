from typing import Literal, cast

PresignedUploadRequestKindType0 = Literal["pointcloud", "tiles3d"]

PRESIGNED_UPLOAD_REQUEST_KIND_TYPE_0_VALUES: set[PresignedUploadRequestKindType0] = {
    "pointcloud",
    "tiles3d",
}


def check_presigned_upload_request_kind_type_0(
    value: str,
) -> PresignedUploadRequestKindType0:
    if value in PRESIGNED_UPLOAD_REQUEST_KIND_TYPE_0_VALUES:
        return cast(PresignedUploadRequestKindType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {PRESIGNED_UPLOAD_REQUEST_KIND_TYPE_0_VALUES!r}"
    )
