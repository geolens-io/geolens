from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.translation_response import TranslationResponse


T = TypeVar("T", bound="TranslationListResponse")


@_attrs_define
class TranslationListResponse:
    """
    Attributes:
        translations (list[TranslationResponse]):
        total (int):
    """

    translations: list[TranslationResponse]
    total: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        translations = []
        for translations_item_data in self.translations:
            translations_item = translations_item_data.to_dict()
            translations.append(translations_item)

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "translations": translations,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.translation_response import TranslationResponse

        d = dict(src_dict)
        translations = []
        _translations = d.pop("translations")
        for translations_item_data in _translations:
            translations_item = TranslationResponse.from_dict(translations_item_data)

            translations.append(translations_item)

        total = d.pop("total")

        translation_list_response = cls(
            translations=translations,
            total=total,
        )

        translation_list_response.additional_properties = d
        return translation_list_response

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
