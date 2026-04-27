from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="UploadConfigResponse")


@_attrs_define
class UploadConfigResponse:
    """
    Attributes:
        allowed_extensions (str): Comma-separated list of allowed file extensions.
        max_file_size_bytes (int): Maximum allowed upload size in bytes.
        presigned_threshold_bytes (int): File size threshold (bytes) above which multipart presigned URLs are used.
        presigned_uploads (bool): Whether presigned S3 uploads are enabled (requires `STORAGE_PROVIDER=s3`).
    """

    allowed_extensions: str
    max_file_size_bytes: int
    presigned_threshold_bytes: int
    presigned_uploads: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        allowed_extensions = self.allowed_extensions

        max_file_size_bytes = self.max_file_size_bytes

        presigned_threshold_bytes = self.presigned_threshold_bytes

        presigned_uploads = self.presigned_uploads

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "allowed_extensions": allowed_extensions,
                "max_file_size_bytes": max_file_size_bytes,
                "presigned_threshold_bytes": presigned_threshold_bytes,
                "presigned_uploads": presigned_uploads,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        allowed_extensions = d.pop("allowed_extensions")

        max_file_size_bytes = d.pop("max_file_size_bytes")

        presigned_threshold_bytes = d.pop("presigned_threshold_bytes")

        presigned_uploads = d.pop("presigned_uploads")

        upload_config_response = cls(
            allowed_extensions=allowed_extensions,
            max_file_size_bytes=max_file_size_bytes,
            presigned_threshold_bytes=presigned_threshold_bytes,
            presigned_uploads=presigned_uploads,
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
