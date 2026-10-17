from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.create_feature_datasets_dataset_id_features_post_geo_json_feature_collection_dry_run_geo_json_feature_dry_run import (
        CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionDryRunGeoJSONFeatureDryRun,
    )


T = TypeVar(
    "T",
    bound="CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionDryRun",
)


@_attrs_define
class CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionDryRun:
    """The features a FeatureCollection create would store, in request order.

    Attributes:
        features (list[CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionDryRunGeoJSONFeatureDryRun]):
        type_ (Literal['FeatureCollection'] | Unset):  Default: 'FeatureCollection'.
    """

    features: list[
        CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionDryRunGeoJSONFeatureDryRun
    ]
    type_: Literal["FeatureCollection"] | Unset = "FeatureCollection"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        features = []
        for features_item_data in self.features:
            features_item = features_item_data.to_dict()
            features.append(features_item)

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "features": features,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.create_feature_datasets_dataset_id_features_post_geo_json_feature_collection_dry_run_geo_json_feature_dry_run import (
            CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionDryRunGeoJSONFeatureDryRun,
        )

        d = dict(src_dict)
        features = []
        _features = d.pop("features")
        for features_item_data in _features:
            features_item = CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionDryRunGeoJSONFeatureDryRun.from_dict(
                features_item_data
            )

            features.append(features_item)

        type_ = cast(Literal["FeatureCollection"] | Unset, d.pop("type", UNSET))
        if type_ != "FeatureCollection" and not isinstance(type_, Unset):
            raise ValueError(
                f"type must match const 'FeatureCollection', got '{type_}'"
            )

        create_feature_datasets_dataset_id_features_post_geo_json_feature_collection_dry_run = cls(
            features=features,
            type_=type_,
        )

        create_feature_datasets_dataset_id_features_post_geo_json_feature_collection_dry_run.additional_properties = d
        return create_feature_datasets_dataset_id_features_post_geo_json_feature_collection_dry_run

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
