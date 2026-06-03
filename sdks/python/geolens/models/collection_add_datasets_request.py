from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from uuid import UUID


T = TypeVar("T", bound="CollectionAddDatasetsRequest")


@_attrs_define
class CollectionAddDatasetsRequest:
    """
    Attributes:
        dataset_ids (list[UUID]): Dataset IDs to add to the collection (1-100)
    """

    dataset_ids: list[UUID]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        dataset_ids = []
        for dataset_ids_item_data in self.dataset_ids:
            dataset_ids_item = str(dataset_ids_item_data)
            dataset_ids.append(dataset_ids_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dataset_ids": dataset_ids,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        dataset_ids = []
        _dataset_ids = d.pop("dataset_ids")
        for dataset_ids_item_data in _dataset_ids:
            dataset_ids_item = UUID(dataset_ids_item_data)

            dataset_ids.append(dataset_ids_item)

        collection_add_datasets_request = cls(
            dataset_ids=dataset_ids,
        )

        collection_add_datasets_request.additional_properties = d
        return collection_add_datasets_request

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
