from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from uuid import UUID


T = TypeVar("T", bound="BulkDeleteLayersRequest")


@_attrs_define
class BulkDeleteLayersRequest:
    """Request body for POST /maps/{map_id}/layers/bulk-delete.

    Attributes:
        layer_ids (list[UUID]): UUIDs of layers to delete. Must be 1–200 elements (matches _MAX_LAYERS_PER_MAP).
    """

    layer_ids: list[UUID]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        layer_ids = []
        for layer_ids_item_data in self.layer_ids:
            layer_ids_item = str(layer_ids_item_data)
            layer_ids.append(layer_ids_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "layer_ids": layer_ids,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        layer_ids = []
        _layer_ids = d.pop("layer_ids")
        for layer_ids_item_data in _layer_ids:
            layer_ids_item = UUID(layer_ids_item_data)

            layer_ids.append(layer_ids_item)

        bulk_delete_layers_request = cls(
            layer_ids=layer_ids,
        )

        bulk_delete_layers_request.additional_properties = d
        return bulk_delete_layers_request

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
