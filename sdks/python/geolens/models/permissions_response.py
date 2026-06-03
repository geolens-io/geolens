from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.permissions_response_permissions import PermissionsResponsePermissions


T = TypeVar("T", bound="PermissionsResponse")


@_attrs_define
class PermissionsResponse:
    """
    Attributes:
        permissions (PermissionsResponsePermissions): Map of permission names to granted/denied
    """

    permissions: PermissionsResponsePermissions
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        permissions = self.permissions.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "permissions": permissions,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.permissions_response_permissions import (
            PermissionsResponsePermissions,
        )

        d = dict(src_dict)
        permissions = PermissionsResponsePermissions.from_dict(d.pop("permissions"))

        permissions_response = cls(
            permissions=permissions,
        )

        permissions_response.additional_properties = d
        return permissions_response

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
