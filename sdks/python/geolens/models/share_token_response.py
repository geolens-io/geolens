from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
import datetime


T = TypeVar("T", bound="ShareTokenResponse")


@_attrs_define
class ShareTokenResponse:
    """
    Attributes:
        token (str): Raw token on create, hint on retrieve
        expires_at (datetime.datetime | None | Unset):
        is_active (bool | Unset):  Default: True.
        share_url (None | str | Unset): Full shareable URL — only returned on create
    """

    token: str
    expires_at: datetime.datetime | None | Unset = UNSET
    is_active: bool | Unset = True
    share_url: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        token = self.token

        expires_at: None | str | Unset
        if isinstance(self.expires_at, Unset):
            expires_at = UNSET
        elif isinstance(self.expires_at, datetime.datetime):
            expires_at = self.expires_at.isoformat()
        else:
            expires_at = self.expires_at

        is_active = self.is_active

        share_url: None | str | Unset
        if isinstance(self.share_url, Unset):
            share_url = UNSET
        else:
            share_url = self.share_url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "token": token,
            }
        )
        if expires_at is not UNSET:
            field_dict["expires_at"] = expires_at
        if is_active is not UNSET:
            field_dict["is_active"] = is_active
        if share_url is not UNSET:
            field_dict["share_url"] = share_url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        token = d.pop("token")

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

        is_active = d.pop("is_active", UNSET)

        def _parse_share_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        share_url = _parse_share_url(d.pop("share_url", UNSET))

        share_token_response = cls(
            token=token,
            expires_at=expires_at,
            is_active=is_active,
            share_url=share_url,
        )

        share_token_response.additional_properties = d
        return share_token_response

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
