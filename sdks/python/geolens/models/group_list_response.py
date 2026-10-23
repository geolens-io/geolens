from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.group_response import GroupResponse


T = TypeVar("T", bound="GroupListResponse")


@_attrs_define
class GroupListResponse:
    """
    Attributes:
        groups (list[GroupResponse]): Page of groups, by name.
        total (int): Total number of groups (across all pages).
    """

    groups: list[GroupResponse]
    total: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        groups = []
        for groups_item_data in self.groups:
            groups_item = groups_item_data.to_dict()
            groups.append(groups_item)

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "groups": groups,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.group_response import GroupResponse

        d = dict(src_dict)
        groups = []
        _groups = d.pop("groups")
        for groups_item_data in _groups:
            groups_item = GroupResponse.from_dict(groups_item_data)

            groups.append(groups_item)

        total = d.pop("total")

        group_list_response = cls(
            groups=groups,
            total=total,
        )

        group_list_response.additional_properties = d
        return group_list_response

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
