from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="OAuthProviderPublic")


@_attrs_define
class OAuthProviderPublic:
    """Minimal provider info for the login page (no secrets, no config).

    Attributes:
        display_name (str): Label shown on the login page button.
        provider_type (str): Provider type, used by the frontend to pick the right icon.
        slug (str): URL-safe identifier used in the callback URL.
    """

    display_name: str
    provider_type: str
    slug: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        display_name = self.display_name

        provider_type = self.provider_type

        slug = self.slug

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "display_name": display_name,
                "provider_type": provider_type,
                "slug": slug,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        display_name = d.pop("display_name")

        provider_type = d.pop("provider_type")

        slug = d.pop("slug")

        o_auth_provider_public = cls(
            display_name=display_name,
            provider_type=provider_type,
            slug=slug,
        )

        o_auth_provider_public.additional_properties = d
        return o_auth_provider_public

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
