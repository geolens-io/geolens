from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast
from uuid import UUID


T = TypeVar("T", bound="TranslationResponse")


@_attrs_define
class TranslationResponse:
    """
    Attributes:
        language (str):
        record_id (UUID):
        summary (None | str):
        title (str):
    """

    language: str
    record_id: UUID
    summary: None | str
    title: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        language = self.language

        record_id = str(self.record_id)

        summary: None | str
        summary = self.summary

        title = self.title

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "language": language,
                "record_id": record_id,
                "summary": summary,
                "title": title,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        language = d.pop("language")

        record_id = UUID(d.pop("record_id"))

        def _parse_summary(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        summary = _parse_summary(d.pop("summary"))

        title = d.pop("title")

        translation_response = cls(
            language=language,
            record_id=record_id,
            summary=summary,
            title=title,
        )

        translation_response.additional_properties = d
        return translation_response

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
