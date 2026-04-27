from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.map_summary_response import MapSummaryResponse


T = TypeVar("T", bound="MapListResponse")


@_attrs_define
class MapListResponse:
    """
    Attributes:
        maps (list[MapSummaryResponse]):
        total (int):
    """

    maps: list[MapSummaryResponse]
    total: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        maps = []
        for maps_item_data in self.maps:
            maps_item = maps_item_data.to_dict()
            maps.append(maps_item)

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "maps": maps,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.map_summary_response import MapSummaryResponse

        d = dict(src_dict)
        maps = []
        _maps = d.pop("maps")
        for maps_item_data in _maps:
            maps_item = MapSummaryResponse.from_dict(maps_item_data)

            maps.append(maps_item)

        total = d.pop("total")

        map_list_response = cls(
            maps=maps,
            total=total,
        )

        map_list_response.additional_properties = d
        return map_list_response

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
