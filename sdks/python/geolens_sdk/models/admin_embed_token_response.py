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


T = TypeVar("T", bound="AdminEmbedTokenResponse")


@_attrs_define
class AdminEmbedTokenResponse:
    """
    Attributes:
        created_at (datetime.datetime):
        expires_at (datetime.datetime):
        id (UUID):
        is_active (bool):
        map_id (UUID):
        scoped_dataset_ids (list[str]):
        token_hint (str):
        allowed_origins (list[str] | None | Unset):
        creator_username (None | str | Unset):
        last_used_at (datetime.datetime | None | Unset):
        map_name (None | str | Unset):
        name (None | str | Unset):
        use_count (int | Unset):  Default: 0.
    """

    created_at: datetime.datetime
    expires_at: datetime.datetime
    id: UUID
    is_active: bool
    map_id: UUID
    scoped_dataset_ids: list[str]
    token_hint: str
    allowed_origins: list[str] | None | Unset = UNSET
    creator_username: None | str | Unset = UNSET
    last_used_at: datetime.datetime | None | Unset = UNSET
    map_name: None | str | Unset = UNSET
    name: None | str | Unset = UNSET
    use_count: int | Unset = 0
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        expires_at = self.expires_at.isoformat()

        id = str(self.id)

        is_active = self.is_active

        map_id = str(self.map_id)

        scoped_dataset_ids = self.scoped_dataset_ids

        token_hint = self.token_hint

        allowed_origins: list[str] | None | Unset
        if isinstance(self.allowed_origins, Unset):
            allowed_origins = UNSET
        elif isinstance(self.allowed_origins, list):
            allowed_origins = self.allowed_origins

        else:
            allowed_origins = self.allowed_origins

        creator_username: None | str | Unset
        if isinstance(self.creator_username, Unset):
            creator_username = UNSET
        else:
            creator_username = self.creator_username

        last_used_at: None | str | Unset
        if isinstance(self.last_used_at, Unset):
            last_used_at = UNSET
        elif isinstance(self.last_used_at, datetime.datetime):
            last_used_at = self.last_used_at.isoformat()
        else:
            last_used_at = self.last_used_at

        map_name: None | str | Unset
        if isinstance(self.map_name, Unset):
            map_name = UNSET
        else:
            map_name = self.map_name

        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        use_count = self.use_count

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "expires_at": expires_at,
                "id": id,
                "is_active": is_active,
                "map_id": map_id,
                "scoped_dataset_ids": scoped_dataset_ids,
                "token_hint": token_hint,
            }
        )
        if allowed_origins is not UNSET:
            field_dict["allowed_origins"] = allowed_origins
        if creator_username is not UNSET:
            field_dict["creator_username"] = creator_username
        if last_used_at is not UNSET:
            field_dict["last_used_at"] = last_used_at
        if map_name is not UNSET:
            field_dict["map_name"] = map_name
        if name is not UNSET:
            field_dict["name"] = name
        if use_count is not UNSET:
            field_dict["use_count"] = use_count

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        expires_at = isoparse(d.pop("expires_at"))

        id = UUID(d.pop("id"))

        is_active = d.pop("is_active")

        map_id = UUID(d.pop("map_id"))

        scoped_dataset_ids = cast(list[str], d.pop("scoped_dataset_ids"))

        token_hint = d.pop("token_hint")

        def _parse_allowed_origins(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                allowed_origins_type_0 = cast(list[str], data)

                return allowed_origins_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        allowed_origins = _parse_allowed_origins(d.pop("allowed_origins", UNSET))

        def _parse_creator_username(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        creator_username = _parse_creator_username(d.pop("creator_username", UNSET))

        def _parse_last_used_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_used_at_type_0 = isoparse(data)

                return last_used_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_used_at = _parse_last_used_at(d.pop("last_used_at", UNSET))

        def _parse_map_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        map_name = _parse_map_name(d.pop("map_name", UNSET))

        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))

        use_count = d.pop("use_count", UNSET)

        admin_embed_token_response = cls(
            created_at=created_at,
            expires_at=expires_at,
            id=id,
            is_active=is_active,
            map_id=map_id,
            scoped_dataset_ids=scoped_dataset_ids,
            token_hint=token_hint,
            allowed_origins=allowed_origins,
            creator_username=creator_username,
            last_used_at=last_used_at,
            map_name=map_name,
            name=name,
            use_count=use_count,
        )

        admin_embed_token_response.additional_properties = d
        return admin_embed_token_response

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
