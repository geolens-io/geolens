from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from uuid import UUID


T = TypeVar("T", bound="MapLayerAccessGap")


@_attrs_define
class MapLayerAccessGap:
    """
    Attributes:
        layer_id (UUID):
        layer_title (str):
        dataset_id (UUID):
        dataset_title (str):
        group_ids (list[UUID]): The map's groups that have a member who can't read it.
        can_share (bool): Whether `confirm: share_datasets` would share the dataset with those groups.
    """

    layer_id: UUID
    layer_title: str
    dataset_id: UUID
    dataset_title: str
    group_ids: list[UUID]
    can_share: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        layer_id = str(self.layer_id)

        layer_title = self.layer_title

        dataset_id = str(self.dataset_id)

        dataset_title = self.dataset_title

        group_ids = []
        for group_ids_item_data in self.group_ids:
            group_ids_item = str(group_ids_item_data)
            group_ids.append(group_ids_item)

        can_share = self.can_share

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "layer_id": layer_id,
                "layer_title": layer_title,
                "dataset_id": dataset_id,
                "dataset_title": dataset_title,
                "group_ids": group_ids,
                "can_share": can_share,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        layer_id = UUID(d.pop("layer_id"))

        layer_title = d.pop("layer_title")

        dataset_id = UUID(d.pop("dataset_id"))

        dataset_title = d.pop("dataset_title")

        group_ids = []
        _group_ids = d.pop("group_ids")
        for group_ids_item_data in _group_ids:
            group_ids_item = UUID(group_ids_item_data)

            group_ids.append(group_ids_item)

        can_share = d.pop("can_share")

        map_layer_access_gap = cls(
            layer_id=layer_id,
            layer_title=layer_title,
            dataset_id=dataset_id,
            dataset_title=dataset_title,
            group_ids=group_ids,
            can_share=can_share,
        )

        map_layer_access_gap.additional_properties = d
        return map_layer_access_gap

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
