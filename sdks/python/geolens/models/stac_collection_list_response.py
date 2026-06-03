from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.stac_collection_list_response_collections_item import (
        StacCollectionListResponseCollectionsItem,
    )
    from ..models.stac_link import StacLink


T = TypeVar("T", bound="StacCollectionListResponse")


@_attrs_define
class StacCollectionListResponse:
    """STAC collections list response.

    Attributes:
        collections (list[StacCollectionListResponseCollectionsItem]): List of STAC collections.
        links (list[StacLink]): Top-level collection navigation links.
    """

    collections: list[StacCollectionListResponseCollectionsItem]
    links: list[StacLink]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        collections = []
        for collections_item_data in self.collections:
            collections_item = collections_item_data.to_dict()
            collections.append(collections_item)

        links = []
        for links_item_data in self.links:
            links_item = links_item_data.to_dict()
            links.append(links_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "collections": collections,
                "links": links,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stac_collection_list_response_collections_item import (
            StacCollectionListResponseCollectionsItem,
        )
        from ..models.stac_link import StacLink

        d = dict(src_dict)
        collections = []
        _collections = d.pop("collections")
        for collections_item_data in _collections:
            collections_item = StacCollectionListResponseCollectionsItem.from_dict(
                collections_item_data
            )

            collections.append(collections_item)

        links = []
        _links = d.pop("links")
        for links_item_data in _links:
            links_item = StacLink.from_dict(links_item_data)

            links.append(links_item)

        stac_collection_list_response = cls(
            collections=collections,
            links=links,
        )

        stac_collection_list_response.additional_properties = d
        return stac_collection_list_response

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
