from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.column_definition import ColumnDefinition


T = TypeVar("T", bound="CreateEmptyDatasetRequest")


@_attrs_define
class CreateEmptyDatasetRequest:
    """
    Attributes:
        title (str):
        columns (list[ColumnDefinition]):
    """

    title: str
    columns: list[ColumnDefinition]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        title = self.title

        columns = []
        for columns_item_data in self.columns:
            columns_item = columns_item_data.to_dict()
            columns.append(columns_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "title": title,
                "columns": columns,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.column_definition import ColumnDefinition

        d = dict(src_dict)
        title = d.pop("title")

        columns = []
        _columns = d.pop("columns")
        for columns_item_data in _columns:
            columns_item = ColumnDefinition.from_dict(columns_item_data)

            columns.append(columns_item)

        create_empty_dataset_request = cls(
            title=title,
            columns=columns,
        )

        create_empty_dataset_request.additional_properties = d
        return create_empty_dataset_request

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
