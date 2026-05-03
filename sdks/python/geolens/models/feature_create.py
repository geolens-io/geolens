from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.feature_create_properties_type_0 import FeatureCreatePropertiesType0
    from ..models.geo_json_geometry import GeoJSONGeometry


T = TypeVar("T", bound="FeatureCreate")


@_attrs_define
class FeatureCreate:
    """GeoJSON-style feature for insertion.

    Attributes:
        geometry (GeoJSONGeometry): A GeoJSON geometry object (RFC 7946).
        properties (FeatureCreatePropertiesType0 | None | Unset):
    """

    geometry: GeoJSONGeometry
    properties: FeatureCreatePropertiesType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.feature_create_properties_type_0 import (
            FeatureCreatePropertiesType0,
        )

        geometry = self.geometry.to_dict()

        properties: dict[str, Any] | None | Unset
        if isinstance(self.properties, Unset):
            properties = UNSET
        elif isinstance(self.properties, FeatureCreatePropertiesType0):
            properties = self.properties.to_dict()
        else:
            properties = self.properties

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "geometry": geometry,
            }
        )
        if properties is not UNSET:
            field_dict["properties"] = properties

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.feature_create_properties_type_0 import (
            FeatureCreatePropertiesType0,
        )
        from ..models.geo_json_geometry import GeoJSONGeometry

        d = dict(src_dict)
        geometry = GeoJSONGeometry.from_dict(d.pop("geometry"))

        def _parse_properties(
            data: object,
        ) -> FeatureCreatePropertiesType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                properties_type_0 = FeatureCreatePropertiesType0.from_dict(data)

                return properties_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(FeatureCreatePropertiesType0 | None | Unset, data)

        properties = _parse_properties(d.pop("properties", UNSET))

        feature_create = cls(
            geometry=geometry,
            properties=properties,
        )

        feature_create.additional_properties = d
        return feature_create

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
