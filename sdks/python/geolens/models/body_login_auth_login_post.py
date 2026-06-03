from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="BodyLoginAuthLoginPost")


@_attrs_define
class BodyLoginAuthLoginPost:
    """
    Attributes:
        password (str):
        username (str):
        client_id (None | str | Unset):
        client_secret (None | str | Unset):
        grant_type (None | str | Unset):
        scope (str | Unset):  Default: ''.
    """

    password: str
    username: str
    client_id: None | str | Unset = UNSET
    client_secret: None | str | Unset = UNSET
    grant_type: None | str | Unset = UNSET
    scope: str | Unset = ""
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        password = self.password

        username = self.username

        client_id: None | str | Unset
        if isinstance(self.client_id, Unset):
            client_id = UNSET
        else:
            client_id = self.client_id

        client_secret: None | str | Unset
        if isinstance(self.client_secret, Unset):
            client_secret = UNSET
        else:
            client_secret = self.client_secret

        grant_type: None | str | Unset
        if isinstance(self.grant_type, Unset):
            grant_type = UNSET
        else:
            grant_type = self.grant_type

        scope = self.scope

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "password": password,
                "username": username,
            }
        )
        if client_id is not UNSET:
            field_dict["client_id"] = client_id
        if client_secret is not UNSET:
            field_dict["client_secret"] = client_secret
        if grant_type is not UNSET:
            field_dict["grant_type"] = grant_type
        if scope is not UNSET:
            field_dict["scope"] = scope

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        password = d.pop("password")

        username = d.pop("username")

        def _parse_client_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        client_id = _parse_client_id(d.pop("client_id", UNSET))

        def _parse_client_secret(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        client_secret = _parse_client_secret(d.pop("client_secret", UNSET))

        def _parse_grant_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        grant_type = _parse_grant_type(d.pop("grant_type", UNSET))

        scope = d.pop("scope", UNSET)

        body_login_auth_login_post = cls(
            password=password,
            username=username,
            client_id=client_id,
            client_secret=client_secret,
            grant_type=grant_type,
            scope=scope,
        )

        body_login_auth_login_post.additional_properties = d
        return body_login_auth_login_post

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
