from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="EmbedTokenCreate")


@_attrs_define
class EmbedTokenCreate:
    """
    Attributes:
        allowed_origins (list[str] | None | Unset): Restrict embedding to these origins (enterprise only). Omit to allow
            any origin. Example: ['https://dashboard.example.com'].
        expires_in_days (int | Unset): Token lifetime in days (1-365). Expiration controls are enterprise controls
            (enterprise only). Default: 30. Example: 90.
        name (None | str | Unset): Human-readable label for the token Example: Public dashboard embed.
    """

    allowed_origins: list[str] | None | Unset = UNSET
    expires_in_days: int | Unset = 30
    name: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        allowed_origins: list[str] | None | Unset
        if isinstance(self.allowed_origins, Unset):
            allowed_origins = UNSET
        elif isinstance(self.allowed_origins, list):
            allowed_origins = self.allowed_origins

        else:
            allowed_origins = self.allowed_origins

        expires_in_days = self.expires_in_days

        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if allowed_origins is not UNSET:
            field_dict["allowed_origins"] = allowed_origins
        if expires_in_days is not UNSET:
            field_dict["expires_in_days"] = expires_in_days
        if name is not UNSET:
            field_dict["name"] = name

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

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

        expires_in_days = d.pop("expires_in_days", UNSET)

        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))

        embed_token_create = cls(
            allowed_origins=allowed_origins,
            expires_in_days=expires_in_days,
            name=name,
        )

        embed_token_create.additional_properties = d
        return embed_token_create

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
