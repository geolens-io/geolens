from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast


T = TypeVar("T", bound="CapabilitiesAuth")


@_attrs_define
class CapabilitiesAuth:
    """
    Attributes:
        password_login_enabled (bool): Whether username and password sign-in is on.
        methods (list[str]): Sign-in methods on offer: `password` plus each enabled provider type.
    """

    password_login_enabled: bool
    methods: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        password_login_enabled = self.password_login_enabled

        methods = self.methods

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "password_login_enabled": password_login_enabled,
                "methods": methods,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        password_login_enabled = d.pop("password_login_enabled")

        methods = cast(list[str], d.pop("methods"))

        capabilities_auth = cls(
            password_login_enabled=password_login_enabled,
            methods=methods,
        )

        capabilities_auth.additional_properties = d
        return capabilities_auth

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
