from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime


T = TypeVar("T", bound="AdminApiKeyListItem")


@_attrs_define
class AdminApiKeyListItem:
    """
    Attributes:
        id (UUID): Unique API key identifier.
        user_id (UUID): Owning user's ID.
        name (str): Human-readable label.
        fingerprint (None | str): Non-secret key identifier; null for legacy keys.
        is_active (bool): Whether the key is active. Inactive keys cannot authenticate.
        scope (str): Privilege scope: 'full' or 'read_only' (#875).
        created_at (datetime.datetime): Timestamp when the key was created.
        last_used_at (datetime.datetime | None): Timestamp of the most recent successful authentication using this key.
        expires_at (datetime.datetime | None | Unset): Expiry timestamp; null means the key does not expire.
    """

    id: UUID
    user_id: UUID
    name: str
    fingerprint: None | str
    is_active: bool
    scope: str
    created_at: datetime.datetime
    last_used_at: datetime.datetime | None
    expires_at: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        user_id = str(self.user_id)

        name = self.name

        fingerprint: None | str
        fingerprint = self.fingerprint

        is_active = self.is_active

        scope = self.scope

        created_at = self.created_at.isoformat()

        last_used_at: None | str
        if isinstance(self.last_used_at, datetime.datetime):
            last_used_at = self.last_used_at.isoformat()
        else:
            last_used_at = self.last_used_at

        expires_at: None | str | Unset
        if isinstance(self.expires_at, Unset):
            expires_at = UNSET
        elif isinstance(self.expires_at, datetime.datetime):
            expires_at = self.expires_at.isoformat()
        else:
            expires_at = self.expires_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "user_id": user_id,
                "name": name,
                "fingerprint": fingerprint,
                "is_active": is_active,
                "scope": scope,
                "created_at": created_at,
                "last_used_at": last_used_at,
            }
        )
        if expires_at is not UNSET:
            field_dict["expires_at"] = expires_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        user_id = UUID(d.pop("user_id"))

        name = d.pop("name")

        def _parse_fingerprint(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        fingerprint = _parse_fingerprint(d.pop("fingerprint"))

        is_active = d.pop("is_active")

        scope = d.pop("scope")

        created_at = isoparse(d.pop("created_at"))

        def _parse_last_used_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_used_at_type_0 = isoparse(data)

                return last_used_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        last_used_at = _parse_last_used_at(d.pop("last_used_at"))

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

        admin_api_key_list_item = cls(
            id=id,
            user_id=user_id,
            name=name,
            fingerprint=fingerprint,
            is_active=is_active,
            scope=scope,
            created_at=created_at,
            last_used_at=last_used_at,
            expires_at=expires_at,
        )

        admin_api_key_list_item.additional_properties = d
        return admin_api_key_list_item

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
