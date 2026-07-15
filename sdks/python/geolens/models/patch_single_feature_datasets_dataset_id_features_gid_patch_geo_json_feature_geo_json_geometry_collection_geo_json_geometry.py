from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_geo_json_geometry_collection_geo_json_geometry_type import (
    check_patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_geo_json_geometry_collection_geo_json_geometry_type,
)
from ..models.patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_geo_json_geometry_collection_geo_json_geometry_type import (
    PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType,
)
from typing import cast


T = TypeVar(
    "T",
    bound="PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometry",
)


@_attrs_define
class PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometry:
    """A GeoJSON geometry object (RFC 7946).

    Attributes:
        coordinates (list[Any]):
        type_
            (PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType):
    """

    coordinates: list[Any]
    type_: PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometryType
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        coordinates = self.coordinates

        type_: str = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "coordinates": coordinates,
                "type": type_,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        coordinates = cast(list[Any], d.pop("coordinates"))

        type_ = check_patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_geo_json_geometry_collection_geo_json_geometry_type(
            d.pop("type")
        )

        patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_geo_json_geometry_collection_geo_json_geometry = cls(
            coordinates=coordinates,
            type_=type_,
        )

        patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_geo_json_geometry_collection_geo_json_geometry.additional_properties = d
        return patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_geo_json_geometry_collection_geo_json_geometry

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
