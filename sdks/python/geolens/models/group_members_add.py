from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from uuid import UUID


T = TypeVar("T", bound="GroupMembersAdd")


@_attrs_define
class GroupMembersAdd:
    """
    Attributes:
        user_ids (list[UUID]): Users to add. Users already in the group are left as they are; if any id matches no user,
            none are added.
    """

    user_ids: list[UUID]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        user_ids = []
        for user_ids_item_data in self.user_ids:
            user_ids_item = str(user_ids_item_data)
            user_ids.append(user_ids_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "user_ids": user_ids,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        user_ids = []
        _user_ids = d.pop("user_ids")
        for user_ids_item_data in _user_ids:
            user_ids_item = UUID(user_ids_item_data)

            user_ids.append(user_ids_item)

        group_members_add = cls(
            user_ids=user_ids,
        )

        group_members_add.additional_properties = d
        return group_members_add

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
