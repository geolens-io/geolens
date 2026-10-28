from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.story_chapter_input import StoryChapterInput


T = TypeVar("T", bound="StoryDocumentInput")


@_attrs_define
class StoryDocumentInput:
    """
    Attributes:
        version (Literal[1] | Unset):  Default: 1.
        chapters (list[StoryChapterInput] | Unset):
    """

    version: Literal[1] | Unset = 1
    chapters: list[StoryChapterInput] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        version = self.version

        chapters: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.chapters, Unset):
            chapters = []
            for chapters_item_data in self.chapters:
                chapters_item = chapters_item_data.to_dict()
                chapters.append(chapters_item)

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if version is not UNSET:
            field_dict["version"] = version
        if chapters is not UNSET:
            field_dict["chapters"] = chapters

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.story_chapter_input import StoryChapterInput

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

        story_document_input = cls(
            version=version,
            chapters=chapters,
        )

        return story_document_input
