from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="MapDefaultsResponse")


@_attrs_define
class MapDefaultsResponse:
    """
    Attributes:
        center_lat (float): Currently configured initial center latitude.
        center_lng (float): Currently configured initial center longitude.
        zoom (float): Currently configured initial zoom level.
    """

    center_lat: float
    center_lng: float
    zoom: float
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        center_lat = self.center_lat

        center_lng = self.center_lng

        zoom = self.zoom

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "center_lat": center_lat,
                "center_lng": center_lng,
                "zoom": zoom,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        center_lat = d.pop("center_lat")

        center_lng = d.pop("center_lng")

        zoom = d.pop("zoom")

        map_defaults_response = cls(
            center_lat=center_lat,
            center_lng=center_lng,
            zoom=zoom,
        )

        map_defaults_response.additional_properties = d
        return map_defaults_response

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
