from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


if TYPE_CHECKING:
    from ..models.keyword_response import KeywordResponse


T = TypeVar("T", bound="KeywordListResponse")


@_attrs_define
class KeywordListResponse:
    """
    Attributes:
        keywords (list[KeywordResponse]):
        total (int):
        inherited_audience_gap (bool | Unset): True when at least one keyword is inherited AND this record's audience —
            at its stored state, or at the counterfactual audience_visibility/audience_record_status query parameters, which
            are honored only for the record's owner and admins — includes someone who cannot open the source dataset (feat
            #1070). Default: False.
    """

    keywords: list[KeywordResponse]
    total: int
    inherited_audience_gap: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        keywords = []
        for keywords_item_data in self.keywords:
            keywords_item = keywords_item_data.to_dict()
            keywords.append(keywords_item)

        total = self.total

        inherited_audience_gap = self.inherited_audience_gap

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "keywords": keywords,
                "total": total,
            }
        )
        if inherited_audience_gap is not UNSET:
            field_dict["inherited_audience_gap"] = inherited_audience_gap

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.keyword_response import KeywordResponse

        d = dict(src_dict)
        keywords = []
        _keywords = d.pop("keywords")
        for keywords_item_data in _keywords:
            keywords_item = KeywordResponse.from_dict(keywords_item_data)

            keywords.append(keywords_item)

        total = d.pop("total")

        inherited_audience_gap = d.pop("inherited_audience_gap", UNSET)

        keyword_list_response = cls(
            keywords=keywords,
            total=total,
            inherited_audience_gap=inherited_audience_gap,
        )

        keyword_list_response.additional_properties = d
        return keyword_list_response

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
