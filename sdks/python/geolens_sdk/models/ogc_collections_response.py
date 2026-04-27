from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


if TYPE_CHECKING:
    from ..models.ogc_collections_response_collections_item import (
        OGCCollectionsResponseCollectionsItem,
    )
    from ..models.ogc_record_link import OGCRecordLink


T = TypeVar("T", bound="OGCCollectionsResponse")


@_attrs_define
class OGCCollectionsResponse:
    """Response for /collections listing all available OGC collections.

    Attributes:
        collections (list[OGCCollectionsResponseCollectionsItem]):
        links (list[OGCRecordLink] | Unset):
    """

    collections: list[OGCCollectionsResponseCollectionsItem]
    links: list[OGCRecordLink] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        collections = []
        for collections_item_data in self.collections:
            collections_item = collections_item_data.to_dict()
            collections.append(collections_item)

        links: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.links, Unset):
            links = []
            for links_item_data in self.links:
                links_item = links_item_data.to_dict()
                links.append(links_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "collections": collections,
            }
        )
        if links is not UNSET:
            field_dict["links"] = links

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ogc_collections_response_collections_item import (
            OGCCollectionsResponseCollectionsItem,
        )
        from ..models.ogc_record_link import OGCRecordLink

        d = dict(src_dict)
        collections = []
        _collections = d.pop("collections")
        for collections_item_data in _collections:
            collections_item = OGCCollectionsResponseCollectionsItem.from_dict(
                collections_item_data
            )

            collections.append(collections_item)

        _links = d.pop("links", UNSET)
        links: list[OGCRecordLink] | Unset = UNSET
        if _links is not UNSET:
            links = []
            for links_item_data in _links:
                links_item = OGCRecordLink.from_dict(links_item_data)

                links.append(links_item)

        ogc_collections_response = cls(
            collections=collections,
            links=links,
        )

        ogc_collections_response.additional_properties = d
        return ogc_collections_response

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
