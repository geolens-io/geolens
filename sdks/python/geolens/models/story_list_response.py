from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.story_summary import StorySummary


T = TypeVar("T", bound="StoryListResponse")


@_attrs_define
class StoryListResponse:
    """
    Attributes:
        stories (list[StorySummary]):
        total (int):
    """

    stories: list[StorySummary]
    total: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        stories = []
        for stories_item_data in self.stories:
            stories_item = stories_item_data.to_dict()
            stories.append(stories_item)

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "stories": stories,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.story_summary import StorySummary

        d = dict(src_dict)
        stories = []
        _stories = d.pop("stories")
        for stories_item_data in _stories:
            stories_item = StorySummary.from_dict(stories_item_data)

            stories.append(stories_item)

        total = d.pop("total")

        story_list_response = cls(
            stories=stories,
            total=total,
        )

        story_list_response.additional_properties = d
        return story_list_response

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
