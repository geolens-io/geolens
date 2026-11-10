from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.story_chapter_input import StoryChapterInput
    from ..models.story_settings import StorySettings


T = TypeVar("T", bound="StoryDocumentInput")


@_attrs_define
class StoryDocumentInput:
    """
    Attributes:
        version (Literal[1] | Unset):  Default: 1.
        chapters (list[StoryChapterInput] | Unset):
        settings (None | StorySettings | Unset): Reader settings; absent means every default.
    """

    version: Literal[1] | Unset = 1
    chapters: list[StoryChapterInput] | Unset = UNSET
    settings: None | StorySettings | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.story_settings import StorySettings

        version = self.version

        chapters: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.chapters, Unset):
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

        field_dict.update({})
        if version is not UNSET:
            field_dict["version"] = version
        if chapters is not UNSET:
            field_dict["chapters"] = chapters
        if settings is not UNSET:
            field_dict["settings"] = settings

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.story_chapter_input import StoryChapterInput
        from ..models.story_settings import StorySettings

        d = dict(src_dict)
        version = cast(Literal[1] | Unset, d.pop("version", UNSET))
        if version != 1 and not isinstance(version, Unset):
            raise ValueError(f"version must match const 1, got '{version}'")

        _chapters = d.pop("chapters", UNSET)
        chapters: list[StoryChapterInput] | Unset = UNSET
        if _chapters is not UNSET:
            chapters = []
            for chapters_item_data in _chapters:
                chapters_item = StoryChapterInput.from_dict(chapters_item_data)

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

        story_document_input = cls(
            version=version,
            chapters=chapters,
            settings=settings,
        )

        return story_document_input
