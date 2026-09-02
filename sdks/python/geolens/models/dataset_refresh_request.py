from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.service_auth_request import ServiceAuthRequest


T = TypeVar("T", bound="DatasetRefreshRequest")


@_attrs_define
class DatasetRefreshRequest:
    """Body of a one-request refresh (#1220). Carries no source pointer.

    Everything about WHERE the data comes from is read server-side from the
    dataset's stored origin binding — that is the whole feature. A client
    cannot re-point a dataset through this door, and a client that has been
    shown the wrong URL cannot refresh from it.

        Attributes:
            token (None | str | Unset): Transient credential for a protected service. Used for this refresh only and never
                persisted: it is handed to the worker through a single-use, short-lived reference and is gone once claimed. A
                retry needs a new token. Deprecated: use the auth object with method bearer.
            auth (None | ServiceAuthRequest | Unset): Structured credential for a protected service. Mutually exclusive with
                the token field.
    """

    token: None | str | Unset = UNSET
    auth: None | ServiceAuthRequest | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.service_auth_request import ServiceAuthRequest

        token: None | str | Unset
        if isinstance(self.token, Unset):
            token = UNSET
        else:
            token = self.token

        auth: dict[str, Any] | None | Unset
        if isinstance(self.auth, Unset):
            auth = UNSET
        elif isinstance(self.auth, ServiceAuthRequest):
            auth = self.auth.to_dict()
        else:
            auth = self.auth

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if token is not UNSET:
            field_dict["token"] = token
        if auth is not UNSET:
            field_dict["auth"] = auth

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.service_auth_request import ServiceAuthRequest

        d = dict(src_dict)

        def _parse_token(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        token = _parse_token(d.pop("token", UNSET))

        def _parse_auth(data: object) -> None | ServiceAuthRequest | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                auth_type_0 = ServiceAuthRequest.from_dict(data)

                return auth_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | ServiceAuthRequest | Unset, data)

        auth = _parse_auth(d.pop("auth", UNSET))

        dataset_refresh_request = cls(
            token=token,
            auth=auth,
        )

        dataset_refresh_request.additional_properties = d
        return dataset_refresh_request

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
