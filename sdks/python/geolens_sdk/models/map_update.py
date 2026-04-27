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
    from ..models.map_layer_input import MapLayerInput


T = TypeVar("T", bound="MapUpdate")


@_attrs_define
class MapUpdate:
    """
    Attributes:
        basemap_style (None | str | Unset): Basemap style ID or URL
        bearing (float | None | Unset): Map rotation in degrees
        center_lat (float | None | Unset): Map center latitude
        center_lng (float | None | Unset): Map center longitude
        description (None | str | Unset):
        layers (list[MapLayerInput] | None | Unset): Full replacement layer list (max 200 layers)
        name (None | str | Unset):
        notes (None | str | Unset):
        pitch (float | None | Unset): Map tilt in degrees (0-85)
        show_basemap_labels (bool | None | Unset):
        visibility (MapVisibility | None | Unset): private, internal, or public
        widgets (list[str] | None | Unset): Enabled widget IDs, e.g. ['measurement']
        zoom (float | None | Unset): Map zoom level
    """

    basemap_style: None | str | Unset = UNSET
    bearing: float | None | Unset = UNSET
    center_lat: float | None | Unset = UNSET
    center_lng: float | None | Unset = UNSET
    description: None | str | Unset = UNSET
    layers: list[MapLayerInput] | None | Unset = UNSET
    name: None | str | Unset = UNSET
    notes: None | str | Unset = UNSET
    pitch: float | None | Unset = UNSET
    show_basemap_labels: bool | None | Unset = UNSET
    visibility: MapVisibility | None | Unset = UNSET
    widgets: list[str] | None | Unset = UNSET
    zoom: float | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        basemap_style: None | str | Unset
        if isinstance(self.basemap_style, Unset):
            basemap_style = UNSET
        else:
            basemap_style = self.basemap_style

        bearing: float | None | Unset
        if isinstance(self.bearing, Unset):
            bearing = UNSET
        else:
            bearing = self.bearing

        center_lat: float | None | Unset
        if isinstance(self.center_lat, Unset):
            center_lat = UNSET
        else:
            center_lat = self.center_lat

        center_lng: float | None | Unset
        if isinstance(self.center_lng, Unset):
            center_lng = UNSET
        else:
            center_lng = self.center_lng

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

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

        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        notes: None | str | Unset
        if isinstance(self.notes, Unset):
            notes = UNSET
        else:
            notes = self.notes

        pitch: float | None | Unset
        if isinstance(self.pitch, Unset):
            pitch = UNSET
        else:
            pitch = self.pitch

        show_basemap_labels: bool | None | Unset
        if isinstance(self.show_basemap_labels, Unset):
            show_basemap_labels = UNSET
        else:
            show_basemap_labels = self.show_basemap_labels

        visibility: None | str | Unset
        if isinstance(self.visibility, Unset):
            visibility = UNSET
        elif isinstance(self.visibility, str):
            visibility = self.visibility
        else:
            visibility = self.visibility

        widgets: list[str] | None | Unset
        if isinstance(self.widgets, Unset):
            widgets = UNSET
        elif isinstance(self.widgets, list):
            widgets = self.widgets

        else:
            widgets = self.widgets

        zoom: float | None | Unset
        if isinstance(self.zoom, Unset):
            zoom = UNSET
        else:
            zoom = self.zoom

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if basemap_style is not UNSET:
            field_dict["basemap_style"] = basemap_style
        if bearing is not UNSET:
            field_dict["bearing"] = bearing
        if center_lat is not UNSET:
            field_dict["center_lat"] = center_lat
        if center_lng is not UNSET:
            field_dict["center_lng"] = center_lng
        if description is not UNSET:
            field_dict["description"] = description
        if layers is not UNSET:
            field_dict["layers"] = layers
        if name is not UNSET:
            field_dict["name"] = name
        if notes is not UNSET:
            field_dict["notes"] = notes
        if pitch is not UNSET:
            field_dict["pitch"] = pitch
        if show_basemap_labels is not UNSET:
            field_dict["show_basemap_labels"] = show_basemap_labels
        if visibility is not UNSET:
            field_dict["visibility"] = visibility
        if widgets is not UNSET:
            field_dict["widgets"] = widgets
        if zoom is not UNSET:
            field_dict["zoom"] = zoom

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.map_layer_input import MapLayerInput

        d = dict(src_dict)

        def _parse_basemap_style(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        basemap_style = _parse_basemap_style(d.pop("basemap_style", UNSET))

        def _parse_bearing(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        bearing = _parse_bearing(d.pop("bearing", UNSET))

        def _parse_center_lat(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        center_lat = _parse_center_lat(d.pop("center_lat", UNSET))

        def _parse_center_lng(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        center_lng = _parse_center_lng(d.pop("center_lng", UNSET))

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

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

        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))

        def _parse_notes(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        notes = _parse_notes(d.pop("notes", UNSET))

        def _parse_pitch(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        pitch = _parse_pitch(d.pop("pitch", UNSET))

        def _parse_show_basemap_labels(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        show_basemap_labels = _parse_show_basemap_labels(
            d.pop("show_basemap_labels", UNSET)
        )

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

        def _parse_widgets(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                widgets_type_0 = cast(list[str], data)

                return widgets_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        widgets = _parse_widgets(d.pop("widgets", UNSET))

        def _parse_zoom(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        zoom = _parse_zoom(d.pop("zoom", UNSET))

        map_update = cls(
            basemap_style=basemap_style,
            bearing=bearing,
            center_lat=center_lat,
            center_lng=center_lng,
            description=description,
            layers=layers,
            name=name,
            notes=notes,
            pitch=pitch,
            show_basemap_labels=show_basemap_labels,
            visibility=visibility,
            widgets=widgets,
            zoom=zoom,
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
