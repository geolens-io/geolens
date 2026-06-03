from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="SamlToLocalConversion")


@_attrs_define
class SamlToLocalConversion:
    """Request body for POST /admin/users/{user_id}/convert-saml-to-local/.

    Per Phase 221 D-01: a dedicated, single-purpose schema kept narrow on
    purpose -- password is intentionally NOT on the generic UserUpdate schema
    (which has no password field) so this conversion produces a single,
    audit-distinct action ('user.convert_saml_to_local') instead of being
    folded into 'user.update'.

        Attributes:
            password (str): Local-password for the converted account (policy: min 12 chars, 3+ character classes). The user
                can change this after first login.
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

        saml_to_local_conversion = cls(
            password=password,
        )

        saml_to_local_conversion.additional_properties = d
        return saml_to_local_conversion

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
