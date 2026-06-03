from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime


T = TypeVar("T", bound="AdminApiKeyListItem")


@_attrs_define
class AdminApiKeyListItem:
    """
    Attributes:
        created_at (datetime.datetime): Timestamp when the key was created.
        id (UUID): Unique API key identifier.
        is_active (bool): Whether the key is active. Inactive keys cannot authenticate.
        last_used_at (datetime.datetime | None): Timestamp of the most recent successful authentication using this key.
        name (str): Human-readable label.
        user_id (UUID): Owning user's ID.
    """

    created_at: datetime.datetime
    id: UUID
    is_active: bool
    last_used_at: datetime.datetime | None
    name: str
    user_id: UUID
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        id = str(self.id)

        is_active = self.is_active

        last_used_at: None | str
        if isinstance(self.last_used_at, datetime.datetime):
            last_used_at = self.last_used_at.isoformat()
        else:
            last_used_at = self.last_used_at

        name = self.name

        user_id = str(self.user_id)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "id": id,
                "is_active": is_active,
                "last_used_at": last_used_at,
                "name": name,
                "user_id": user_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        id = UUID(d.pop("id"))

        is_active = d.pop("is_active")

        def _parse_last_used_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_used_at_type_0 = isoparse(data)

                return last_used_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        last_used_at = _parse_last_used_at(d.pop("last_used_at"))

        name = d.pop("name")

        user_id = UUID(d.pop("user_id"))

        admin_api_key_list_item = cls(
            created_at=created_at,
            id=id,
            is_active=is_active,
            last_used_at=last_used_at,
            name=name,
            user_id=user_id,
        )

        admin_api_key_list_item.additional_properties = d
        return admin_api_key_list_item

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
