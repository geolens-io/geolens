from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.o_auth_provider_update_provider_type_type_0 import (
    check_o_auth_provider_update_provider_type_type_0,
)
from ..models.o_auth_provider_update_provider_type_type_0 import (
    OAuthProviderUpdateProviderTypeType0,
)
from typing import cast

if TYPE_CHECKING:
    from ..models.o_auth_provider_update_group_role_mapping_type_0 import (
        OAuthProviderUpdateGroupRoleMappingType0,
    )


T = TypeVar("T", bound="OAuthProviderUpdate")


@_attrs_define
class OAuthProviderUpdate:
    """Schema for updating an existing OAuth provider. All fields optional.

    Attributes:
        authorize_url (None | str | Unset): Updated authorization endpoint.
        client_id (None | str | Unset): New client ID. Set when rotating credentials.
        client_secret (None | str | Unset): New client secret. Omit to leave unchanged; setting this rotates the stored
            secret.
        default_role (None | str | Unset): Updated default role for new users.
        discovery_url (None | str | Unset): Updated OIDC discovery URL.
        display_name (None | str | Unset): New display label.
        enabled (bool | None | Unset): Set to false to hide the provider button without deleting the configuration.
        group_claim (None | str | Unset): Updated group claim name.
        group_role_mapping (None | OAuthProviderUpdateGroupRoleMappingType0 | Unset): Updated group-to-role mapping.
            Pass an empty object to clear.
        provider_type (None | OAuthProviderUpdateProviderTypeType0 | Unset): New provider type. Rarely changed after
            creation.
        scopes (None | str | Unset): Updated space-separated scopes.
        slug (None | str | Unset): New slug. Changes the callback URL — coordinate with the IdP before updating.
        token_url (None | str | Unset): Updated token endpoint.
        userinfo_url (None | str | Unset): Updated userinfo endpoint.
    """

    authorize_url: None | str | Unset = UNSET
    client_id: None | str | Unset = UNSET
    client_secret: None | str | Unset = UNSET
    default_role: None | str | Unset = UNSET
    discovery_url: None | str | Unset = UNSET
    display_name: None | str | Unset = UNSET
    enabled: bool | None | Unset = UNSET
    group_claim: None | str | Unset = UNSET
    group_role_mapping: None | OAuthProviderUpdateGroupRoleMappingType0 | Unset = UNSET
    provider_type: None | OAuthProviderUpdateProviderTypeType0 | Unset = UNSET
    scopes: None | str | Unset = UNSET
    slug: None | str | Unset = UNSET
    token_url: None | str | Unset = UNSET
    userinfo_url: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.o_auth_provider_update_group_role_mapping_type_0 import (
            OAuthProviderUpdateGroupRoleMappingType0,
        )

        authorize_url: None | str | Unset
        if isinstance(self.authorize_url, Unset):
            authorize_url = UNSET
        else:
            authorize_url = self.authorize_url

        client_id: None | str | Unset
        if isinstance(self.client_id, Unset):
            client_id = UNSET
        else:
            client_id = self.client_id

        client_secret: None | str | Unset
        if isinstance(self.client_secret, Unset):
            client_secret = UNSET
        else:
            client_secret = self.client_secret

        default_role: None | str | Unset
        if isinstance(self.default_role, Unset):
            default_role = UNSET
        else:
            default_role = self.default_role

        discovery_url: None | str | Unset
        if isinstance(self.discovery_url, Unset):
            discovery_url = UNSET
        else:
            discovery_url = self.discovery_url

        display_name: None | str | Unset
        if isinstance(self.display_name, Unset):
            display_name = UNSET
        else:
            display_name = self.display_name

        enabled: bool | None | Unset
        if isinstance(self.enabled, Unset):
            enabled = UNSET
        else:
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
            self.group_role_mapping, OAuthProviderUpdateGroupRoleMappingType0
        ):
            group_role_mapping = self.group_role_mapping.to_dict()
        else:
            group_role_mapping = self.group_role_mapping

        provider_type: None | str | Unset
        if isinstance(self.provider_type, Unset):
            provider_type = UNSET
        elif isinstance(self.provider_type, str):
            provider_type = self.provider_type
        else:
            provider_type = self.provider_type

        scopes: None | str | Unset
        if isinstance(self.scopes, Unset):
            scopes = UNSET
        else:
            scopes = self.scopes

        slug: None | str | Unset
        if isinstance(self.slug, Unset):
            slug = UNSET
        else:
            slug = self.slug

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
        field_dict.update({})
        if authorize_url is not UNSET:
            field_dict["authorize_url"] = authorize_url
        if client_id is not UNSET:
            field_dict["client_id"] = client_id
        if client_secret is not UNSET:
            field_dict["client_secret"] = client_secret
        if default_role is not UNSET:
            field_dict["default_role"] = default_role
        if discovery_url is not UNSET:
            field_dict["discovery_url"] = discovery_url
        if display_name is not UNSET:
            field_dict["display_name"] = display_name
        if enabled is not UNSET:
            field_dict["enabled"] = enabled
        if group_claim is not UNSET:
            field_dict["group_claim"] = group_claim
        if group_role_mapping is not UNSET:
            field_dict["group_role_mapping"] = group_role_mapping
        if provider_type is not UNSET:
            field_dict["provider_type"] = provider_type
        if scopes is not UNSET:
            field_dict["scopes"] = scopes
        if slug is not UNSET:
            field_dict["slug"] = slug
        if token_url is not UNSET:
            field_dict["token_url"] = token_url
        if userinfo_url is not UNSET:
            field_dict["userinfo_url"] = userinfo_url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.o_auth_provider_update_group_role_mapping_type_0 import (
            OAuthProviderUpdateGroupRoleMappingType0,
        )

        d = dict(src_dict)

        def _parse_authorize_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        authorize_url = _parse_authorize_url(d.pop("authorize_url", UNSET))

        def _parse_client_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        client_id = _parse_client_id(d.pop("client_id", UNSET))

        def _parse_client_secret(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        client_secret = _parse_client_secret(d.pop("client_secret", UNSET))

        def _parse_default_role(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        default_role = _parse_default_role(d.pop("default_role", UNSET))

        def _parse_discovery_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        discovery_url = _parse_discovery_url(d.pop("discovery_url", UNSET))

        def _parse_display_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        display_name = _parse_display_name(d.pop("display_name", UNSET))

        def _parse_enabled(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        enabled = _parse_enabled(d.pop("enabled", UNSET))

        def _parse_group_claim(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        group_claim = _parse_group_claim(d.pop("group_claim", UNSET))

        def _parse_group_role_mapping(
            data: object,
        ) -> None | OAuthProviderUpdateGroupRoleMappingType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                group_role_mapping_type_0 = (
                    OAuthProviderUpdateGroupRoleMappingType0.from_dict(data)
                )

                return group_role_mapping_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OAuthProviderUpdateGroupRoleMappingType0 | Unset, data)

        group_role_mapping = _parse_group_role_mapping(
            d.pop("group_role_mapping", UNSET)
        )

        def _parse_provider_type(
            data: object,
        ) -> None | OAuthProviderUpdateProviderTypeType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                provider_type_type_0 = (
                    check_o_auth_provider_update_provider_type_type_0(data)
                )

                return provider_type_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OAuthProviderUpdateProviderTypeType0 | Unset, data)

        provider_type = _parse_provider_type(d.pop("provider_type", UNSET))

        def _parse_scopes(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        scopes = _parse_scopes(d.pop("scopes", UNSET))

        def _parse_slug(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        slug = _parse_slug(d.pop("slug", UNSET))

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

        o_auth_provider_update = cls(
            authorize_url=authorize_url,
            client_id=client_id,
            client_secret=client_secret,
            default_role=default_role,
            discovery_url=discovery_url,
            display_name=display_name,
            enabled=enabled,
            group_claim=group_claim,
            group_role_mapping=group_role_mapping,
            provider_type=provider_type,
            scopes=scopes,
            slug=slug,
            token_url=token_url,
            userinfo_url=userinfo_url,
        )

        o_auth_provider_update.additional_properties = d
        return o_auth_provider_update

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
