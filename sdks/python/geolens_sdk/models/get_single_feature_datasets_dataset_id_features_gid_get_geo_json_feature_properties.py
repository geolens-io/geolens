from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar(
    "T", bound="GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureProperties"
)


@_attrs_define
class GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureProperties:
    """ """

    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature_properties = cls()

        get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature_properties.additional_properties = d
        return get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature_properties

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
