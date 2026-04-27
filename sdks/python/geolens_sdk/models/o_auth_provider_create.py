from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.o_auth_provider_create_provider_type import (
    check_o_auth_provider_create_provider_type,
)
from ..models.o_auth_provider_create_provider_type import (
    OAuthProviderCreateProviderType,
)
from typing import cast

if TYPE_CHECKING:
    from ..models.o_auth_provider_create_group_role_mapping_type_0 import (
        OAuthProviderCreateGroupRoleMappingType0,
    )


T = TypeVar("T", bound="OAuthProviderCreate")


@_attrs_define
class OAuthProviderCreate:
    """Schema for creating a new OAuth provider.

    Attributes:
        client_id (str): OAuth client ID issued by the IdP.
        client_secret (str): OAuth client secret issued by the IdP. Stored encrypted; never returned in responses.
        display_name (str): Human-readable label shown on the login page button.
        provider_type (OAuthProviderCreateProviderType): OAuth provider type. 'google' and 'microsoft' auto-populate the
            discovery URL; 'oidc' is generic.
        slug (str): URL-safe identifier used in callback URLs (e.g. 'google', 'azure-ad'). Lowercase, digits, and
            hyphens only.
        authorize_url (None | str | Unset): Authorization endpoint. Only needed when discovery_url is not set.
        default_role (str | Unset): Role assigned to new users created via this provider: 'viewer', 'editor', or
            'admin'. Default: 'viewer'.
        discovery_url (None | str | Unset): OIDC discovery URL ending in `.well-known/openid-configuration`. Auto-
            populated for Google and Microsoft.
        enabled (bool | Unset): Whether the provider button appears on the login page. Default: True.
        group_claim (None | str | Unset): Name of the JWT/userinfo claim that contains group memberships. Set to enable
            group-based role mapping.
        group_role_mapping (None | OAuthProviderCreateGroupRoleMappingType0 | Unset): JSON object mapping IdP group
            names to GeoLens roles. First match wins. Falls back to default_role if no group matches.
        scopes (str | Unset): Space-separated OAuth scopes. Default: 'openid profile email'.
        token_url (None | str | Unset): Token endpoint. Only needed when discovery_url is not set.
        userinfo_url (None | str | Unset): Userinfo endpoint. Only needed when discovery_url is not set.
    """

    client_id: str
    client_secret: str
    display_name: str
    provider_type: OAuthProviderCreateProviderType
    slug: str
    authorize_url: None | str | Unset = UNSET
    default_role: str | Unset = "viewer"
    discovery_url: None | str | Unset = UNSET
    enabled: bool | Unset = True
    group_claim: None | str | Unset = UNSET
    group_role_mapping: None | OAuthProviderCreateGroupRoleMappingType0 | Unset = UNSET
    scopes: str | Unset = "openid profile email"
    token_url: None | str | Unset = UNSET
    userinfo_url: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.o_auth_provider_create_group_role_mapping_type_0 import (
            OAuthProviderCreateGroupRoleMappingType0,
        )

        client_id = self.client_id

        client_secret = self.client_secret

        display_name = self.display_name

        provider_type: str = self.provider_type

        slug = self.slug

        authorize_url: None | str | Unset
        if isinstance(self.authorize_url, Unset):
            authorize_url = UNSET
        else:
            authorize_url = self.authorize_url

        default_role = self.default_role

        discovery_url: None | str | Unset
        if isinstance(self.discovery_url, Unset):
            discovery_url = UNSET
        else:
            discovery_url = self.discovery_url

        enabled = self.enabled

        group_claim: None | str | Unset
        if isinstance(self.group_claim, Unset):
            group_claim = UNSET
        else:
            group_claim = self.group_claim

        group_role_mapping: dict[str, Any] | None | Unset
        if isinstance(self.group_role_mapping, Unset):
            group_role_mapping = UNSET
        elif isinstance(
            self.group_role_mapping, OAuthProviderCreateGroupRoleMappingType0
        ):
            group_role_mapping = self.group_role_mapping.to_dict()
        else:
            group_role_mapping = self.group_role_mapping

        scopes = self.scopes

        token_url: None | str | Unset
        if isinstance(self.token_url, Unset):
            token_url = UNSET
        else:
            token_url = self.token_url

        userinfo_url: None | str | Unset
        if isinstance(self.userinfo_url, Unset):
            userinfo_url = UNSET
        else:
            userinfo_url = self.userinfo_url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "display_name": display_name,
                "provider_type": provider_type,
                "slug": slug,
            }
        )
        if authorize_url is not UNSET:
            field_dict["authorize_url"] = authorize_url
        if default_role is not UNSET:
            field_dict["default_role"] = default_role
        if discovery_url is not UNSET:
            field_dict["discovery_url"] = discovery_url
        if enabled is not UNSET:
            field_dict["enabled"] = enabled
        if group_claim is not UNSET:
            field_dict["group_claim"] = group_claim
        if group_role_mapping is not UNSET:
            field_dict["group_role_mapping"] = group_role_mapping
        if scopes is not UNSET:
            field_dict["scopes"] = scopes
        if token_url is not UNSET:
            field_dict["token_url"] = token_url
        if userinfo_url is not UNSET:
            field_dict["userinfo_url"] = userinfo_url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.o_auth_provider_create_group_role_mapping_type_0 import (
            OAuthProviderCreateGroupRoleMappingType0,
        )

        d = dict(src_dict)
        client_id = d.pop("client_id")

        client_secret = d.pop("client_secret")

        display_name = d.pop("display_name")

        provider_type = check_o_auth_provider_create_provider_type(
            d.pop("provider_type")
        )

        slug = d.pop("slug")

        def _parse_authorize_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        authorize_url = _parse_authorize_url(d.pop("authorize_url", UNSET))

        default_role = d.pop("default_role", UNSET)

        def _parse_discovery_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        discovery_url = _parse_discovery_url(d.pop("discovery_url", UNSET))

        enabled = d.pop("enabled", UNSET)

        def _parse_group_claim(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        group_claim = _parse_group_claim(d.pop("group_claim", UNSET))

        def _parse_group_role_mapping(
            data: object,
        ) -> None | OAuthProviderCreateGroupRoleMappingType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                group_role_mapping_type_0 = (
                    OAuthProviderCreateGroupRoleMappingType0.from_dict(data)
                )

                return group_role_mapping_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OAuthProviderCreateGroupRoleMappingType0 | Unset, data)

        group_role_mapping = _parse_group_role_mapping(
            d.pop("group_role_mapping", UNSET)
        )

        scopes = d.pop("scopes", UNSET)

        def _parse_token_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        token_url = _parse_token_url(d.pop("token_url", UNSET))

        def _parse_userinfo_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        userinfo_url = _parse_userinfo_url(d.pop("userinfo_url", UNSET))

        o_auth_provider_create = cls(
            client_id=client_id,
            client_secret=client_secret,
            display_name=display_name,
            provider_type=provider_type,
            slug=slug,
            authorize_url=authorize_url,
            default_role=default_role,
            discovery_url=discovery_url,
            enabled=enabled,
            group_claim=group_claim,
            group_role_mapping=group_role_mapping,
            scopes=scopes,
            token_url=token_url,
            userinfo_url=userinfo_url,
        )

        o_auth_provider_create.additional_properties = d
        return o_auth_provider_create

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
