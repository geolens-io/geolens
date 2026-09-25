from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from .. import types

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="BodyUploadFileIngestUploadPost")


@_attrs_define
class BodyUploadFileIngestUploadPost:
    """
    Attributes:
        file (str):
        kind (None | str | Unset): 'tiles3d' uploads a 3D Tiles tileset as a .zip or .3tz archive holding tileset.json.
            Omit it for any other file; a .zip without it is read as geospatial data, and a .3tz without it is refused.
    """

    file: str
    kind: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        file = self.file

        kind: None | str | Unset
        if isinstance(self.kind, Unset):
            kind = UNSET
        else:
            kind = self.kind

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "file": file,
            }
        )
        if kind is not UNSET:
            field_dict["kind"] = kind

        return field_dict

    def to_multipart(self) -> types.RequestFiles:
        files: types.RequestFiles = []

        files.append(("file", (None, str(self.file).encode(), "text/plain")))

        if not isinstance(self.kind, Unset):
            if isinstance(self.kind, str):
                files.append(("kind", (None, str(self.kind).encode(), "text/plain")))
            else:
                files.append(("kind", (None, str(self.kind).encode(), "text/plain")))

        for prop_name, prop in self.additional_properties.items():
            files.append((prop_name, (None, str(prop).encode(), "text/plain")))

        return files

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        file = d.pop("file")

        def _parse_kind(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        kind = _parse_kind(d.pop("kind", UNSET))

        body_upload_file_ingest_upload_post = cls(
            file=file,
            kind=kind,
        )

        body_upload_file_ingest_upload_post.additional_properties = d
        return body_upload_file_ingest_upload_post

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
