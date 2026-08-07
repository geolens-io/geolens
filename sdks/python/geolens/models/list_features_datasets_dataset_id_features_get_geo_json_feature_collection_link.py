from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar(
    "T", bound="ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionLink"
)


@_attrs_define
class ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionLink:
    """
    Attributes:
        rel (str):
        href (str):
        type_ (str):
    """

    rel: str
    href: str
    type_: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        rel = self.rel

        href = self.href

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "rel": rel,
                "href": href,
                "type": type_,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        rel = d.pop("rel")

        href = d.pop("href")

        type_ = d.pop("type")

        list_features_datasets_dataset_id_features_get_geo_json_feature_collection_link = cls(
            rel=rel,
            href=href,
            type_=type_,
        )

        list_features_datasets_dataset_id_features_get_geo_json_feature_collection_link.additional_properties = d
        return list_features_datasets_dataset_id_features_get_geo_json_feature_collection_link

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
