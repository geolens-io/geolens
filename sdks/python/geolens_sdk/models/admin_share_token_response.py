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


T = TypeVar("T", bound="AdminShareTokenResponse")


@_attrs_define
class AdminShareTokenResponse:
    """
    Attributes:
        created_at (datetime.datetime):
        created_by (None | str):
        expires_at (datetime.datetime | None):
        id (UUID):
        is_active (bool):
        map_id (UUID):
        map_name (str):
        token (str):
        embed_token_count (int | Unset):  Default: 0.
    """

    created_at: datetime.datetime
    created_by: None | str
    expires_at: datetime.datetime | None
    id: UUID
    is_active: bool
    map_id: UUID
    map_name: str
    token: str
    embed_token_count: int | Unset = 0
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        created_by: None | str
        created_by = self.created_by

        expires_at: None | str
        if isinstance(self.expires_at, datetime.datetime):
            expires_at = self.expires_at.isoformat()
        else:
            expires_at = self.expires_at

        id = str(self.id)

        is_active = self.is_active

        map_id = str(self.map_id)

        map_name = self.map_name

        token = self.token

        embed_token_count = self.embed_token_count

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "created_by": created_by,
                "expires_at": expires_at,
                "id": id,
                "is_active": is_active,
                "map_id": map_id,
                "map_name": map_name,
                "token": token,
            }
        )
        if embed_token_count is not UNSET:
            field_dict["embed_token_count"] = embed_token_count

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        def _parse_created_by(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_by = _parse_created_by(d.pop("created_by"))

        def _parse_expires_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                expires_at_type_0 = isoparse(data)

                return expires_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        expires_at = _parse_expires_at(d.pop("expires_at"))

        id = UUID(d.pop("id"))

        is_active = d.pop("is_active")

        map_id = UUID(d.pop("map_id"))

        map_name = d.pop("map_name")

        token = d.pop("token")

        embed_token_count = d.pop("embed_token_count", UNSET)

        admin_share_token_response = cls(
            created_at=created_at,
            created_by=created_by,
            expires_at=expires_at,
            id=id,
            is_active=is_active,
            map_id=map_id,
            map_name=map_name,
            token=token,
            embed_token_count=embed_token_count,
        )

        admin_share_token_response.additional_properties = d
        return admin_share_token_response

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
