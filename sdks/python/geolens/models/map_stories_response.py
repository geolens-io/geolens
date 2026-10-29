from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.map_story_reference import MapStoryReference


T = TypeVar("T", bound="MapStoriesResponse")


@_attrs_define
class MapStoriesResponse:
    """
    Attributes:
        stories (list[MapStoryReference]): Stories using the map that you can read, by title.
        hidden_count (int): Stories using the map that you can't read; not named.
    """

    stories: list[MapStoryReference]
    hidden_count: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        stories = []
        for stories_item_data in self.stories:
            stories_item = stories_item_data.to_dict()
            stories.append(stories_item)

        hidden_count = self.hidden_count

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "stories": stories,
                "hidden_count": hidden_count,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.map_story_reference import MapStoryReference

        d = dict(src_dict)
        stories = []
        _stories = d.pop("stories")
        for stories_item_data in _stories:
            stories_item = MapStoryReference.from_dict(stories_item_data)

            stories.append(stories_item)

        hidden_count = d.pop("hidden_count")

        map_stories_response = cls(
            stories=stories,
            hidden_count=hidden_count,
        )

        map_stories_response.additional_properties = d
        return map_stories_response

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
