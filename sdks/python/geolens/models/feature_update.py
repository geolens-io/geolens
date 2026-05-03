from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.feature_update_properties_type_0 import FeatureUpdatePropertiesType0
    from ..models.geo_json_geometry import GeoJSONGeometry


T = TypeVar("T", bound="FeatureUpdate")


@_attrs_define
class FeatureUpdate:
    """Partial feature update (PATCH semantics).

    Attributes:
        geometry (GeoJSONGeometry | None | Unset):
        properties (FeatureUpdatePropertiesType0 | None | Unset):
    """

    geometry: GeoJSONGeometry | None | Unset = UNSET
    properties: FeatureUpdatePropertiesType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.feature_update_properties_type_0 import (
            FeatureUpdatePropertiesType0,
        )
        from ..models.geo_json_geometry import GeoJSONGeometry

        geometry: dict[str, Any] | None | Unset
        if isinstance(self.geometry, Unset):
            geometry = UNSET
        elif isinstance(self.geometry, GeoJSONGeometry):
            geometry = self.geometry.to_dict()
        else:
            geometry = self.geometry

        properties: dict[str, Any] | None | Unset
        if isinstance(self.properties, Unset):
            properties = UNSET
        elif isinstance(self.properties, FeatureUpdatePropertiesType0):
            properties = self.properties.to_dict()
        else:
            properties = self.properties

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if geometry is not UNSET:
            field_dict["geometry"] = geometry
        if properties is not UNSET:
            field_dict["properties"] = properties

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.feature_update_properties_type_0 import (
            FeatureUpdatePropertiesType0,
        )
        from ..models.geo_json_geometry import GeoJSONGeometry

        d = dict(src_dict)

        def _parse_geometry(data: object) -> GeoJSONGeometry | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_type_0 = GeoJSONGeometry.from_dict(data)

                return geometry_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(GeoJSONGeometry | None | Unset, data)

        geometry = _parse_geometry(d.pop("geometry", UNSET))

        def _parse_properties(
            data: object,
        ) -> FeatureUpdatePropertiesType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                properties_type_0 = FeatureUpdatePropertiesType0.from_dict(data)

                return properties_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(FeatureUpdatePropertiesType0 | None | Unset, data)

        properties = _parse_properties(d.pop("properties", UNSET))

        feature_update = cls(
            geometry=geometry,
            properties=properties,
        )

        feature_update.additional_properties = d
        return feature_update

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
