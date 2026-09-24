from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal


T = TypeVar("T", bound="PresignedUploadRequest")


@_attrs_define
class PresignedUploadRequest:
    """
    Attributes:
        filename (str): Original filename being uploaded. Used to determine the file extension and content disposition.
        file_size (int): Total file size in bytes. Used to decide between single-part and multipart upload.
        content_type (str | Unset): MIME type to associate with the uploaded object. Default: 'application/octet-
            stream'.
        kind (Literal['tiles3d'] | None | Unset): 'tiles3d' uploads a 3D Tiles tileset as a .zip archive holding
            tileset.json. Omit it for any other file; a zip without it is read as geospatial data.
    """

    filename: str
    file_size: int
    content_type: str | Unset = "application/octet-stream"
    kind: Literal["tiles3d"] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        filename = self.filename

        file_size = self.file_size

        content_type = self.content_type

        kind: Literal["tiles3d"] | None | Unset
        if isinstance(self.kind, Unset):
            kind = UNSET
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

        def _parse_kind(data: object) -> Literal["tiles3d"] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            kind_type_0 = cast(Literal["tiles3d"], data)
            if kind_type_0 != "tiles3d":
                raise ValueError(
                    f"kind_type_0 must match const 'tiles3d', got '{kind_type_0}'"
                )
            return kind_type_0
            return cast(Literal["tiles3d"] | None | Unset, data)

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
