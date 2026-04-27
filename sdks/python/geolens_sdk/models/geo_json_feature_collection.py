from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


if TYPE_CHECKING:
    from ..models.geo_json_feature import GeoJSONFeature


T = TypeVar("T", bound="GeoJSONFeatureCollection")


@_attrs_define
class GeoJSONFeatureCollection:
    """A GeoJSON FeatureCollection.

    Attributes:
        features (list[GeoJSONFeature] | Unset):
        type_ (str | Unset):  Default: 'FeatureCollection'.
    """

    features: list[GeoJSONFeature] | Unset = UNSET
    type_: str | Unset = "FeatureCollection"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        features: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.features, Unset):
            features = []
            for features_item_data in self.features:
                features_item = features_item_data.to_dict()
                features.append(features_item)

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if features is not UNSET:
            field_dict["features"] = features
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.geo_json_feature import GeoJSONFeature

        d = dict(src_dict)
        _features = d.pop("features", UNSET)
        features: list[GeoJSONFeature] | Unset = UNSET
        if _features is not UNSET:
            features = []
            for features_item_data in _features:
                features_item = GeoJSONFeature.from_dict(features_item_data)

                features.append(features_item)

        type_ = d.pop("type", UNSET)

        geo_json_feature_collection = cls(
            features=features,
            type_=type_,
        )

        geo_json_feature_collection.additional_properties = d
        return geo_json_feature_collection

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
