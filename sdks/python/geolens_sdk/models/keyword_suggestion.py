from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="KeywordSuggestion")


@_attrs_define
class KeywordSuggestion:
    """A single keyword suggestion with classification.

    Attributes:
        keyword (str): Lowercase keyword
        keyword_type (str): Classification: theme, place, or temporal
    """

    keyword: str
    keyword_type: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        keyword = self.keyword

        keyword_type = self.keyword_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "keyword": keyword,
                "keyword_type": keyword_type,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        keyword = d.pop("keyword")

        keyword_type = d.pop("keyword_type")

        keyword_suggestion = cls(
            keyword=keyword,
            keyword_type=keyword_type,
        )

        keyword_suggestion.additional_properties = d
        return keyword_suggestion

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
