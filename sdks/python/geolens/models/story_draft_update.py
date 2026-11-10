from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define


if TYPE_CHECKING:
    from ..models.story_document_input import StoryDocumentInput


T = TypeVar("T", bound="StoryDraftUpdate")


@_attrs_define
class StoryDraftUpdate:
    """
    Attributes:
        revision (int): The draft revision this save replaces.
        document (StoryDocumentInput):
    """

    revision: int
    document: StoryDocumentInput

    def to_dict(self) -> dict[str, Any]:
        revision = self.revision

        document = self.document.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "revision": revision,
                "document": document,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.story_document_input import StoryDocumentInput

        d = dict(src_dict)
        revision = d.pop("revision")

        document = StoryDocumentInput.from_dict(d.pop("document"))

        story_draft_update = cls(
            revision=revision,
            document=document,
        )

        return story_draft_update
