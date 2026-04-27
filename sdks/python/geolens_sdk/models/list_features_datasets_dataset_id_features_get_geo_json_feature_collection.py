from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.inline_def_geo_json_feature_afaebacb import (
        InlineDefGeoJSONFeatureAfaebacb,
    )
    from ..models.inline_def_link_900f1c94 import InlineDefLink900F1C94


T = TypeVar(
    "T", bound="ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection"
)


@_attrs_define
class ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollection:
    """A GeoJSON FeatureCollection with OGC API Features pagination fields.

    Attributes:
        features (list[InlineDefGeoJSONFeatureAfaebacb]):
        links (list[InlineDefLink900F1C94]):
        number_matched (int):
        number_returned (int):
        type_ (Literal['FeatureCollection'] | Unset):  Default: 'FeatureCollection'.
    """

    features: list[InlineDefGeoJSONFeatureAfaebacb]
    links: list[InlineDefLink900F1C94]
    number_matched: int
    number_returned: int
    type_: Literal["FeatureCollection"] | Unset = "FeatureCollection"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        features = []
        for features_item_data in self.features:
            features_item = features_item_data.to_dict()
            features.append(features_item)

        links = []
        for links_item_data in self.links:
            links_item = links_item_data.to_dict()
            links.append(links_item)

        number_matched = self.number_matched

        number_returned = self.number_returned

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "features": features,
                "links": links,
                "numberMatched": number_matched,
                "numberReturned": number_returned,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.inline_def_geo_json_feature_afaebacb import (
            InlineDefGeoJSONFeatureAfaebacb,
        )
        from ..models.inline_def_link_900f1c94 import InlineDefLink900F1C94

        d = dict(src_dict)
        features = []
        _features = d.pop("features")
        for features_item_data in _features:
            features_item = InlineDefGeoJSONFeatureAfaebacb.from_dict(
                features_item_data
            )

            features.append(features_item)

        links = []
        _links = d.pop("links")
        for links_item_data in _links:
            links_item = InlineDefLink900F1C94.from_dict(links_item_data)

            links.append(links_item)

        number_matched = d.pop("numberMatched")

        number_returned = d.pop("numberReturned")

        type_ = cast(Literal["FeatureCollection"] | Unset, d.pop("type", UNSET))
        if type_ != "FeatureCollection" and not isinstance(type_, Unset):
            raise ValueError(
                f"type must match const 'FeatureCollection', got '{type_}'"
            )

        list_features_datasets_dataset_id_features_get_geo_json_feature_collection = (
            cls(
                features=features,
                links=links,
                number_matched=number_matched,
                number_returned=number_returned,
                type_=type_,
            )
        )

        list_features_datasets_dataset_id_features_get_geo_json_feature_collection.additional_properties = d
        return (
            list_features_datasets_dataset_id_features_get_geo_json_feature_collection
        )

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
