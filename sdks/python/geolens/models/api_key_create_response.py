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


T = TypeVar("T", bound="ApiKeyCreateResponse")


@_attrs_define
class ApiKeyCreateResponse:
    """
    Attributes:
        id (UUID):
        key (str): The API key secret (shown only once)
        fingerprint (str): Non-secret key identifier (prefix and last four characters)
        name (str):
        scope (str): Privilege scope: 'full' or 'read_only' (#875)
        created_at (datetime.datetime):
        expires_at (datetime.datetime | None | Unset): Expiry timestamp; null means the key does not expire
    """

    id: UUID
    key: str
    fingerprint: str
    name: str
    scope: str
    created_at: datetime.datetime
    expires_at: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        key = self.key

        fingerprint = self.fingerprint

        name = self.name

        scope = self.scope

        created_at = self.created_at.isoformat()

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
                "key": key,
                "fingerprint": fingerprint,
                "name": name,
                "scope": scope,
                "created_at": created_at,
            }
        )
        if expires_at is not UNSET:
            field_dict["expires_at"] = expires_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        key = d.pop("key")

        fingerprint = d.pop("fingerprint")

        name = d.pop("name")

        scope = d.pop("scope")

        created_at = isoparse(d.pop("created_at"))

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

        api_key_create_response = cls(
            id=id,
            key=key,
            fingerprint=fingerprint,
            name=name,
            scope=scope,
            created_at=created_at,
            expires_at=expires_at,
        )

        api_key_create_response.additional_properties = d
        return api_key_create_response

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
