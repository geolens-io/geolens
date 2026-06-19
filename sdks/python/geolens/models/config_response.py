from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="ConfigResponse")


@_attrs_define
class ConfigResponse:
    """
    Attributes:
        registration_enabled (bool): Whether self-service registration is open
        auth_methods (list[str] | Unset): Auth methods contributed by the active AuthExtension. Empty in community; e.g.
            ['saml'] when the enterprise SAML overlay is installed. Login UI can render conditional sign-in options without
            needing admin OAuthProvider access.
        landing_first (bool | Unset): When true, unauthenticated visits to '/' are redirected to '/login' as the product
            landing page. Default false (search catalog is the root). Default: False.
    """

    registration_enabled: bool
    auth_methods: list[str] | Unset = UNSET
    landing_first: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        registration_enabled = self.registration_enabled

        auth_methods: list[str] | Unset = UNSET
        if not isinstance(self.auth_methods, Unset):
            auth_methods = self.auth_methods

        landing_first = self.landing_first

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "registration_enabled": registration_enabled,
            }
        )
        if auth_methods is not UNSET:
            field_dict["auth_methods"] = auth_methods
        if landing_first is not UNSET:
            field_dict["landing_first"] = landing_first

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        registration_enabled = d.pop("registration_enabled")

        auth_methods = cast(list[str], d.pop("auth_methods", UNSET))

        landing_first = d.pop("landing_first", UNSET)

        config_response = cls(
            registration_enabled=registration_enabled,
            auth_methods=auth_methods,
            landing_first=landing_first,
        )

        config_response.additional_properties = d
        return config_response

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
