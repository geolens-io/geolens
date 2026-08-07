from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="UploadConfigResponse")


@_attrs_define
class UploadConfigResponse:
    """
    Attributes:
        presigned_uploads (bool): Whether presigned S3 uploads are enabled (requires `STORAGE_PROVIDER=s3`).
        presigned_threshold_bytes (int): File size threshold (bytes) above which multipart presigned URLs are used.
        max_file_size_bytes (int): Maximum allowed upload size in bytes.
        allowed_extensions (str): Comma-separated list of allowed file extensions.
        remaining_dataset_quota (int | None | Unset): Datasets the caller may still create before hitting the per-user
            count cap, or null when no count cap is configured (unlimited). Advisory UX hint only — the cap is enforced
            server-side at upload.
    """

    presigned_uploads: bool
    presigned_threshold_bytes: int
    max_file_size_bytes: int
    allowed_extensions: str
    remaining_dataset_quota: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        presigned_uploads = self.presigned_uploads

        presigned_threshold_bytes = self.presigned_threshold_bytes

        max_file_size_bytes = self.max_file_size_bytes

        allowed_extensions = self.allowed_extensions

        remaining_dataset_quota: int | None | Unset
        if isinstance(self.remaining_dataset_quota, Unset):
            remaining_dataset_quota = UNSET
        else:
            remaining_dataset_quota = self.remaining_dataset_quota

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "presigned_uploads": presigned_uploads,
                "presigned_threshold_bytes": presigned_threshold_bytes,
                "max_file_size_bytes": max_file_size_bytes,
                "allowed_extensions": allowed_extensions,
            }
        )
        if remaining_dataset_quota is not UNSET:
            field_dict["remaining_dataset_quota"] = remaining_dataset_quota

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        presigned_uploads = d.pop("presigned_uploads")

        presigned_threshold_bytes = d.pop("presigned_threshold_bytes")

        max_file_size_bytes = d.pop("max_file_size_bytes")

        allowed_extensions = d.pop("allowed_extensions")

        def _parse_remaining_dataset_quota(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        remaining_dataset_quota = _parse_remaining_dataset_quota(
            d.pop("remaining_dataset_quota", UNSET)
        )

        upload_config_response = cls(
            presigned_uploads=presigned_uploads,
            presigned_threshold_bytes=presigned_threshold_bytes,
            max_file_size_bytes=max_file_size_bytes,
            allowed_extensions=allowed_extensions,
            remaining_dataset_quota=remaining_dataset_quota,
        )

        upload_config_response.additional_properties = d
        return upload_config_response

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
