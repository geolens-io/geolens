from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


T = TypeVar("T", bound="StoryRevision")


@_attrs_define
class StoryRevision:
    """
    Attributes:
        revision (int): The draft revision this publish or discard acts on.
    """

    revision: int

    def to_dict(self) -> dict[str, Any]:
        revision = self.revision

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "revision": revision,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        revision = d.pop("revision")

        story_revision = cls(
            revision=revision,
        )

        return story_revision
