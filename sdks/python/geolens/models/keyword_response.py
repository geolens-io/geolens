from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID


T = TypeVar("T", bound="KeywordResponse")


@_attrs_define
class KeywordResponse:
    """
    Attributes:
        id (UUID):
        record_id (UUID):
        keyword (str):
        vocabulary_uri (None | str):
        keyword_type (str):
        inherited (bool | Unset): True when this keyword also exists on the dataset this record was derived from (feat
            #1070). Derived at read time from derived_from; only ever true for a requester who can access that source
            dataset, so everyone else sees false — matching the derived_from redaction. Default: False.
    """

    id: UUID
    record_id: UUID
    keyword: str
    vocabulary_uri: None | str
    keyword_type: str
    inherited: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        record_id = str(self.record_id)

        keyword = self.keyword

        vocabulary_uri: None | str
        vocabulary_uri = self.vocabulary_uri

        keyword_type = self.keyword_type

        inherited = self.inherited

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "record_id": record_id,
                "keyword": keyword,
                "vocabulary_uri": vocabulary_uri,
                "keyword_type": keyword_type,
            }
        )
        if inherited is not UNSET:
            field_dict["inherited"] = inherited

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        record_id = UUID(d.pop("record_id"))

        keyword = d.pop("keyword")

        def _parse_vocabulary_uri(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        vocabulary_uri = _parse_vocabulary_uri(d.pop("vocabulary_uri"))

        keyword_type = d.pop("keyword_type")

        inherited = d.pop("inherited", UNSET)

        keyword_response = cls(
            id=id,
            record_id=record_id,
            keyword=keyword,
            vocabulary_uri=vocabulary_uri,
            keyword_type=keyword_type,
            inherited=inherited,
        )

        keyword_response.additional_properties = d
        return keyword_response

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
