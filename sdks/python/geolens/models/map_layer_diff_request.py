from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.map_layer_input import MapLayerInput
    from ..models.map_layer_patch import MapLayerPatch


T = TypeVar("T", bound="MapLayerDiffRequest")


@_attrs_define
class MapLayerDiffRequest:
    """
    Attributes:
        added (list[MapLayerInput] | Unset): Layers to append (max 200)
        fallback_full_replace (bool | Unset): Client hint only; PATCH never performs full replacement Default: False.
        order (list[UUID] | None | Unset): Optional stable layer ID order for existing layers
        removed (list[UUID] | Unset):
        updated (list[MapLayerPatch] | Unset):
    """

    added: list[MapLayerInput] | Unset = UNSET
    fallback_full_replace: bool | Unset = False
    order: list[UUID] | None | Unset = UNSET
    removed: list[UUID] | Unset = UNSET
    updated: list[MapLayerPatch] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        added: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.added, Unset):
            added = []
            for added_item_data in self.added:
                added_item = added_item_data.to_dict()
                added.append(added_item)

        fallback_full_replace = self.fallback_full_replace

        order: list[str] | None | Unset
        if isinstance(self.order, Unset):
            order = UNSET
        elif isinstance(self.order, list):
            order = []
            for order_type_0_item_data in self.order:
                order_type_0_item = str(order_type_0_item_data)
                order.append(order_type_0_item)

        else:
            order = self.order

        removed: list[str] | Unset = UNSET
        if not isinstance(self.removed, Unset):
            removed = []
            for removed_item_data in self.removed:
                removed_item = str(removed_item_data)
                removed.append(removed_item)

        updated: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.updated, Unset):
            updated = []
            for updated_item_data in self.updated:
                updated_item = updated_item_data.to_dict()
                updated.append(updated_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if added is not UNSET:
            field_dict["added"] = added
        if fallback_full_replace is not UNSET:
            field_dict["fallback_full_replace"] = fallback_full_replace
        if order is not UNSET:
            field_dict["order"] = order
        if removed is not UNSET:
            field_dict["removed"] = removed
        if updated is not UNSET:
            field_dict["updated"] = updated

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.map_layer_input import MapLayerInput
        from ..models.map_layer_patch import MapLayerPatch

        d = dict(src_dict)
        _added = d.pop("added", UNSET)
        added: list[MapLayerInput] | Unset = UNSET
        if _added is not UNSET:
            added = []
            for added_item_data in _added:
                added_item = MapLayerInput.from_dict(added_item_data)

                added.append(added_item)

        fallback_full_replace = d.pop("fallback_full_replace", UNSET)

        def _parse_order(data: object) -> list[UUID] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                order_type_0 = []
                _order_type_0 = data
                for order_type_0_item_data in _order_type_0:
                    order_type_0_item = UUID(order_type_0_item_data)

                    order_type_0.append(order_type_0_item)

                return order_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[UUID] | None | Unset, data)

        order = _parse_order(d.pop("order", UNSET))

        _removed = d.pop("removed", UNSET)
        removed: list[UUID] | Unset = UNSET
        if _removed is not UNSET:
            removed = []
            for removed_item_data in _removed:
                removed_item = UUID(removed_item_data)

                removed.append(removed_item)

        _updated = d.pop("updated", UNSET)
        updated: list[MapLayerPatch] | Unset = UNSET
        if _updated is not UNSET:
            updated = []
            for updated_item_data in _updated:
                updated_item = MapLayerPatch.from_dict(updated_item_data)

                updated.append(updated_item)

        map_layer_diff_request = cls(
            added=added,
            fallback_full_replace=fallback_full_replace,
            order=order,
            removed=removed,
            updated=updated,
        )

        map_layer_diff_request.additional_properties = d
        return map_layer_diff_request

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
