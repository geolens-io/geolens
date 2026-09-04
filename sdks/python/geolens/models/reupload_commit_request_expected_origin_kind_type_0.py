from typing import Literal, cast

ReuploadCommitRequestExpectedOriginKindType0 = Literal[
    "created", "postgis", "service", "stac", "upload"
]

REUPLOAD_COMMIT_REQUEST_EXPECTED_ORIGIN_KIND_TYPE_0_VALUES: set[
    ReuploadCommitRequestExpectedOriginKindType0
] = {
    "created",
    "postgis",
    "service",
    "stac",
    "upload",
}


def check_reupload_commit_request_expected_origin_kind_type_0(
    value: str,
) -> ReuploadCommitRequestExpectedOriginKindType0:
    if value in REUPLOAD_COMMIT_REQUEST_EXPECTED_ORIGIN_KIND_TYPE_0_VALUES:
        return cast(ReuploadCommitRequestExpectedOriginKindType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {REUPLOAD_COMMIT_REQUEST_EXPECTED_ORIGIN_KIND_TYPE_0_VALUES!r}"
    )
