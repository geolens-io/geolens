from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.create_feature_datasets_dataset_id_features_post_geo_json_feature_geo_json_geometry_type import (
    check_create_feature_datasets_dataset_id_features_post_geo_json_feature_geo_json_geometry_type,
)
from ..models.create_feature_datasets_dataset_id_features_post_geo_json_feature_geo_json_geometry_type import (
    CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureGeoJSONGeometryType,
)
from typing import cast


T = TypeVar(
    "T", bound="CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureGeoJSONGeometry"
)


@_attrs_define
class CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureGeoJSONGeometry:
    """A GeoJSON geometry object (RFC 7946).

    Attributes:
        type_ (CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureGeoJSONGeometryType):
        coordinates (list[Any]):
    """

    type_: CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureGeoJSONGeometryType
    coordinates: list[Any]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_: str = self.type_

        coordinates = self.coordinates

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "coordinates": coordinates,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        type_ = check_create_feature_datasets_dataset_id_features_post_geo_json_feature_geo_json_geometry_type(
            d.pop("type")
        )

        coordinates = cast(list[Any], d.pop("coordinates"))

        create_feature_datasets_dataset_id_features_post_geo_json_feature_geo_json_geometry = cls(
            type_=type_,
            coordinates=coordinates,
        )

        create_feature_datasets_dataset_id_features_post_geo_json_feature_geo_json_geometry.additional_properties = d
        return create_feature_datasets_dataset_id_features_post_geo_json_feature_geo_json_geometry

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
