from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.create_feature_datasets_dataset_id_features_post_geo_json_feature_collection_write_geo_json_feature import (
        CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionWriteGeoJSONFeature,
    )


T = TypeVar(
    "T", bound="CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionWrite"
)


@_attrs_define
class CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionWrite:
    """The features a FeatureCollection create inserted, in request order.

    Attributes:
        features (list[CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionWriteGeoJSONFeature]):
        type_ (Literal['FeatureCollection'] | Unset):  Default: 'FeatureCollection'.
        table_id (None | str | Unset): Opaque id of the data table this feature was read from or written to. A reupload
            or an overwrite of the dataset's data replaces the table, and the replacement can reuse feature ids. Send it
            back as the `table_id` query parameter of a PUT, PATCH or DELETE of this feature, or of a batch delete, to have
            the write refused if the table was replaced since.
        tile_cache_version (int | None | Unset): The dataset's tile_cache_version after this write committed. Send it as
            the tile routes' `_v` query parameter when reloading tiles, so a request that reaches a different API worker is
            forced to re-read the dataset instead of serving that worker's own cached snapshot.
    """

    features: list[
        CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionWriteGeoJSONFeature
    ]
    type_: Literal["FeatureCollection"] | Unset = "FeatureCollection"
    table_id: None | str | Unset = UNSET
    tile_cache_version: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        features = []
        for features_item_data in self.features:
            features_item = features_item_data.to_dict()
            features.append(features_item)

        type_ = self.type_

        table_id: None | str | Unset
        if isinstance(self.table_id, Unset):
            table_id = UNSET
        else:
            table_id = self.table_id

        tile_cache_version: int | None | Unset
        if isinstance(self.tile_cache_version, Unset):
            tile_cache_version = UNSET
        else:
            tile_cache_version = self.tile_cache_version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "features": features,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_
        if table_id is not UNSET:
            field_dict["table_id"] = table_id
        if tile_cache_version is not UNSET:
            field_dict["tile_cache_version"] = tile_cache_version

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.create_feature_datasets_dataset_id_features_post_geo_json_feature_collection_write_geo_json_feature import (
            CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionWriteGeoJSONFeature,
        )

        d = dict(src_dict)
        features = []
        _features = d.pop("features")
        for features_item_data in _features:
            features_item = CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureCollectionWriteGeoJSONFeature.from_dict(
                features_item_data
            )

            features.append(features_item)

        type_ = cast(Literal["FeatureCollection"] | Unset, d.pop("type", UNSET))
        if type_ != "FeatureCollection" and not isinstance(type_, Unset):
            raise ValueError(
                f"type must match const 'FeatureCollection', got '{type_}'"
            )

        def _parse_table_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        table_id = _parse_table_id(d.pop("table_id", UNSET))

        def _parse_tile_cache_version(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        tile_cache_version = _parse_tile_cache_version(
            d.pop("tile_cache_version", UNSET)
        )

        create_feature_datasets_dataset_id_features_post_geo_json_feature_collection_write = cls(
            features=features,
            type_=type_,
            table_id=table_id,
            tile_cache_version=tile_cache_version,
        )

        create_feature_datasets_dataset_id_features_post_geo_json_feature_collection_write.additional_properties = d
        return create_feature_datasets_dataset_id_features_post_geo_json_feature_collection_write

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
