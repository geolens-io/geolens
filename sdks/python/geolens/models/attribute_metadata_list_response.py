from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.attribute_metadata_response import AttributeMetadataResponse


T = TypeVar("T", bound="AttributeMetadataListResponse")


@_attrs_define
class AttributeMetadataListResponse:
    """
    Attributes:
        attributes (list[AttributeMetadataResponse]):
        total (int):
    """

    attributes: list[AttributeMetadataResponse]
    total: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        attributes = []
        for attributes_item_data in self.attributes:
            attributes_item = attributes_item_data.to_dict()
            attributes.append(attributes_item)

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "attributes": attributes,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.attribute_metadata_response import AttributeMetadataResponse

        d = dict(src_dict)
        attributes = []
        _attributes = d.pop("attributes")
        for attributes_item_data in _attributes:
            attributes_item = AttributeMetadataResponse.from_dict(attributes_item_data)

            attributes.append(attributes_item)

        total = d.pop("total")

        attribute_metadata_list_response = cls(
            attributes=attributes,
            total=total,
        )

        attribute_metadata_list_response.additional_properties = d
        return attribute_metadata_list_response

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
