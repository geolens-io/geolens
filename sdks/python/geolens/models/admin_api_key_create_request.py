from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.admin_api_key_create_request_scope import AdminApiKeyCreateRequestScope
from ..models.admin_api_key_create_request_scope import (
    check_admin_api_key_create_request_scope,
)
from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime


T = TypeVar("T", bound="AdminApiKeyCreateRequest")


@_attrs_define
class AdminApiKeyCreateRequest:
    """
    Attributes:
        user_id (UUID): ID of the user the new API key will belong to.
        name (str): Human-readable label for the API key (e.g. 'CI pipeline', 'QGIS desktop').
        expires_at (datetime.datetime | None | Unset): Optional expiry timestamp (RFC 3339, timezone-aware). Omit or
            null for a non-expiring key; expired keys stop authenticating.
        scope (AdminApiKeyCreateRequestScope | Unset): Privilege scope (#875). 'full' impersonates the owner completely,
            the pre-existing behavior. 'read_only' authenticates GET, HEAD and OPTIONS requests only; any other method is
            refused with 403. A service-account key minted for an application is the usual case for 'read_only'. Default:
            'full'.
    """

    user_id: UUID
    name: str
    expires_at: datetime.datetime | None | Unset = UNSET
    scope: AdminApiKeyCreateRequestScope | Unset = "full"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        user_id = str(self.user_id)

        name = self.name

        expires_at: None | str | Unset
        if isinstance(self.expires_at, Unset):
            expires_at = UNSET
        elif isinstance(self.expires_at, datetime.datetime):
            expires_at = self.expires_at.isoformat()
        else:
            expires_at = self.expires_at

        scope: str | Unset = UNSET
        if not isinstance(self.scope, Unset):
            scope = self.scope

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "user_id": user_id,
                "name": name,
            }
        )
        if expires_at is not UNSET:
            field_dict["expires_at"] = expires_at
        if scope is not UNSET:
            field_dict["scope"] = scope

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        user_id = UUID(d.pop("user_id"))

        name = d.pop("name")

        def _parse_expires_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                expires_at_type_0 = isoparse(data)

                return expires_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        expires_at = _parse_expires_at(d.pop("expires_at", UNSET))

        _scope = d.pop("scope", UNSET)
        scope: AdminApiKeyCreateRequestScope | Unset
        if isinstance(_scope, Unset):
            scope = UNSET
        else:
            scope = check_admin_api_key_create_request_scope(_scope)

        admin_api_key_create_request = cls(
            user_id=user_id,
            name=name,
            expires_at=expires_at,
            scope=scope,
        )

        admin_api_key_create_request.additional_properties = d
        return admin_api_key_create_request

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
