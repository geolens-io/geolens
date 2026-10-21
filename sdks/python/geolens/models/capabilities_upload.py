from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast


T = TypeVar("T", bound="CapabilitiesUpload")


@_attrs_define
class CapabilitiesUpload:
    """
    Attributes:
        max_file_size_bytes (int): Largest accepted upload, in bytes.
        allowed_extensions (list[str]): Extensions a publish manifest can carry, a subset of the upload allowlist.
        presigned (bool): Whether direct-to-S3 uploads are enabled.
    """

    max_file_size_bytes: int
    allowed_extensions: list[str]
    presigned: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        max_file_size_bytes = self.max_file_size_bytes

        allowed_extensions = self.allowed_extensions

        presigned = self.presigned

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "max_file_size_bytes": max_file_size_bytes,
                "allowed_extensions": allowed_extensions,
                "presigned": presigned,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        max_file_size_bytes = d.pop("max_file_size_bytes")

        allowed_extensions = cast(list[str], d.pop("allowed_extensions"))

        presigned = d.pop("presigned")

        capabilities_upload = cls(
            max_file_size_bytes=max_file_size_bytes,
            allowed_extensions=allowed_extensions,
            presigned=presigned,
        )

        capabilities_upload.additional_properties = d
        return capabilities_upload

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
