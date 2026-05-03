from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.vrt_generation_item import VrtGenerationItem


T = TypeVar("T", bound="VrtGenerationListResponse")


@_attrs_define
class VrtGenerationListResponse:
    """
    Attributes:
        generations (list[VrtGenerationItem]):
        total (int):
    """

    generations: list[VrtGenerationItem]
    total: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        generations = []
        for generations_item_data in self.generations:
            generations_item = generations_item_data.to_dict()
            generations.append(generations_item)

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "generations": generations,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.vrt_generation_item import VrtGenerationItem

        d = dict(src_dict)
        generations = []
        _generations = d.pop("generations")
        for generations_item_data in _generations:
            generations_item = VrtGenerationItem.from_dict(generations_item_data)

            generations.append(generations_item)

        total = d.pop("total")

        vrt_generation_list_response = cls(
            generations=generations,
            total=total,
        )

        vrt_generation_list_response.additional_properties = d
        return vrt_generation_list_response

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
