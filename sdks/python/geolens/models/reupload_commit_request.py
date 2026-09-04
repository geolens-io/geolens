from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.reupload_commit_request_expected_origin_kind_type_0 import (
    check_reupload_commit_request_expected_origin_kind_type_0,
)
from ..models.reupload_commit_request_expected_origin_kind_type_0 import (
    ReuploadCommitRequestExpectedOriginKindType0,
)
from typing import cast

if TYPE_CHECKING:
    from ..models.service_auth_request import ServiceAuthRequest


T = TypeVar("T", bound="ReuploadCommitRequest")


@_attrs_define
class ReuploadCommitRequest:
    """
    Attributes:
        srid_override (int | None | Unset):
        expected_origin_kind (None | ReuploadCommitRequestExpectedOriginKindType0 | Unset): The dataset origin the
            client saw when it staged this replacement. When set, the commit is refused with 409 `origin_changed` if the
            dataset's origin no longer matches, so a service, STAC or registered-table binding established after the upload
            is not silently rebound to an upload. Optional: a client that omits it keeps the pre-#1768 behaviour.
        token (None | str | Unset): Deprecated: use the auth object with method bearer.
        layer_name (None | str | Unset):
        auth (None | ServiceAuthRequest | Unset): Structured credential for a protected service. Mutually exclusive with
            the token field.
    """

    srid_override: int | None | Unset = UNSET
    expected_origin_kind: (
        None | ReuploadCommitRequestExpectedOriginKindType0 | Unset
    ) = UNSET
    token: None | str | Unset = UNSET
    layer_name: None | str | Unset = UNSET
    auth: None | ServiceAuthRequest | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.service_auth_request import ServiceAuthRequest

        srid_override: int | None | Unset
        if isinstance(self.srid_override, Unset):
            srid_override = UNSET
        else:
            srid_override = self.srid_override

        expected_origin_kind: None | str | Unset
        if isinstance(self.expected_origin_kind, Unset):
            expected_origin_kind = UNSET
        elif isinstance(self.expected_origin_kind, str):
            expected_origin_kind = self.expected_origin_kind
        else:
            expected_origin_kind = self.expected_origin_kind

        token: None | str | Unset
        if isinstance(self.token, Unset):
            token = UNSET
        else:
            token = self.token

        layer_name: None | str | Unset
        if isinstance(self.layer_name, Unset):
            layer_name = UNSET
        else:
            layer_name = self.layer_name

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
        if srid_override is not UNSET:
            field_dict["srid_override"] = srid_override
        if expected_origin_kind is not UNSET:
            field_dict["expected_origin_kind"] = expected_origin_kind
        if token is not UNSET:
            field_dict["token"] = token
        if layer_name is not UNSET:
            field_dict["layer_name"] = layer_name
        if auth is not UNSET:
            field_dict["auth"] = auth

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.service_auth_request import ServiceAuthRequest

        d = dict(src_dict)

        def _parse_srid_override(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        srid_override = _parse_srid_override(d.pop("srid_override", UNSET))

        def _parse_expected_origin_kind(
            data: object,
        ) -> None | ReuploadCommitRequestExpectedOriginKindType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                expected_origin_kind_type_0 = (
                    check_reupload_commit_request_expected_origin_kind_type_0(data)
                )

                return expected_origin_kind_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                None | ReuploadCommitRequestExpectedOriginKindType0 | Unset, data
            )

        expected_origin_kind = _parse_expected_origin_kind(
            d.pop("expected_origin_kind", UNSET)
        )

        def _parse_token(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        token = _parse_token(d.pop("token", UNSET))

        def _parse_layer_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        layer_name = _parse_layer_name(d.pop("layer_name", UNSET))

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

        reupload_commit_request = cls(
            srid_override=srid_override,
            expected_origin_kind=expected_origin_kind,
            token=token,
            layer_name=layer_name,
            auth=auth,
        )

        reupload_commit_request.additional_properties = d
        return reupload_commit_request

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
