from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from dateutil.parser import isoparse
from uuid import UUID
import datetime


T = TypeVar("T", bound="GroupResponse")


@_attrs_define
class GroupResponse:
    """
    Attributes:
        id (UUID): Unique group identifier.
        name (str): Group name.
        member_count (int): Number of users in the group.
        created_at (datetime.datetime): When the group was created.
        updated_at (datetime.datetime): When the group was last renamed.
    """

    id: UUID
    name: str
    member_count: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        name = self.name

        member_count = self.member_count

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "name": name,
                "member_count": member_count,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        name = d.pop("name")

        member_count = d.pop("member_count")

        created_at = isoparse(d.pop("created_at"))

        updated_at = isoparse(d.pop("updated_at"))

        group_response = cls(
            id=id,
            name=name,
            member_count=member_count,
            created_at=created_at,
            updated_at=updated_at,
        )

        group_response.additional_properties = d
        return group_response

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
