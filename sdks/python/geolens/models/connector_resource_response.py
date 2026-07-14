from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


if TYPE_CHECKING:
    from ..models.connector_resource_response_metadata import (
        ConnectorResourceResponseMetadata,
    )


T = TypeVar("T", bound="ConnectorResourceResponse")


@_attrs_define
class ConnectorResourceResponse:
    """
    Attributes:
        id (str): API-safe opaque resource handle. This is never a provider URL, signed locator, or credential.
        kind (str):
        name (str):
        metadata (ConnectorResourceResponseMetadata | Unset):
    """

    id: str
    kind: str
    name: str
    metadata: ConnectorResourceResponseMetadata | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        kind = self.kind

        name = self.name

        metadata: dict[str, Any] | Unset = UNSET
        if not isinstance(self.metadata, Unset):
            metadata = self.metadata.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "kind": kind,
                "name": name,
            }
        )
        if metadata is not UNSET:
            field_dict["metadata"] = metadata

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.connector_resource_response_metadata import (
            ConnectorResourceResponseMetadata,
        )

        d = dict(src_dict)
        id = d.pop("id")

        kind = d.pop("kind")

        name = d.pop("name")

        _metadata = d.pop("metadata", UNSET)
        metadata: ConnectorResourceResponseMetadata | Unset
        if isinstance(_metadata, Unset):
            metadata = UNSET
        else:
            metadata = ConnectorResourceResponseMetadata.from_dict(_metadata)

        connector_resource_response = cls(
            id=id,
            kind=kind,
            name=name,
            metadata=metadata,
        )

        connector_resource_response.additional_properties = d
        return connector_resource_response

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
