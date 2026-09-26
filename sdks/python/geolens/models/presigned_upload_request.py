from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.presigned_upload_request_kind_type_0 import (
    check_presigned_upload_request_kind_type_0,
)
from ..models.presigned_upload_request_kind_type_0 import (
    PresignedUploadRequestKindType0,
)
from typing import cast


T = TypeVar("T", bound="PresignedUploadRequest")


@_attrs_define
class PresignedUploadRequest:
    """
    Attributes:
        filename (str): Original filename being uploaded. Used to determine the file extension and content disposition.
        file_size (int): Total file size in bytes. Used to decide between single-part and multipart upload.
        content_type (str | Unset): MIME type to associate with the uploaded object. Default: 'application/octet-
            stream'.
        kind (None | PresignedUploadRequestKindType0 | Unset): 'tiles3d' uploads a 3D Tiles tileset as a .zip or .3tz
            archive holding tileset.json. Omit it for any other file; a .zip without it is read as geospatial data, and a
            .3tz without it is refused. 'pointcloud' uploads a COPC point cloud as a .laz file; a .laz without it is
            refused.
    """

    filename: str
    file_size: int
    content_type: str | Unset = "application/octet-stream"
    kind: None | PresignedUploadRequestKindType0 | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        filename = self.filename

        file_size = self.file_size

        content_type = self.content_type

        kind: None | str | Unset
        if isinstance(self.kind, Unset):
            kind = UNSET
        elif isinstance(self.kind, str):
            kind = self.kind
        else:
            kind = self.kind

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "filename": filename,
                "file_size": file_size,
            }
        )
        if content_type is not UNSET:
            field_dict["content_type"] = content_type
        if kind is not UNSET:
            field_dict["kind"] = kind

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        filename = d.pop("filename")

        file_size = d.pop("file_size")

        content_type = d.pop("content_type", UNSET)

        def _parse_kind(data: object) -> None | PresignedUploadRequestKindType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                kind_type_0 = check_presigned_upload_request_kind_type_0(data)

                return kind_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | PresignedUploadRequestKindType0 | Unset, data)

        kind = _parse_kind(d.pop("kind", UNSET))

        presigned_upload_request = cls(
            filename=filename,
            file_size=file_size,
            content_type=content_type,
            kind=kind,
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
