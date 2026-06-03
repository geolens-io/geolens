from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


T = TypeVar("T", bound="PresignedUploadRequest")


@_attrs_define
class PresignedUploadRequest:
    """
    Attributes:
        file_size (int): Total file size in bytes. Used to decide between single-part and multipart upload.
        filename (str): Original filename being uploaded. Used to determine the file extension and content disposition.
        content_type (str | Unset): MIME type to associate with the uploaded object. Default: 'application/octet-
            stream'.
    """

    file_size: int
    filename: str
    content_type: str | Unset = "application/octet-stream"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        file_size = self.file_size

        filename = self.filename

        content_type = self.content_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "file_size": file_size,
                "filename": filename,
            }
        )
        if content_type is not UNSET:
            field_dict["content_type"] = content_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        file_size = d.pop("file_size")

        filename = d.pop("filename")

        content_type = d.pop("content_type", UNSET)

        presigned_upload_request = cls(
            file_size=file_size,
            filename=filename,
            content_type=content_type,
        )

        presigned_upload_request.additional_properties = d
        return presigned_upload_request

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
