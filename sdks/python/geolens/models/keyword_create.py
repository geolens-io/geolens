from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="KeywordCreate")


@_attrs_define
class KeywordCreate:
    """
    Attributes:
        keyword (str):
        keyword_type (str | Unset): ISO MD_KeywordTypeCode, e.g. theme, place, discipline Default: 'theme'.
        vocabulary_uri (None | str | Unset): URI of the controlled vocabulary
    """

    keyword: str
    keyword_type: str | Unset = "theme"
    vocabulary_uri: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        keyword = self.keyword

        keyword_type = self.keyword_type

        vocabulary_uri: None | str | Unset
        if isinstance(self.vocabulary_uri, Unset):
            vocabulary_uri = UNSET
        else:
            vocabulary_uri = self.vocabulary_uri

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "keyword": keyword,
            }
        )
        if keyword_type is not UNSET:
            field_dict["keyword_type"] = keyword_type
        if vocabulary_uri is not UNSET:
            field_dict["vocabulary_uri"] = vocabulary_uri

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        keyword = d.pop("keyword")

        keyword_type = d.pop("keyword_type", UNSET)

        def _parse_vocabulary_uri(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        vocabulary_uri = _parse_vocabulary_uri(d.pop("vocabulary_uri", UNSET))

        keyword_create = cls(
            keyword=keyword,
            keyword_type=keyword_type,
            vocabulary_uri=vocabulary_uri,
        )

        keyword_create.additional_properties = d
        return keyword_create

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
