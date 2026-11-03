from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast


T = TypeVar("T", bound="ArcgisTranslatedView")


@_attrs_define
class ArcgisTranslatedView:
    """
    Attributes:
        basemap_style (None | str): The GeoLens basemap id.
        center_lng (float | None): Initial center longitude.
        center_lat (float | None): Initial center latitude.
        zoom (float | None): Initial zoom level.
        bearing (float | None): Initial rotation in degrees.
    """

    basemap_style: None | str
    center_lng: float | None
    center_lat: float | None
    zoom: float | None
    bearing: float | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        basemap_style: None | str
        basemap_style = self.basemap_style

        center_lng: float | None
        center_lng = self.center_lng

        center_lat: float | None
        center_lat = self.center_lat

        zoom: float | None
        zoom = self.zoom

        bearing: float | None
        bearing = self.bearing

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "basemap_style": basemap_style,
                "center_lng": center_lng,
                "center_lat": center_lat,
                "zoom": zoom,
                "bearing": bearing,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_basemap_style(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        basemap_style = _parse_basemap_style(d.pop("basemap_style"))

        def _parse_center_lng(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        center_lng = _parse_center_lng(d.pop("center_lng"))

        def _parse_center_lat(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        center_lat = _parse_center_lat(d.pop("center_lat"))

        def _parse_zoom(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        zoom = _parse_zoom(d.pop("zoom"))

        def _parse_bearing(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        bearing = _parse_bearing(d.pop("bearing"))

        arcgis_translated_view = cls(
            basemap_style=basemap_style,
            center_lng=center_lng,
            center_lat=center_lat,
            zoom=zoom,
            bearing=bearing,
        )

        arcgis_translated_view.additional_properties = d
        return arcgis_translated_view

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
