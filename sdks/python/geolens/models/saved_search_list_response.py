from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.saved_search_response import SavedSearchResponse


T = TypeVar("T", bound="SavedSearchListResponse")


@_attrs_define
class SavedSearchListResponse:
    """Response wrapping a list of saved searches.

    Attributes:
        searches (list[SavedSearchResponse]):
        total (int):
    """

    searches: list[SavedSearchResponse]
    total: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        searches = []
        for searches_item_data in self.searches:
            searches_item = searches_item_data.to_dict()
            searches.append(searches_item)

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "searches": searches,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.saved_search_response import SavedSearchResponse

        d = dict(src_dict)
        searches = []
        _searches = d.pop("searches")
        for searches_item_data in _searches:
            searches_item = SavedSearchResponse.from_dict(searches_item_data)

            searches.append(searches_item)

        total = d.pop("total")

        saved_search_list_response = cls(
            searches=searches,
            total=total,
        )

        saved_search_list_response.additional_properties = d
        return saved_search_list_response

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
