from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.user_response_status import check_user_response_status
from ..models.user_response_status import UserResponseStatus
from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime


T = TypeVar("T", bound="UserResponse")


@_attrs_define
class UserResponse:
    """
    Attributes:
        created_at (datetime.datetime):
        email (None | str):
        id (UUID):
        is_active (bool):
        last_login_at (datetime.datetime | None):
        roles (list[str]): Assigned role names, e.g. ['admin', 'editor']
        status (UserResponseStatus): Account status: active, pending, suspended, or deactivated.
        username (str):
    """

    created_at: datetime.datetime
    email: None | str
    id: UUID
    is_active: bool
    last_login_at: datetime.datetime | None
    roles: list[str]
    status: UserResponseStatus
    username: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        email: None | str
        email = self.email

        id = str(self.id)

        is_active = self.is_active

        last_login_at: None | str
        if isinstance(self.last_login_at, datetime.datetime):
            last_login_at = self.last_login_at.isoformat()
        else:
            last_login_at = self.last_login_at

        roles = self.roles

        status: str = self.status

        username = self.username

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "email": email,
                "id": id,
                "is_active": is_active,
                "last_login_at": last_login_at,
                "roles": roles,
                "status": status,
                "username": username,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        def _parse_email(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        email = _parse_email(d.pop("email"))

        id = UUID(d.pop("id"))

        is_active = d.pop("is_active")

        def _parse_last_login_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_login_at_type_0 = isoparse(data)

                return last_login_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        last_login_at = _parse_last_login_at(d.pop("last_login_at"))

        roles = cast(list[str], d.pop("roles"))

        status = check_user_response_status(d.pop("status"))

        username = d.pop("username")

        user_response = cls(
            created_at=created_at,
            email=email,
            id=id,
            is_active=is_active,
            last_login_at=last_login_at,
            roles=roles,
            status=status,
            username=username,
        )

        user_response.additional_properties = d
        return user_response

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
