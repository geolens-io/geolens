from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_type import (
    check_get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_type,
)
from ..models.get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_type import (
    GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200Type,
)

if TYPE_CHECKING:
    from ..models.get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item import (
        GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItem,
    )


T = TypeVar(
    "T",
    bound="GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200",
)


@_attrs_define
class GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200:
    """
    Attributes:
        type_ (GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200Type):
        features (list[GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItem]):
        truncated (bool):
        total_count (int):
    """

    type_: GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200Type
    features: list[
        GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItem
    ]
    truncated: bool
    total_count: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_: str = self.type_

        features = []
        for features_item_data in self.features:
            features_item = features_item_data.to_dict()
            features.append(features_item)

        truncated = self.truncated

        total_count = self.total_count

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "features": features,
                "truncated": truncated,
                "total_count": total_count,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item import (
            GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItem,
        )

        d = dict(src_dict)
        type_ = check_get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_type(
            d.pop("type")
        )

        features = []
        _features = d.pop("features")
        for features_item_data in _features:
            features_item = GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItem.from_dict(
                features_item_data
            )

            features.append(features_item)

        truncated = d.pop("truncated")

        total_count = d.pop("total_count")

        get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200 = cls(
            type_=type_,
            features=features,
            truncated=truncated,
            total_count=total_count,
        )

        get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200.additional_properties = d
        return get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200

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
