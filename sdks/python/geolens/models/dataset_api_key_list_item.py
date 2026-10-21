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


T = TypeVar("T", bound="DatasetApiKeyListItem")


@_attrs_define
class DatasetApiKeyListItem:
    """
    Attributes:
        id (UUID):
        name (str):
        fingerprint (None | str): Non-secret key identifier; null for keys created before fingerprint support
        is_active (bool):
        scope (str): Privilege scope: 'full', 'read_only', 'publish' (reads, uploads, manifest apply, and metadata and
            map writes, but no deletes or feature writes), 'dataset_write' (reads and writes the features of the dataset in
            dataset_id, and nothing else), or 'dataset_append' (only creates features in that dataset)
        created_at (datetime.datetime):
        last_used_at (datetime.datetime | None):
        user_id (UUID): The user who minted the key; it acts as them
        username (str): That user's username
        expires_at (datetime.datetime | None | Unset): Expiry timestamp; null means the key does not expire
        dataset_id (None | Unset | UUID): The dataset a 'dataset_write' or 'dataset_append' key is bound to; null for
            other scopes
    """

    id: UUID
    name: str
    fingerprint: None | str
    is_active: bool
    scope: str
    created_at: datetime.datetime
    last_used_at: datetime.datetime | None
    user_id: UUID
    username: str
    expires_at: datetime.datetime | None | Unset = UNSET
    dataset_id: None | Unset | UUID = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

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

        user_id = str(self.user_id)

        username = self.username

        expires_at: None | str | Unset
        if isinstance(self.expires_at, Unset):
            expires_at = UNSET
        elif isinstance(self.expires_at, datetime.datetime):
            expires_at = self.expires_at.isoformat()
        else:
            expires_at = self.expires_at

        dataset_id: None | str | Unset
        if isinstance(self.dataset_id, Unset):
            dataset_id = UNSET
        elif isinstance(self.dataset_id, UUID):
            dataset_id = str(self.dataset_id)
        else:
            dataset_id = self.dataset_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "name": name,
                "fingerprint": fingerprint,
                "is_active": is_active,
                "scope": scope,
                "created_at": created_at,
                "last_used_at": last_used_at,
                "user_id": user_id,
                "username": username,
            }
        )
        if expires_at is not UNSET:
            field_dict["expires_at"] = expires_at
        if dataset_id is not UNSET:
            field_dict["dataset_id"] = dataset_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

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

        user_id = UUID(d.pop("user_id"))

        username = d.pop("username")

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

        def _parse_dataset_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                dataset_id_type_0 = UUID(data)

                return dataset_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        dataset_id = _parse_dataset_id(d.pop("dataset_id", UNSET))

        dataset_api_key_list_item = cls(
            id=id,
            name=name,
            fingerprint=fingerprint,
            is_active=is_active,
            scope=scope,
            created_at=created_at,
            last_used_at=last_used_at,
            user_id=user_id,
            username=username,
            expires_at=expires_at,
            dataset_id=dataset_id,
        )

        dataset_api_key_list_item.additional_properties = d
        return dataset_api_key_list_item

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
