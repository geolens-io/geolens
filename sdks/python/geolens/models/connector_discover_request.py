from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.connector_discover_request_config import (
        ConnectorDiscoverRequestConfig,
    )


T = TypeVar("T", bound="ConnectorDiscoverRequest")


@_attrs_define
class ConnectorDiscoverRequest:
    """
    Attributes:
        config (ConnectorDiscoverRequestConfig | Unset):
        credential_id (None | str | Unset):
    """

    config: ConnectorDiscoverRequestConfig | Unset = UNSET
    credential_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
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
        field_dict.update({})
        if config is not UNSET:
            field_dict["config"] = config
        if credential_id is not UNSET:
            field_dict["credential_id"] = credential_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.connector_discover_request_config import (
            ConnectorDiscoverRequestConfig,
        )

        d = dict(src_dict)
        _config = d.pop("config", UNSET)
        config: ConnectorDiscoverRequestConfig | Unset
        if isinstance(_config, Unset):
            config = UNSET
        else:
            config = ConnectorDiscoverRequestConfig.from_dict(_config)

        def _parse_credential_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        credential_id = _parse_credential_id(d.pop("credential_id", UNSET))

        connector_discover_request = cls(
            config=config,
            credential_id=credential_id,
        )

        connector_discover_request.additional_properties = d
        return connector_discover_request

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
