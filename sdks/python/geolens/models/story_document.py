from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.story_chapter import StoryChapter
    from ..models.story_settings import StorySettings


T = TypeVar("T", bound="StoryDocument")


@_attrs_define
class StoryDocument:
    """
    Attributes:
        version (int):
        chapters (list[StoryChapter]):
        settings (None | StorySettings | Unset):
    """

    version: int
    chapters: list[StoryChapter]
    settings: None | StorySettings | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.story_settings import StorySettings

        version = self.version

        chapters = []
        for chapters_item_data in self.chapters:
            chapters_item = chapters_item_data.to_dict()
            chapters.append(chapters_item)

        settings: dict[str, Any] | None | Unset
        if isinstance(self.settings, Unset):
            settings = UNSET
        elif isinstance(self.settings, StorySettings):
            settings = self.settings.to_dict()
        else:
            settings = self.settings

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "version": version,
                "chapters": chapters,
            }
        )
        if settings is not UNSET:
            field_dict["settings"] = settings

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.story_chapter import StoryChapter
        from ..models.story_settings import StorySettings

        d = dict(src_dict)
        version = d.pop("version")

        chapters = []
        _chapters = d.pop("chapters")
        for chapters_item_data in _chapters:
            chapters_item = StoryChapter.from_dict(chapters_item_data)

            chapters.append(chapters_item)

        def _parse_settings(data: object) -> None | StorySettings | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                settings_type_0 = StorySettings.from_dict(data)

                return settings_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | StorySettings | Unset, data)

        settings = _parse_settings(d.pop("settings", UNSET))

        story_document = cls(
            version=version,
            chapters=chapters,
            settings=settings,
        )

        story_document.additional_properties = d
        return story_document

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
