from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.stac_item_summary import StacItemSummary


T = TypeVar("T", bound="StacSearchResponse")


@_attrs_define
class StacSearchResponse:
    """
    Attributes:
        items (list[StacItemSummary]): Matching items.
        returned (int): Number of items in this response.
        matched (int | None | Unset): Total matches (if reported by API).
    """

    items: list[StacItemSummary]
    returned: int
    matched: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        items = []
        for items_item_data in self.items:
            items_item = items_item_data.to_dict()
            items.append(items_item)

        returned = self.returned

        matched: int | None | Unset
        if isinstance(self.matched, Unset):
            matched = UNSET
        else:
            matched = self.matched

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "items": items,
                "returned": returned,
            }
        )
        if matched is not UNSET:
            field_dict["matched"] = matched

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stac_item_summary import StacItemSummary

        d = dict(src_dict)
        items = []
        _items = d.pop("items")
        for items_item_data in _items:
            items_item = StacItemSummary.from_dict(items_item_data)

            items.append(items_item)

        returned = d.pop("returned")

        def _parse_matched(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        matched = _parse_matched(d.pop("matched", UNSET))

        stac_search_response = cls(
            items=items,
            returned=returned,
            matched=matched,
        )

        stac_search_response.additional_properties = d
        return stac_search_response

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
