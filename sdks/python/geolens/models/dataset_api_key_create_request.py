from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.dataset_api_key_create_request_scope import (
    check_dataset_api_key_create_request_scope,
)
from ..models.dataset_api_key_create_request_scope import (
    DatasetApiKeyCreateRequestScope,
)
from dateutil.parser import isoparse
import datetime


T = TypeVar("T", bound="DatasetApiKeyCreateRequest")


@_attrs_define
class DatasetApiKeyCreateRequest:
    """
    Attributes:
        name (str): Human-readable label for the API key
        expires_at (datetime.datetime): Expiry timestamp (RFC 3339, timezone-aware), in the future and at most 365 days
            away. Expired keys stop authenticating.
        scope (DatasetApiKeyCreateRequestScope | Unset): 'dataset_write' reads and writes the dataset's features.
            'dataset_append' only creates features, one or a FeatureCollection per request, and can't read, change or delete
            them. Default: 'dataset_write'.
    """

    name: str
    expires_at: datetime.datetime
    scope: DatasetApiKeyCreateRequestScope | Unset = "dataset_write"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        expires_at = self.expires_at.isoformat()

        scope: str | Unset = UNSET
        if not isinstance(self.scope, Unset):
            scope = self.scope

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
                "expires_at": expires_at,
            }
        )
        if scope is not UNSET:
            field_dict["scope"] = scope

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name")

        expires_at = isoparse(d.pop("expires_at"))

        _scope = d.pop("scope", UNSET)
        scope: DatasetApiKeyCreateRequestScope | Unset
        if isinstance(_scope, Unset):
            scope = UNSET
        else:
            scope = check_dataset_api_key_create_request_scope(_scope)

        dataset_api_key_create_request = cls(
            name=name,
            expires_at=expires_at,
            scope=scope,
        )

        dataset_api_key_create_request.additional_properties = d
        return dataset_api_key_create_request

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
