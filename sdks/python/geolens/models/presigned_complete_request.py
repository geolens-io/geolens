from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


if TYPE_CHECKING:
    from ..models.presigned_part_info import PresignedPartInfo


T = TypeVar("T", bound="PresignedCompleteRequest")


@_attrs_define
class PresignedCompleteRequest:
    """
    Attributes:
        parts (list[PresignedPartInfo] | Unset): Ordered list of uploaded parts (etag + part_number) used to complete a
            multipart upload.
    """

    parts: list[PresignedPartInfo] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        parts: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.parts, Unset):
            parts = []
            for parts_item_data in self.parts:
                parts_item = parts_item_data.to_dict()
                parts.append(parts_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if parts is not UNSET:
            field_dict["parts"] = parts

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.presigned_part_info import PresignedPartInfo

        d = dict(src_dict)
        _parts = d.pop("parts", UNSET)
        parts: list[PresignedPartInfo] | Unset = UNSET
        if _parts is not UNSET:
            parts = []
            for parts_item_data in _parts:
                parts_item = PresignedPartInfo.from_dict(parts_item_data)

                parts.append(parts_item)

        presigned_complete_request = cls(
            parts=parts,
        )

        presigned_complete_request.additional_properties = d
        return presigned_complete_request

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
