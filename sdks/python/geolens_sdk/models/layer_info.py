from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="LayerInfo")


@_attrs_define
class LayerInfo:
    """
    Attributes:
        name (str): Internal layer identifier used by the source service.
        feature_count (int | None | Unset): Total feature count if reported by the service.
        geometry_type (None | str | Unset): Detected geometry type for the layer.
        layer_id (int | None | str | Unset): Numeric or string layer ID used by ArcGIS services.
        layer_type (str | Unset): Layer kind: 'layer' (spatial) or 'table' (non-spatial attribute table). Default:
            'layer'.
        object_id_field (None | str | Unset): ArcGIS object ID field name, used for stable pagination.
        title (None | str | Unset): Human-readable layer title from the service capabilities.
    """

    name: str
    feature_count: int | None | Unset = UNSET
    geometry_type: None | str | Unset = UNSET
    layer_id: int | None | str | Unset = UNSET
    layer_type: str | Unset = "layer"
    object_id_field: None | str | Unset = UNSET
    title: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        feature_count: int | None | Unset
        if isinstance(self.feature_count, Unset):
            feature_count = UNSET
        else:
            feature_count = self.feature_count

        geometry_type: None | str | Unset
        if isinstance(self.geometry_type, Unset):
            geometry_type = UNSET
        else:
            geometry_type = self.geometry_type

        layer_id: int | None | str | Unset
        if isinstance(self.layer_id, Unset):
            layer_id = UNSET
        else:
            layer_id = self.layer_id

        layer_type = self.layer_type

        object_id_field: None | str | Unset
        if isinstance(self.object_id_field, Unset):
            object_id_field = UNSET
        else:
            object_id_field = self.object_id_field

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
            }
        )
        if feature_count is not UNSET:
            field_dict["feature_count"] = feature_count
        if geometry_type is not UNSET:
            field_dict["geometry_type"] = geometry_type
        if layer_id is not UNSET:
            field_dict["layer_id"] = layer_id
        if layer_type is not UNSET:
            field_dict["layer_type"] = layer_type
        if object_id_field is not UNSET:
            field_dict["object_id_field"] = object_id_field
        if title is not UNSET:
            field_dict["title"] = title

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name")

        def _parse_feature_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        feature_count = _parse_feature_count(d.pop("feature_count", UNSET))

        def _parse_geometry_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        geometry_type = _parse_geometry_type(d.pop("geometry_type", UNSET))

        def _parse_layer_id(data: object) -> int | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | str | Unset, data)

        layer_id = _parse_layer_id(d.pop("layer_id", UNSET))

        layer_type = d.pop("layer_type", UNSET)

        def _parse_object_id_field(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        object_id_field = _parse_object_id_field(d.pop("object_id_field", UNSET))

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        layer_info = cls(
            name=name,
            feature_count=feature_count,
            geometry_type=geometry_type,
            layer_id=layer_id,
            layer_type=layer_type,
            object_id_field=object_id_field,
            title=title,
        )

        layer_info.additional_properties = d
        return layer_info

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
