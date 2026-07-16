from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.share_token_request_expires_in_days_type_0 import (
    check_share_token_request_expires_in_days_type_0,
)
from ..models.share_token_request_expires_in_days_type_0 import (
    ShareTokenRequestExpiresInDaysType0,
)
from dateutil.parser import isoparse
from typing import cast
import datetime


T = TypeVar("T", bound="ShareTokenRequest")


@_attrs_define
class ShareTokenRequest:
    """
    Attributes:
        expires_at (datetime.datetime | None | Unset): Expiration timestamp; must carry a UTC offset. Null creates a
            non-expiring share link. A custom expiration requires advanced sharing controls.
        expires_in_days (None | ShareTokenRequestExpiresInDaysType0 | Unset): Server-calculated expiration preset.
            Choose 1, 7, 30, or 90 days.
    """

    expires_at: datetime.datetime | None | Unset = UNSET
    expires_in_days: None | ShareTokenRequestExpiresInDaysType0 | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        expires_at: None | str | Unset
        if isinstance(self.expires_at, Unset):
            expires_at = UNSET
        elif isinstance(self.expires_at, datetime.datetime):
            expires_at = self.expires_at.isoformat()
        else:
            expires_at = self.expires_at

        expires_in_days: int | None | Unset
        if isinstance(self.expires_in_days, Unset):
            expires_in_days = UNSET
        elif isinstance(self.expires_in_days, int):
            expires_in_days = self.expires_in_days
        else:
            expires_in_days = self.expires_in_days

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if expires_at is not UNSET:
            field_dict["expires_at"] = expires_at
        if expires_in_days is not UNSET:
            field_dict["expires_in_days"] = expires_in_days

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

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

        def _parse_expires_in_days(
            data: object,
        ) -> None | ShareTokenRequestExpiresInDaysType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, int):
                    raise TypeError()
                expires_in_days_type_0 = (
                    check_share_token_request_expires_in_days_type_0(data)
                )

                return expires_in_days_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | ShareTokenRequestExpiresInDaysType0 | Unset, data)

        expires_in_days = _parse_expires_in_days(d.pop("expires_in_days", UNSET))

        share_token_request = cls(
            expires_at=expires_at,
            expires_in_days=expires_in_days,
        )

        share_token_request.additional_properties = d
        return share_token_request

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
