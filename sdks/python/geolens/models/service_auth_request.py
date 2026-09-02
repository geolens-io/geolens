from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.service_auth_request_method import check_service_auth_request_method
from ..models.service_auth_request_method import ServiceAuthRequestMethod
from typing import cast


T = TypeVar("T", bound="ServiceAuthRequest")


@_attrs_define
class ServiceAuthRequest:
    """How one request authenticates to the remote service it names.

    Attributes:
        method (ServiceAuthRequestMethod): How the credential is presented to the remote service. Omit the whole auth
            object for a public service.
        token (None | str | Unset): Bearer token or API key, for method bearer.
        username (None | str | Unset): Username, for method basic.
        password (None | str | Unset): Password, for method basic.
        header_name (None | str | Unset): Name of the header the key is sent under, for method header.
        header_value (None | str | Unset): Value of the header the key is sent under, for method header.
    """

    method: ServiceAuthRequestMethod
    token: None | str | Unset = UNSET
    username: None | str | Unset = UNSET
    password: None | str | Unset = UNSET
    header_name: None | str | Unset = UNSET
    header_value: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        method: str = self.method

        token: None | str | Unset
        if isinstance(self.token, Unset):
            token = UNSET
        else:
            token = self.token

        username: None | str | Unset
        if isinstance(self.username, Unset):
            username = UNSET
        else:
            username = self.username

        password: None | str | Unset
        if isinstance(self.password, Unset):
            password = UNSET
        else:
            password = self.password

        header_name: None | str | Unset
        if isinstance(self.header_name, Unset):
            header_name = UNSET
        else:
            header_name = self.header_name

        header_value: None | str | Unset
        if isinstance(self.header_value, Unset):
            header_value = UNSET
        else:
            header_value = self.header_value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "method": method,
            }
        )
        if token is not UNSET:
            field_dict["token"] = token
        if username is not UNSET:
            field_dict["username"] = username
        if password is not UNSET:
            field_dict["password"] = password
        if header_name is not UNSET:
            field_dict["header_name"] = header_name
        if header_value is not UNSET:
            field_dict["header_value"] = header_value

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        method = check_service_auth_request_method(d.pop("method"))

        def _parse_token(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        token = _parse_token(d.pop("token", UNSET))

        def _parse_username(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        username = _parse_username(d.pop("username", UNSET))

        def _parse_password(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        password = _parse_password(d.pop("password", UNSET))

        def _parse_header_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        header_name = _parse_header_name(d.pop("header_name", UNSET))

        def _parse_header_value(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        header_value = _parse_header_value(d.pop("header_value", UNSET))

        service_auth_request = cls(
            method=method,
            token=token,
            username=username,
            password=password,
            header_name=header_name,
            header_value=header_value,
        )

        service_auth_request.additional_properties = d
        return service_auth_request

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
