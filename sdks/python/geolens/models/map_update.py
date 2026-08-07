from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.map_visibility import check_map_visibility
from ..models.map_visibility import MapVisibility
from typing import cast

if TYPE_CHECKING:
    from ..models.basemap_config import BasemapConfig
    from ..models.map_layer_input import MapLayerInput
    from ..models.terrain_config import TerrainConfig


T = TypeVar("T", bound="MapUpdate")


@_attrs_define
class MapUpdate:
    """
    Attributes:
        name (None | str | Unset):
        description (None | str | Unset):
        notes (None | str | Unset):
        center_lng (float | None | Unset): Map center longitude
        center_lat (float | None | Unset): Map center latitude
        zoom (float | None | Unset): Map zoom level
        bearing (float | None | Unset): Map rotation in degrees
        pitch (float | None | Unset): Map tilt in degrees (0-85)
        basemap_style (None | str | Unset): Basemap style ID or URL
        show_basemap_labels (bool | None | Unset):
        basemap_config (BasemapConfig | None | Unset): Curated map-level basemap appearance preferences
        terrain_config (None | TerrainConfig | Unset): Map-level terrain source and exaggeration preferences
        visibility (MapVisibility | None | Unset): private, internal, or public
        layers (list[MapLayerInput] | None | Unset): Full replacement layer list (max 200 layers)
        plugins (list[str] | None | Unset): Enabled plugin IDs, e.g. ['measurement']
        legend_title (None | str | Unset): Custom map-level legend title. Null/empty leaves the legend without a heading
            override (ENH-06).
    """

    name: None | str | Unset = UNSET
    description: None | str | Unset = UNSET
    notes: None | str | Unset = UNSET
    center_lng: float | None | Unset = UNSET
    center_lat: float | None | Unset = UNSET
    zoom: float | None | Unset = UNSET
    bearing: float | None | Unset = UNSET
    pitch: float | None | Unset = UNSET
    basemap_style: None | str | Unset = UNSET
    show_basemap_labels: bool | None | Unset = UNSET
    basemap_config: BasemapConfig | None | Unset = UNSET
    terrain_config: None | TerrainConfig | Unset = UNSET
    visibility: MapVisibility | None | Unset = UNSET
    layers: list[MapLayerInput] | None | Unset = UNSET
    plugins: list[str] | None | Unset = UNSET
    legend_title: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.basemap_config import BasemapConfig
        from ..models.terrain_config import TerrainConfig

        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        notes: None | str | Unset
        if isinstance(self.notes, Unset):
            notes = UNSET
        else:
            notes = self.notes

        center_lng: float | None | Unset
        if isinstance(self.center_lng, Unset):
            center_lng = UNSET
        else:
            center_lng = self.center_lng

        center_lat: float | None | Unset
        if isinstance(self.center_lat, Unset):
            center_lat = UNSET
        else:
            center_lat = self.center_lat

        zoom: float | None | Unset
        if isinstance(self.zoom, Unset):
            zoom = UNSET
        else:
            zoom = self.zoom

        bearing: float | None | Unset
        if isinstance(self.bearing, Unset):
            bearing = UNSET
        else:
            bearing = self.bearing

        pitch: float | None | Unset
        if isinstance(self.pitch, Unset):
            pitch = UNSET
        else:
            pitch = self.pitch

        basemap_style: None | str | Unset
        if isinstance(self.basemap_style, Unset):
            basemap_style = UNSET
        else:
            basemap_style = self.basemap_style

        show_basemap_labels: bool | None | Unset
        if isinstance(self.show_basemap_labels, Unset):
            show_basemap_labels = UNSET
        else:
            show_basemap_labels = self.show_basemap_labels

        basemap_config: dict[str, Any] | None | Unset
        if isinstance(self.basemap_config, Unset):
            basemap_config = UNSET
        elif isinstance(self.basemap_config, BasemapConfig):
            basemap_config = self.basemap_config.to_dict()
        else:
            basemap_config = self.basemap_config

        terrain_config: dict[str, Any] | None | Unset
        if isinstance(self.terrain_config, Unset):
            terrain_config = UNSET
        elif isinstance(self.terrain_config, TerrainConfig):
            terrain_config = self.terrain_config.to_dict()
        else:
            terrain_config = self.terrain_config

        visibility: None | str | Unset
        if isinstance(self.visibility, Unset):
            visibility = UNSET
        elif isinstance(self.visibility, str):
            visibility = self.visibility
        else:
            visibility = self.visibility

        layers: list[dict[str, Any]] | None | Unset
        if isinstance(self.layers, Unset):
            layers = UNSET
        elif isinstance(self.layers, list):
            layers = []
            for layers_type_0_item_data in self.layers:
                layers_type_0_item = layers_type_0_item_data.to_dict()
                layers.append(layers_type_0_item)

        else:
            layers = self.layers

        plugins: list[str] | None | Unset
        if isinstance(self.plugins, Unset):
            plugins = UNSET
        elif isinstance(self.plugins, list):
            plugins = self.plugins

        else:
            plugins = self.plugins

        legend_title: None | str | Unset
        if isinstance(self.legend_title, Unset):
            legend_title = UNSET
        else:
            legend_title = self.legend_title

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if name is not UNSET:
            field_dict["name"] = name
        if description is not UNSET:
            field_dict["description"] = description
        if notes is not UNSET:
            field_dict["notes"] = notes
        if center_lng is not UNSET:
            field_dict["center_lng"] = center_lng
        if center_lat is not UNSET:
            field_dict["center_lat"] = center_lat
        if zoom is not UNSET:
            field_dict["zoom"] = zoom
        if bearing is not UNSET:
            field_dict["bearing"] = bearing
        if pitch is not UNSET:
            field_dict["pitch"] = pitch
        if basemap_style is not UNSET:
            field_dict["basemap_style"] = basemap_style
        if show_basemap_labels is not UNSET:
            field_dict["show_basemap_labels"] = show_basemap_labels
        if basemap_config is not UNSET:
            field_dict["basemap_config"] = basemap_config
        if terrain_config is not UNSET:
            field_dict["terrain_config"] = terrain_config
        if visibility is not UNSET:
            field_dict["visibility"] = visibility
        if layers is not UNSET:
            field_dict["layers"] = layers
        if plugins is not UNSET:
            field_dict["plugins"] = plugins
        if legend_title is not UNSET:
            field_dict["legend_title"] = legend_title

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.basemap_config import BasemapConfig
        from ..models.map_layer_input import MapLayerInput
        from ..models.terrain_config import TerrainConfig

        d = dict(src_dict)

        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_notes(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        notes = _parse_notes(d.pop("notes", UNSET))

        def _parse_center_lng(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        center_lng = _parse_center_lng(d.pop("center_lng", UNSET))

        def _parse_center_lat(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        center_lat = _parse_center_lat(d.pop("center_lat", UNSET))

        def _parse_zoom(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        zoom = _parse_zoom(d.pop("zoom", UNSET))

        def _parse_bearing(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        bearing = _parse_bearing(d.pop("bearing", UNSET))

        def _parse_pitch(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        pitch = _parse_pitch(d.pop("pitch", UNSET))

        def _parse_basemap_style(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        basemap_style = _parse_basemap_style(d.pop("basemap_style", UNSET))

        def _parse_show_basemap_labels(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        show_basemap_labels = _parse_show_basemap_labels(
            d.pop("show_basemap_labels", UNSET)
        )

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

        def _parse_visibility(data: object) -> MapVisibility | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                visibility_type_0 = check_map_visibility(data)

                return visibility_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MapVisibility | None | Unset, data)

        visibility = _parse_visibility(d.pop("visibility", UNSET))

        def _parse_layers(data: object) -> list[MapLayerInput] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                layers_type_0 = []
                _layers_type_0 = data
                for layers_type_0_item_data in _layers_type_0:
                    layers_type_0_item = MapLayerInput.from_dict(
                        layers_type_0_item_data
                    )

                    layers_type_0.append(layers_type_0_item)

                return layers_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[MapLayerInput] | None | Unset, data)

        layers = _parse_layers(d.pop("layers", UNSET))

        def _parse_plugins(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                plugins_type_0 = cast(list[str], data)

                return plugins_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        plugins = _parse_plugins(d.pop("plugins", UNSET))

        def _parse_legend_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        legend_title = _parse_legend_title(d.pop("legend_title", UNSET))

        map_update = cls(
            name=name,
            description=description,
            notes=notes,
            center_lng=center_lng,
            center_lat=center_lat,
            zoom=zoom,
            bearing=bearing,
            pitch=pitch,
            basemap_style=basemap_style,
            show_basemap_labels=show_basemap_labels,
            basemap_config=basemap_config,
            terrain_config=terrain_config,
            visibility=visibility,
            layers=layers,
            plugins=plugins,
            legend_title=legend_title,
        )

        map_update.additional_properties = d
        return map_update

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
