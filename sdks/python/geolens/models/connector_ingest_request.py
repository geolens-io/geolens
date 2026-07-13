from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.connector_ingest_request_config import ConnectorIngestRequestConfig


T = TypeVar("T", bound="ConnectorIngestRequest")


@_attrs_define
class ConnectorIngestRequest:
    """
    Attributes:
        resource_id (str): API-safe opaque handle returned by connector discovery.
        config (ConnectorIngestRequestConfig | Unset):
        credential_id (None | str | Unset):
    """

    resource_id: str
    config: ConnectorIngestRequestConfig | Unset = UNSET
    credential_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        resource_id = self.resource_id

        config: dict[str, Any] | Unset = UNSET
        if not isinstance(self.config, Unset):
            config = self.config.to_dict()

        credential_id: None | str | Unset
        if isinstance(self.credential_id, Unset):
            credential_id = UNSET
        else:
            credential_id = self.credential_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "resource_id": resource_id,
            }
        )
        if config is not UNSET:
            field_dict["config"] = config
        if credential_id is not UNSET:
            field_dict["credential_id"] = credential_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.connector_ingest_request_config import (
            ConnectorIngestRequestConfig,
        )

        d = dict(src_dict)
        resource_id = d.pop("resource_id")

        _config = d.pop("config", UNSET)
        config: ConnectorIngestRequestConfig | Unset
        if isinstance(_config, Unset):
            config = UNSET
        else:
            config = ConnectorIngestRequestConfig.from_dict(_config)

        def _parse_credential_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        credential_id = _parse_credential_id(d.pop("credential_id", UNSET))

        connector_ingest_request = cls(
            resource_id=resource_id,
            config=config,
            credential_id=credential_id,
        )

        connector_ingest_request.additional_properties = d
        return connector_ingest_request

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
