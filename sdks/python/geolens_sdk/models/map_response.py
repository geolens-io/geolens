from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.map_visibility import check_map_visibility
from ..models.map_visibility import MapVisibility
from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
    from ..models.map_layer_response import MapLayerResponse


T = TypeVar("T", bound="MapResponse")


@_attrs_define
class MapResponse:
    """
    Attributes:
        basemap_style (str):
        bearing (float):
        center_lat (float | None):
        center_lng (float | None):
        created_at (datetime.datetime):
        created_by (None | UUID):
        description (None | str):
        id (UUID):
        layer_count (int):
        layers (list[MapLayerResponse]):
        name (str):
        pitch (float):
        show_basemap_labels (bool):
        updated_at (datetime.datetime):
        visibility (MapVisibility):
        zoom (float | None):
        created_by_username (None | str | Unset):
        forked_from_id (None | Unset | UUID): Source map UUID if this is a fork
        forked_from_name (None | str | Unset):
        notes (None | str | Unset):
        thumbnail_url (None | str | Unset):
        widgets (list[str] | None | Unset):
    """

    basemap_style: str
    bearing: float
    center_lat: float | None
    center_lng: float | None
    created_at: datetime.datetime
    created_by: None | UUID
    description: None | str
    id: UUID
    layer_count: int
    layers: list[MapLayerResponse]
    name: str
    pitch: float
    show_basemap_labels: bool
    updated_at: datetime.datetime
    visibility: MapVisibility
    zoom: float | None
    created_by_username: None | str | Unset = UNSET
    forked_from_id: None | Unset | UUID = UNSET
    forked_from_name: None | str | Unset = UNSET
    notes: None | str | Unset = UNSET
    thumbnail_url: None | str | Unset = UNSET
    widgets: list[str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        basemap_style = self.basemap_style

        bearing = self.bearing

        center_lat: float | None
        center_lat = self.center_lat

        center_lng: float | None
        center_lng = self.center_lng

        created_at = self.created_at.isoformat()

        created_by: None | str
        if isinstance(self.created_by, UUID):
            created_by = str(self.created_by)
        else:
            created_by = self.created_by

        description: None | str
        description = self.description

        id = str(self.id)

        layer_count = self.layer_count

        layers = []
        for layers_item_data in self.layers:
            layers_item = layers_item_data.to_dict()
            layers.append(layers_item)

        name = self.name

        pitch = self.pitch

        show_basemap_labels = self.show_basemap_labels

        updated_at = self.updated_at.isoformat()

        visibility: str = self.visibility

        zoom: float | None
        zoom = self.zoom

        created_by_username: None | str | Unset
        if isinstance(self.created_by_username, Unset):
            created_by_username = UNSET
        else:
            created_by_username = self.created_by_username

        forked_from_id: None | str | Unset
        if isinstance(self.forked_from_id, Unset):
            forked_from_id = UNSET
        elif isinstance(self.forked_from_id, UUID):
            forked_from_id = str(self.forked_from_id)
        else:
            forked_from_id = self.forked_from_id

        forked_from_name: None | str | Unset
        if isinstance(self.forked_from_name, Unset):
            forked_from_name = UNSET
        else:
            forked_from_name = self.forked_from_name

        notes: None | str | Unset
        if isinstance(self.notes, Unset):
            notes = UNSET
        else:
            notes = self.notes

        thumbnail_url: None | str | Unset
        if isinstance(self.thumbnail_url, Unset):
            thumbnail_url = UNSET
        else:
            thumbnail_url = self.thumbnail_url

        widgets: list[str] | None | Unset
        if isinstance(self.widgets, Unset):
            widgets = UNSET
        elif isinstance(self.widgets, list):
            widgets = self.widgets

        else:
            widgets = self.widgets

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "basemap_style": basemap_style,
                "bearing": bearing,
                "center_lat": center_lat,
                "center_lng": center_lng,
                "created_at": created_at,
                "created_by": created_by,
                "description": description,
                "id": id,
                "layer_count": layer_count,
                "layers": layers,
                "name": name,
                "pitch": pitch,
                "show_basemap_labels": show_basemap_labels,
                "updated_at": updated_at,
                "visibility": visibility,
                "zoom": zoom,
            }
        )
        if created_by_username is not UNSET:
            field_dict["created_by_username"] = created_by_username
        if forked_from_id is not UNSET:
            field_dict["forked_from_id"] = forked_from_id
        if forked_from_name is not UNSET:
            field_dict["forked_from_name"] = forked_from_name
        if notes is not UNSET:
            field_dict["notes"] = notes
        if thumbnail_url is not UNSET:
            field_dict["thumbnail_url"] = thumbnail_url
        if widgets is not UNSET:
            field_dict["widgets"] = widgets

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.map_layer_response import MapLayerResponse

        d = dict(src_dict)
        basemap_style = d.pop("basemap_style")

        bearing = d.pop("bearing")

        def _parse_center_lat(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        center_lat = _parse_center_lat(d.pop("center_lat"))

        def _parse_center_lng(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        center_lng = _parse_center_lng(d.pop("center_lng"))

        created_at = isoparse(d.pop("created_at"))

        def _parse_created_by(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                created_by_type_0 = UUID(data)

                return created_by_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        created_by = _parse_created_by(d.pop("created_by"))

        def _parse_description(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        description = _parse_description(d.pop("description"))

        id = UUID(d.pop("id"))

        layer_count = d.pop("layer_count")

        layers = []
        _layers = d.pop("layers")
        for layers_item_data in _layers:
            layers_item = MapLayerResponse.from_dict(layers_item_data)

            layers.append(layers_item)

        name = d.pop("name")

        pitch = d.pop("pitch")

        show_basemap_labels = d.pop("show_basemap_labels")

        updated_at = isoparse(d.pop("updated_at"))

        visibility = check_map_visibility(d.pop("visibility"))

        def _parse_zoom(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        zoom = _parse_zoom(d.pop("zoom"))

        def _parse_created_by_username(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        created_by_username = _parse_created_by_username(
            d.pop("created_by_username", UNSET)
        )

        def _parse_forked_from_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                forked_from_id_type_0 = UUID(data)

                return forked_from_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        forked_from_id = _parse_forked_from_id(d.pop("forked_from_id", UNSET))

        def _parse_forked_from_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        forked_from_name = _parse_forked_from_name(d.pop("forked_from_name", UNSET))

        def _parse_notes(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        notes = _parse_notes(d.pop("notes", UNSET))

        def _parse_thumbnail_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        thumbnail_url = _parse_thumbnail_url(d.pop("thumbnail_url", UNSET))

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

        map_response = cls(
            basemap_style=basemap_style,
            bearing=bearing,
            center_lat=center_lat,
            center_lng=center_lng,
            created_at=created_at,
            created_by=created_by,
            description=description,
            id=id,
            layer_count=layer_count,
            layers=layers,
            name=name,
            pitch=pitch,
            show_basemap_labels=show_basemap_labels,
            updated_at=updated_at,
            visibility=visibility,
            zoom=zoom,
            created_by_username=created_by_username,
            forked_from_id=forked_from_id,
            forked_from_name=forked_from_name,
            notes=notes,
            thumbnail_url=thumbnail_url,
            widgets=widgets,
        )

        map_response.additional_properties = d
        return map_response

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
