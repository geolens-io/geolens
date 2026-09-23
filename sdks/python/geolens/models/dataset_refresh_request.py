from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.dataset_refresh_request_verification_policy import (
    check_dataset_refresh_request_verification_policy,
)
from ..models.dataset_refresh_request_verification_policy import (
    DatasetRefreshRequestVerificationPolicy,
)
from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.service_auth_request import ServiceAuthRequest


T = TypeVar("T", bound="DatasetRefreshRequest")


@_attrs_define
class DatasetRefreshRequest:
    """Body of a one-request refresh. Carries no source pointer.

    Everything about WHERE the data comes from is read server-side from the
    dataset's stored origin binding — that is the whole feature. A client
    cannot re-point a dataset through this door, and a client that has been
    shown the wrong URL cannot refresh from it.

        Attributes:
            token (None | str | Unset): Transient credential for a protected service. Used for this refresh only and never
                persisted: it is handed to the worker through a single-use, short-lived reference and is gone once claimed. A
                retry needs a new token. Deprecated: use the auth object with method bearer.
            verification_policy (DatasetRefreshRequestVerificationPolicy | Unset): Verification policy for this refresh.
                arcgis_id_set_v1 performs the stronger ArcGIS object-ID membership check. Default: 'standard'.
            accept_blocked_run_id (None | Unset | UUID): A blocked run whose reviewed source and staged content may be
                accepted. The refresh that uses the acceptance holds it until it ends, and a cancelled or failed refresh gives
                it back. A different result blocks again.
            auth (None | ServiceAuthRequest | Unset): Structured credential for a protected service. Mutually exclusive with
                the token field.
    """

    token: None | str | Unset = UNSET
    verification_policy: DatasetRefreshRequestVerificationPolicy | Unset = "standard"
    accept_blocked_run_id: None | Unset | UUID = UNSET
    auth: None | ServiceAuthRequest | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.service_auth_request import ServiceAuthRequest

        token: None | str | Unset
        if isinstance(self.token, Unset):
            token = UNSET
        else:
            token = self.token

        verification_policy: str | Unset = UNSET
        if not isinstance(self.verification_policy, Unset):
            verification_policy = self.verification_policy

        accept_blocked_run_id: None | str | Unset
        if isinstance(self.accept_blocked_run_id, Unset):
            accept_blocked_run_id = UNSET
        elif isinstance(self.accept_blocked_run_id, UUID):
            accept_blocked_run_id = str(self.accept_blocked_run_id)
        else:
            accept_blocked_run_id = self.accept_blocked_run_id

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
        if verification_policy is not UNSET:
            field_dict["verification_policy"] = verification_policy
        if accept_blocked_run_id is not UNSET:
            field_dict["accept_blocked_run_id"] = accept_blocked_run_id
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

        _verification_policy = d.pop("verification_policy", UNSET)
        verification_policy: DatasetRefreshRequestVerificationPolicy | Unset
        if isinstance(_verification_policy, Unset):
            verification_policy = UNSET
        else:
            verification_policy = check_dataset_refresh_request_verification_policy(
                _verification_policy
            )

        def _parse_accept_blocked_run_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                accept_blocked_run_id_type_0 = UUID(data)

                return accept_blocked_run_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        accept_blocked_run_id = _parse_accept_blocked_run_id(
            d.pop("accept_blocked_run_id", UNSET)
        )

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
            verification_policy=verification_policy,
            accept_blocked_run_id=accept_blocked_run_id,
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
