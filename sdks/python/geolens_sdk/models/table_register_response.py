from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from uuid import UUID


T = TypeVar("T", bound="TableRegisterResponse")


@_attrs_define
class TableRegisterResponse:
    """
    Attributes:
        dataset_id (UUID): Identifier of the newly registered dataset.
        table_name (str): Source PostgreSQL table that was registered.
        title (str): Title of the registered dataset.
    """

    dataset_id: UUID
    table_name: str
    title: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        dataset_id = str(self.dataset_id)

        table_name = self.table_name

        title = self.title

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dataset_id": dataset_id,
                "table_name": table_name,
                "title": title,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        dataset_id = UUID(d.pop("dataset_id"))

        table_name = d.pop("table_name")

        title = d.pop("title")

        table_register_response = cls(
            dataset_id=dataset_id,
            table_name=table_name,
            title=title,
        )

        table_register_response.additional_properties = d
        return table_register_response

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
