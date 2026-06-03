from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
    from ..models.o_auth_provider_response_group_role_mapping_type_0 import (
        OAuthProviderResponseGroupRoleMappingType0,
    )


T = TypeVar("T", bound="OAuthProviderResponse")


@_attrs_define
class OAuthProviderResponse:
    """Response schema for OAuth/SAML provider.

    Write-only credentials are never exposed:
      - ``client_secret_encrypted`` (OAuth client secret) — excluded.
      - ``idp_certificate`` (SAML IdP signing cert, Fernet-encrypted at rest) — excluded.

    The 3 non-secret SAML fields (``idp_entity_id``, ``idp_sso_url``,
    ``sp_entity_id``) ARE exposed so the admin UI can display them.

    Pitfall 11 interaction: those 3 fields are declared with ``deferred=True``
    on the OAuth ORM model so community DBs (which lack the columns) do not
    crash on SELECT. Pydantic's ``from_attributes=True`` would normally trigger
    an implicit deferred load on attribute access, which fails under FastAPI's
    async context with ``MissingGreenlet``. The ``model_validator(mode="before")``
    below reads the SAML fields directly from ``obj.__dict__`` so unloaded
    attributes default to None instead of triggering IO. SAML admin endpoints
    that need the values must use ``undefer_group("saml")`` at query time.

        Attributes:
            created_at (datetime.datetime): Timestamp the provider was created.
            default_role (str): Default role assigned to new users.
            display_name (str): Label shown on the login page button.
            enabled (bool): Whether the provider button appears on the login page.
            id (UUID): Unique provider identifier.
            provider_type (str): Provider type: 'google', 'microsoft', 'oidc', or 'saml'.
            scopes (str): Space-separated OAuth scopes.
            slug (str): URL-safe identifier used in the callback URL.
            updated_at (datetime.datetime): Timestamp the provider was last updated.
            authorize_url (None | str | Unset): Authorization endpoint.
            client_id (None | str | Unset): OAuth client ID. Visible to admins; never exposes client_secret. Null for SAML
                providers.
            discovery_url (None | str | Unset): OIDC discovery URL.
            group_claim (None | str | Unset): Claim name used for group-based role mapping.
            group_role_mapping (None | OAuthProviderResponseGroupRoleMappingType0 | Unset): Group-to-role mapping rules.
            idp_entity_id (None | str | Unset): SAML IdP entityID (SAML providers only).
            idp_sso_url (None | str | Unset): SAML IdP SSO URL (SAML providers only).
            sp_entity_id (None | str | Unset): SP entityID for this SAML provider (SAML providers only).
            token_url (None | str | Unset): Token endpoint.
            userinfo_url (None | str | Unset): Userinfo endpoint.
    """

    created_at: datetime.datetime
    default_role: str
    display_name: str
    enabled: bool
    id: UUID
    provider_type: str
    scopes: str
    slug: str
    updated_at: datetime.datetime
    authorize_url: None | str | Unset = UNSET
    client_id: None | str | Unset = UNSET
    discovery_url: None | str | Unset = UNSET
    group_claim: None | str | Unset = UNSET
    group_role_mapping: None | OAuthProviderResponseGroupRoleMappingType0 | Unset = (
        UNSET
    )
    idp_entity_id: None | str | Unset = UNSET
    idp_sso_url: None | str | Unset = UNSET
    sp_entity_id: None | str | Unset = UNSET
    token_url: None | str | Unset = UNSET
    userinfo_url: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.o_auth_provider_response_group_role_mapping_type_0 import (
            OAuthProviderResponseGroupRoleMappingType0,
        )

        created_at = self.created_at.isoformat()

        default_role = self.default_role

        display_name = self.display_name

        enabled = self.enabled

        id = str(self.id)

        provider_type = self.provider_type

        scopes = self.scopes

        slug = self.slug

        updated_at = self.updated_at.isoformat()

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

        discovery_url: None | str | Unset
        if isinstance(self.discovery_url, Unset):
            discovery_url = UNSET
        else:
            discovery_url = self.discovery_url

        group_claim: None | str | Unset
        if isinstance(self.group_claim, Unset):
            group_claim = UNSET
        else:
            group_claim = self.group_claim

        group_role_mapping: dict[str, Any] | None | Unset
        if isinstance(self.group_role_mapping, Unset):
            group_role_mapping = UNSET
        elif isinstance(
            self.group_role_mapping, OAuthProviderResponseGroupRoleMappingType0
        ):
            group_role_mapping = self.group_role_mapping.to_dict()
        else:
            group_role_mapping = self.group_role_mapping

        idp_entity_id: None | str | Unset
        if isinstance(self.idp_entity_id, Unset):
            idp_entity_id = UNSET
        else:
            idp_entity_id = self.idp_entity_id

        idp_sso_url: None | str | Unset
        if isinstance(self.idp_sso_url, Unset):
            idp_sso_url = UNSET
        else:
            idp_sso_url = self.idp_sso_url

        sp_entity_id: None | str | Unset
        if isinstance(self.sp_entity_id, Unset):
            sp_entity_id = UNSET
        else:
            sp_entity_id = self.sp_entity_id

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
                "created_at": created_at,
                "default_role": default_role,
                "display_name": display_name,
                "enabled": enabled,
                "id": id,
                "provider_type": provider_type,
                "scopes": scopes,
                "slug": slug,
                "updated_at": updated_at,
            }
        )
        if authorize_url is not UNSET:
            field_dict["authorize_url"] = authorize_url
        if client_id is not UNSET:
            field_dict["client_id"] = client_id
        if discovery_url is not UNSET:
            field_dict["discovery_url"] = discovery_url
        if group_claim is not UNSET:
            field_dict["group_claim"] = group_claim
        if group_role_mapping is not UNSET:
            field_dict["group_role_mapping"] = group_role_mapping
        if idp_entity_id is not UNSET:
            field_dict["idp_entity_id"] = idp_entity_id
        if idp_sso_url is not UNSET:
            field_dict["idp_sso_url"] = idp_sso_url
        if sp_entity_id is not UNSET:
            field_dict["sp_entity_id"] = sp_entity_id
        if token_url is not UNSET:
            field_dict["token_url"] = token_url
        if userinfo_url is not UNSET:
            field_dict["userinfo_url"] = userinfo_url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.o_auth_provider_response_group_role_mapping_type_0 import (
            OAuthProviderResponseGroupRoleMappingType0,
        )

        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        default_role = d.pop("default_role")

        display_name = d.pop("display_name")

        enabled = d.pop("enabled")

        id = UUID(d.pop("id"))

        provider_type = d.pop("provider_type")

        scopes = d.pop("scopes")

        slug = d.pop("slug")

        updated_at = isoparse(d.pop("updated_at"))

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

        def _parse_discovery_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        discovery_url = _parse_discovery_url(d.pop("discovery_url", UNSET))

        def _parse_group_claim(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        group_claim = _parse_group_claim(d.pop("group_claim", UNSET))

        def _parse_group_role_mapping(
            data: object,
        ) -> None | OAuthProviderResponseGroupRoleMappingType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                group_role_mapping_type_0 = (
                    OAuthProviderResponseGroupRoleMappingType0.from_dict(data)
                )

                return group_role_mapping_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OAuthProviderResponseGroupRoleMappingType0 | Unset, data)

        group_role_mapping = _parse_group_role_mapping(
            d.pop("group_role_mapping", UNSET)
        )

        def _parse_idp_entity_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        idp_entity_id = _parse_idp_entity_id(d.pop("idp_entity_id", UNSET))

        def _parse_idp_sso_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        idp_sso_url = _parse_idp_sso_url(d.pop("idp_sso_url", UNSET))

        def _parse_sp_entity_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        sp_entity_id = _parse_sp_entity_id(d.pop("sp_entity_id", UNSET))

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

        o_auth_provider_response = cls(
            created_at=created_at,
            default_role=default_role,
            display_name=display_name,
            enabled=enabled,
            id=id,
            provider_type=provider_type,
            scopes=scopes,
            slug=slug,
            updated_at=updated_at,
            authorize_url=authorize_url,
            client_id=client_id,
            discovery_url=discovery_url,
            group_claim=group_claim,
            group_role_mapping=group_role_mapping,
            idp_entity_id=idp_entity_id,
            idp_sso_url=idp_sso_url,
            sp_entity_id=sp_entity_id,
            token_url=token_url,
            userinfo_url=userinfo_url,
        )

        o_auth_provider_response.additional_properties = d
        return o_auth_provider_response

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
