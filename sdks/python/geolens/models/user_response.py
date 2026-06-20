from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.user_response_status import check_user_response_status
from ..models.user_response_status import UserResponseStatus
from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
    from ..models.user_quota_usage import UserQuotaUsage


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
        quota_usage (None | Unset | UserQuotaUsage): Per-user storage quota usage. Populated only on admin list
            responses; None when the caller did not load usage (e.g. /auth/me, single-user GET).
    """

    created_at: datetime.datetime
    email: None | str
    id: UUID
    is_active: bool
    last_login_at: datetime.datetime | None
    roles: list[str]
    status: UserResponseStatus
    username: str
    quota_usage: None | Unset | UserQuotaUsage = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.user_quota_usage import UserQuotaUsage

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

        quota_usage: dict[str, Any] | None | Unset
        if isinstance(self.quota_usage, Unset):
            quota_usage = UNSET
        elif isinstance(self.quota_usage, UserQuotaUsage):
            quota_usage = self.quota_usage.to_dict()
        else:
            quota_usage = self.quota_usage

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
        if quota_usage is not UNSET:
            field_dict["quota_usage"] = quota_usage

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.user_quota_usage import UserQuotaUsage

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

        def _parse_quota_usage(data: object) -> None | Unset | UserQuotaUsage:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                quota_usage_type_0 = UserQuotaUsage.from_dict(data)

                return quota_usage_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UserQuotaUsage, data)

        quota_usage = _parse_quota_usage(d.pop("quota_usage", UNSET))

        user_response = cls(
            created_at=created_at,
            email=email,
            id=id,
            is_active=is_active,
            last_login_at=last_login_at,
            roles=roles,
            status=status,
            username=username,
            quota_usage=quota_usage,
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
