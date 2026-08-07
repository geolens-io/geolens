from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


if TYPE_CHECKING:
    from ..models.connector_definition_response_config_schema import (
        ConnectorDefinitionResponseConfigSchema,
    )


T = TypeVar("T", bound="ConnectorDefinitionResponse")


@_attrs_define
class ConnectorDefinitionResponse:
    """Public, non-secret connector capabilities advertised by an overlay.

    Attributes:
        name (str):
        display_name (str):
        config_schema (ConnectorDefinitionResponseConfigSchema):
        supports_credentials (bool | Unset):  Default: False.
        supports_scheduled_sync (bool | Unset):  Default: False.
    """

    name: str
    display_name: str
    config_schema: ConnectorDefinitionResponseConfigSchema
    supports_credentials: bool | Unset = False
    supports_scheduled_sync: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        display_name = self.display_name

        config_schema = self.config_schema.to_dict()

        supports_credentials = self.supports_credentials

        supports_scheduled_sync = self.supports_scheduled_sync

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
                "display_name": display_name,
                "config_schema": config_schema,
            }
        )
        if supports_credentials is not UNSET:
            field_dict["supports_credentials"] = supports_credentials
        if supports_scheduled_sync is not UNSET:
            field_dict["supports_scheduled_sync"] = supports_scheduled_sync

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.connector_definition_response_config_schema import (
            ConnectorDefinitionResponseConfigSchema,
        )

        d = dict(src_dict)
        name = d.pop("name")

        display_name = d.pop("display_name")

        config_schema = ConnectorDefinitionResponseConfigSchema.from_dict(
            d.pop("config_schema")
        )

        supports_credentials = d.pop("supports_credentials", UNSET)

        supports_scheduled_sync = d.pop("supports_scheduled_sync", UNSET)

        connector_definition_response = cls(
            name=name,
            display_name=display_name,
            config_schema=config_schema,
            supports_credentials=supports_credentials,
            supports_scheduled_sync=supports_scheduled_sync,
        )

        connector_definition_response.additional_properties = d
        return connector_definition_response

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
