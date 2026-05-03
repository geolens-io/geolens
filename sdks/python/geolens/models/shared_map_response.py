from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.shared_layer_response import SharedLayerResponse


T = TypeVar("T", bound="SharedMapResponse")


@_attrs_define
class SharedMapResponse:
    """
    Attributes:
        basemap_style (str):
        bearing (float):
        center_lat (float):
        center_lng (float):
        description (None | str):
        layers (list[SharedLayerResponse]):
        name (str):
        pitch (float):
        zoom (float):
        has_non_public_layers (bool | Unset):  Default: False.
        show_basemap_labels (bool | Unset):  Default: True.
    """

    basemap_style: str
    bearing: float
    center_lat: float
    center_lng: float
    description: None | str
    layers: list[SharedLayerResponse]
    name: str
    pitch: float
    zoom: float
    has_non_public_layers: bool | Unset = False
    show_basemap_labels: bool | Unset = True
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        basemap_style = self.basemap_style

        bearing = self.bearing

        center_lat = self.center_lat

        center_lng = self.center_lng

        description: None | str
        description = self.description

        layers = []
        for layers_item_data in self.layers:
            layers_item = layers_item_data.to_dict()
            layers.append(layers_item)

        name = self.name

        pitch = self.pitch

        zoom = self.zoom

        has_non_public_layers = self.has_non_public_layers

        show_basemap_labels = self.show_basemap_labels

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "basemap_style": basemap_style,
                "bearing": bearing,
                "center_lat": center_lat,
                "center_lng": center_lng,
                "description": description,
                "layers": layers,
                "name": name,
                "pitch": pitch,
                "zoom": zoom,
            }
        )
        if has_non_public_layers is not UNSET:
            field_dict["has_non_public_layers"] = has_non_public_layers
        if show_basemap_labels is not UNSET:
            field_dict["show_basemap_labels"] = show_basemap_labels

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.shared_layer_response import SharedLayerResponse

        d = dict(src_dict)
        basemap_style = d.pop("basemap_style")

        bearing = d.pop("bearing")

        center_lat = d.pop("center_lat")

        center_lng = d.pop("center_lng")

        def _parse_description(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        description = _parse_description(d.pop("description"))

        layers = []
        _layers = d.pop("layers")
        for layers_item_data in _layers:
            layers_item = SharedLayerResponse.from_dict(layers_item_data)

            layers.append(layers_item)

        name = d.pop("name")

        pitch = d.pop("pitch")

        zoom = d.pop("zoom")

        has_non_public_layers = d.pop("has_non_public_layers", UNSET)

        show_basemap_labels = d.pop("show_basemap_labels", UNSET)

        shared_map_response = cls(
            basemap_style=basemap_style,
            bearing=bearing,
            center_lat=center_lat,
            center_lng=center_lng,
            description=description,
            layers=layers,
            name=name,
            pitch=pitch,
            zoom=zoom,
            has_non_public_layers=has_non_public_layers,
            show_basemap_labels=show_basemap_labels,
        )

        shared_map_response.additional_properties = d
        return shared_map_response

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
