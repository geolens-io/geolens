from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.get_collection_items_collections_dataset_id_items_get_ogc_feature_items_response_features_item import (
        GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponseFeaturesItem,
    )
    from ..models.get_collection_items_collections_dataset_id_items_get_ogc_feature_items_response_ogc_link import (
        GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponseOGCLink,
    )


T = TypeVar(
    "T", bound="GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse"
)


@_attrs_define
class GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponse:
    """FeatureCollection response as defined by OGC API - Features.

    Attributes:
        number_matched (int): Total number of features matching the query (across all pages).
        number_returned (int): Number of features in this response page.
        features (list[GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponseFeaturesItem]): GeoJSON
            features returned by the query.
        links (list[GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponseOGCLink]): Pagination and self-
            reference links.
        type_ (Literal['FeatureCollection'] | Unset): GeoJSON object type. Default: 'FeatureCollection'.
        time_stamp (str | Unset): ISO 8601 timestamp the response was generated.
    """

    number_matched: int
    number_returned: int
    features: list[
        GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponseFeaturesItem
    ]
    links: list[
        GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponseOGCLink
    ]
    type_: Literal["FeatureCollection"] | Unset = "FeatureCollection"
    time_stamp: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        number_matched = self.number_matched

        number_returned = self.number_returned

        features = []
        for features_item_data in self.features:
            features_item = features_item_data.to_dict()
            features.append(features_item)

        links = []
        for links_item_data in self.links:
            links_item = links_item_data.to_dict()
            links.append(links_item)

        type_ = self.type_

        time_stamp = self.time_stamp

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "numberMatched": number_matched,
                "numberReturned": number_returned,
                "features": features,
                "links": links,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_
        if time_stamp is not UNSET:
            field_dict["timeStamp"] = time_stamp

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_collection_items_collections_dataset_id_items_get_ogc_feature_items_response_features_item import (
            GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponseFeaturesItem,
        )
        from ..models.get_collection_items_collections_dataset_id_items_get_ogc_feature_items_response_ogc_link import (
            GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponseOGCLink,
        )

        d = dict(src_dict)
        number_matched = d.pop("numberMatched")

        number_returned = d.pop("numberReturned")

        features = []
        _features = d.pop("features")
        for features_item_data in _features:
            features_item = GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponseFeaturesItem.from_dict(
                features_item_data
            )

            features.append(features_item)

        links = []
        _links = d.pop("links")
        for links_item_data in _links:
            links_item = GetCollectionItemsCollectionsDatasetIdItemsGetOGCFeatureItemsResponseOGCLink.from_dict(
                links_item_data
            )

            links.append(links_item)

        type_ = cast(Literal["FeatureCollection"] | Unset, d.pop("type", UNSET))
        if type_ != "FeatureCollection" and not isinstance(type_, Unset):
            raise ValueError(
                f"type must match const 'FeatureCollection', got '{type_}'"
            )

        time_stamp = d.pop("timeStamp", UNSET)

        get_collection_items_collections_dataset_id_items_get_ogc_feature_items_response = cls(
            number_matched=number_matched,
            number_returned=number_returned,
            features=features,
            links=links,
            type_=type_,
            time_stamp=time_stamp,
        )

        get_collection_items_collections_dataset_id_items_get_ogc_feature_items_response.additional_properties = d
        return get_collection_items_collections_dataset_id_items_get_ogc_feature_items_response

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
