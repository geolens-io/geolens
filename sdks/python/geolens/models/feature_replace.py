from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.feature_replace_properties import FeatureReplaceProperties
    from ..models.geo_json_geometry import GeoJSONGeometry
    from ..models.geo_json_geometry_collection import GeoJSONGeometryCollection


T = TypeVar("T", bound="FeatureReplace")


@_attrs_define
class FeatureReplace:
    """Full feature replacement (PUT semantics).

    Attributes:
        geometry (GeoJSONGeometry | GeoJSONGeometryCollection):
        properties (FeatureReplaceProperties):
    """

    geometry: GeoJSONGeometry | GeoJSONGeometryCollection
    properties: FeatureReplaceProperties
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.geo_json_geometry_collection import GeoJSONGeometryCollection

        geometry: dict[str, Any]
        if isinstance(self.geometry, GeoJSONGeometryCollection):
            geometry = self.geometry.to_dict()
        else:
            geometry = self.geometry.to_dict()

        properties = self.properties.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "geometry": geometry,
                "properties": properties,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.feature_replace_properties import FeatureReplaceProperties
        from ..models.geo_json_geometry import GeoJSONGeometry
        from ..models.geo_json_geometry_collection import GeoJSONGeometryCollection

        d = dict(src_dict)

        def _parse_geometry(
            data: object,
        ) -> GeoJSONGeometry | GeoJSONGeometryCollection:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_type_0 = GeoJSONGeometryCollection.from_dict(data)

                return geometry_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            if not isinstance(data, dict):
                raise TypeError()
            geometry_type_1 = GeoJSONGeometry.from_dict(data)

            return geometry_type_1

        geometry = _parse_geometry(d.pop("geometry"))

        properties = FeatureReplaceProperties.from_dict(d.pop("properties"))

        feature_replace = cls(
            geometry=geometry,
            properties=properties,
        )

        feature_replace.additional_properties = d
        return feature_replace

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
