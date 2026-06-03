from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.basemap_config import BasemapConfig
    from ..models.shared_layer_response import SharedLayerResponse
    from ..models.terrain_config import TerrainConfig


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
        basemap_config (BasemapConfig | None | Unset):
        has_non_public_layers (bool | Unset):  Default: False.
        show_basemap_labels (bool | Unset):  Default: True.
        terrain_config (None | TerrainConfig | Unset):
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
    basemap_config: BasemapConfig | None | Unset = UNSET
    has_non_public_layers: bool | Unset = False
    show_basemap_labels: bool | Unset = True
    terrain_config: None | TerrainConfig | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.basemap_config import BasemapConfig
        from ..models.terrain_config import TerrainConfig

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

        basemap_config: dict[str, Any] | None | Unset
        if isinstance(self.basemap_config, Unset):
            basemap_config = UNSET
        elif isinstance(self.basemap_config, BasemapConfig):
            basemap_config = self.basemap_config.to_dict()
        else:
            basemap_config = self.basemap_config

        has_non_public_layers = self.has_non_public_layers

        show_basemap_labels = self.show_basemap_labels

        terrain_config: dict[str, Any] | None | Unset
        if isinstance(self.terrain_config, Unset):
            terrain_config = UNSET
        elif isinstance(self.terrain_config, TerrainConfig):
            terrain_config = self.terrain_config.to_dict()
        else:
            terrain_config = self.terrain_config

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
        if basemap_config is not UNSET:
            field_dict["basemap_config"] = basemap_config
        if has_non_public_layers is not UNSET:
            field_dict["has_non_public_layers"] = has_non_public_layers
        if show_basemap_labels is not UNSET:
            field_dict["show_basemap_labels"] = show_basemap_labels
        if terrain_config is not UNSET:
            field_dict["terrain_config"] = terrain_config

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.basemap_config import BasemapConfig
        from ..models.shared_layer_response import SharedLayerResponse
        from ..models.terrain_config import TerrainConfig

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

        def _parse_basemap_config(data: object) -> BasemapConfig | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                basemap_config_type_0 = BasemapConfig.from_dict(data)

                return basemap_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(BasemapConfig | None | Unset, data)

        basemap_config = _parse_basemap_config(d.pop("basemap_config", UNSET))

        has_non_public_layers = d.pop("has_non_public_layers", UNSET)

        show_basemap_labels = d.pop("show_basemap_labels", UNSET)

        def _parse_terrain_config(data: object) -> None | TerrainConfig | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                terrain_config_type_0 = TerrainConfig.from_dict(data)

                return terrain_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TerrainConfig | Unset, data)

        terrain_config = _parse_terrain_config(d.pop("terrain_config", UNSET))

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
            basemap_config=basemap_config,
            has_non_public_layers=has_non_public_layers,
            show_basemap_labels=show_basemap_labels,
            terrain_config=terrain_config,
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
