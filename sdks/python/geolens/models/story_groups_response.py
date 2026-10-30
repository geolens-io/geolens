from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.stored_story_visibility import check_stored_story_visibility
from ..models.stored_story_visibility import StoredStoryVisibility
from uuid import UUID

if TYPE_CHECKING:
    from ..models.group_ref import GroupRef


T = TypeVar("T", bound="StoryGroupsResponse")


@_attrs_define
class StoryGroupsResponse:
    """
    Attributes:
        visibility (StoredStoryVisibility): A story's visibility as stored. A private story shared with groups is
            ``restricted``: its groups' members read it too.
        groups (list[GroupRef]): The sharing groups the story is shared with, by name.
        shared_map_ids (list[UUID] | Unset): Maps this request shared with the story's new groups.
    """

    visibility: StoredStoryVisibility
    groups: list[GroupRef]
    shared_map_ids: list[UUID] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        visibility: str = self.visibility

        groups = []
        for groups_item_data in self.groups:
            groups_item = groups_item_data.to_dict()
            groups.append(groups_item)

        shared_map_ids: list[str] | Unset = UNSET
        if not isinstance(self.shared_map_ids, Unset):
            shared_map_ids = []
            for shared_map_ids_item_data in self.shared_map_ids:
                shared_map_ids_item = str(shared_map_ids_item_data)
                shared_map_ids.append(shared_map_ids_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "visibility": visibility,
                "groups": groups,
            }
        )
        if shared_map_ids is not UNSET:
            field_dict["shared_map_ids"] = shared_map_ids

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.group_ref import GroupRef

        d = dict(src_dict)
        visibility = check_stored_story_visibility(d.pop("visibility"))

        groups = []
        _groups = d.pop("groups")
        for groups_item_data in _groups:
            groups_item = GroupRef.from_dict(groups_item_data)

            groups.append(groups_item)

        _shared_map_ids = d.pop("shared_map_ids", UNSET)
        shared_map_ids: list[UUID] | Unset = UNSET
        if _shared_map_ids is not UNSET:
            shared_map_ids = []
            for shared_map_ids_item_data in _shared_map_ids:
                shared_map_ids_item = UUID(shared_map_ids_item_data)

                shared_map_ids.append(shared_map_ids_item)

        story_groups_response = cls(
            visibility=visibility,
            groups=groups,
            shared_map_ids=shared_map_ids,
        )

        story_groups_response.additional_properties = d
        return story_groups_response

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
