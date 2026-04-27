from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.keyword_suggestion import KeywordSuggestion


T = TypeVar("T", bound="KeywordSuggestionsResponse")


@_attrs_define
class KeywordSuggestionsResponse:
    """AI-suggested keywords for a dataset.

    Attributes:
        keywords (list[KeywordSuggestion]): List of suggested keywords with classification (5-10 items)
    """

    keywords: list[KeywordSuggestion]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        keywords = []
        for keywords_item_data in self.keywords:
            keywords_item = keywords_item_data.to_dict()
            keywords.append(keywords_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "keywords": keywords,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.keyword_suggestion import KeywordSuggestion

        d = dict(src_dict)
        keywords = []
        _keywords = d.pop("keywords")
        for keywords_item_data in _keywords:
            keywords_item = KeywordSuggestion.from_dict(keywords_item_data)

            keywords.append(keywords_item)

        keyword_suggestions_response = cls(
            keywords=keywords,
        )

        keyword_suggestions_response.additional_properties = d
        return keyword_suggestions_response

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
