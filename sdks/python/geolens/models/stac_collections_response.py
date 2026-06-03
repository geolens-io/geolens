from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.stac_collection_summary import StacCollectionSummary


T = TypeVar("T", bound="StacCollectionsResponse")


@_attrs_define
class StacCollectionsResponse:
    """
    Attributes:
        collections (list[StacCollectionSummary]): Available collections.
        url (str): STAC API URL that was queried.
    """

    collections: list[StacCollectionSummary]
    url: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        collections = []
        for collections_item_data in self.collections:
            collections_item = collections_item_data.to_dict()
            collections.append(collections_item)

        url = self.url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "collections": collections,
                "url": url,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stac_collection_summary import StacCollectionSummary

        d = dict(src_dict)
        collections = []
        _collections = d.pop("collections")
        for collections_item_data in _collections:
            collections_item = StacCollectionSummary.from_dict(collections_item_data)

            collections.append(collections_item)

        url = d.pop("url")

        stac_collections_response = cls(
            collections=collections,
            url=url,
        )

        stac_collections_response.additional_properties = d
        return stac_collections_response

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
