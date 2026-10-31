from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from typing import Literal
from uuid import UUID


T = TypeVar("T", bound="StoryGroupsUpdate")


@_attrs_define
class StoryGroupsUpdate:
    """
    Attributes:
        group_ids (list[UUID]): Every group the story is shared with afterwards; an empty list unshares it. An owner may
            add only groups they belong to, and an admin any group.
        confirm (Literal['share_maps'] | None | Unset): Required to go ahead when maps the story uses block some of its
            groups; without it the request answers 409 and lists them. `share_maps` first shares each map marked `can_share`
            with the groups that lack it, which makes a private one restricted. The request is still refused while any other
            map blocks it.
    """

    group_ids: list[UUID]
    confirm: Literal["share_maps"] | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        group_ids = []
        for group_ids_item_data in self.group_ids:
            group_ids_item = str(group_ids_item_data)
            group_ids.append(group_ids_item)

        confirm: Literal["share_maps"] | None | Unset
        if isinstance(self.confirm, Unset):
            confirm = UNSET
        else:
            confirm = self.confirm

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "group_ids": group_ids,
            }
        )
        if confirm is not UNSET:
            field_dict["confirm"] = confirm

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        group_ids = []
        _group_ids = d.pop("group_ids")
        for group_ids_item_data in _group_ids:
            group_ids_item = UUID(group_ids_item_data)

            group_ids.append(group_ids_item)

        def _parse_confirm(data: object) -> Literal["share_maps"] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            confirm_type_0 = cast(Literal["share_maps"], data)
            if confirm_type_0 != "share_maps":
                raise ValueError(
                    f"confirm_type_0 must match const 'share_maps', got '{confirm_type_0}'"
                )
            return confirm_type_0
            return cast(Literal["share_maps"] | None | Unset, data)

        confirm = _parse_confirm(d.pop("confirm", UNSET))

        story_groups_update = cls(
            group_ids=group_ids,
            confirm=confirm,
        )

        return story_groups_update
