from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.stac_import_request_visibility import check_stac_import_request_visibility
from ..models.stac_import_request_visibility import StacImportRequestVisibility

if TYPE_CHECKING:
    from ..models.stac_import_item import StacImportItem


T = TypeVar("T", bound="StacImportRequest")


@_attrs_define
class StacImportRequest:
    """
    Attributes:
        items (list[StacImportItem]): Items to import (max 50 per request).
        url (str): STAC API URL for provenance.
        visibility (StacImportRequestVisibility | Unset): Visibility for imported datasets. Default: 'private'.
    """

    items: list[StacImportItem]
    url: str
    visibility: StacImportRequestVisibility | Unset = "private"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        items = []
        for items_item_data in self.items:
            items_item = items_item_data.to_dict()
            items.append(items_item)

        url = self.url

        visibility: str | Unset = UNSET
        if not isinstance(self.visibility, Unset):
            visibility = self.visibility

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "items": items,
                "url": url,
            }
        )
        if visibility is not UNSET:
            field_dict["visibility"] = visibility

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stac_import_item import StacImportItem

        d = dict(src_dict)
        items = []
        _items = d.pop("items")
        for items_item_data in _items:
            items_item = StacImportItem.from_dict(items_item_data)

            items.append(items_item)

        url = d.pop("url")

        _visibility = d.pop("visibility", UNSET)
        visibility: StacImportRequestVisibility | Unset
        if isinstance(_visibility, Unset):
            visibility = UNSET
        else:
            visibility = check_stac_import_request_visibility(_visibility)

        stac_import_request = cls(
            items=items,
            url=url,
            visibility=visibility,
        )

        stac_import_request.additional_properties = d
        return stac_import_request

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
