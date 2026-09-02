from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="AdminPasswordReset")


@_attrs_define
class AdminPasswordReset:
    """Request body for POST /admin/users/{user_id}/reset-password/.

    Single-purpose for the same reason as SamlToLocalConversion above: the
    generic UserUpdate schema has no password field, so an admin-set password
    lands as its own audited action ('user.password_reset') rather than
    disappearing into 'user.update'.

        Attributes:
            password (str): Replacement password for the account (policy: min 12 chars, 3+ character classes, at most 72
                bytes UTF-8). The user can change this after their next login.
    """

    password: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        password = self.password

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "password": password,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        password = d.pop("password")

        admin_password_reset = cls(
            password=password,
        )

        admin_password_reset.additional_properties = d
        return admin_password_reset

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
