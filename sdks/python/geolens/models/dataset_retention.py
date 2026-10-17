from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="DatasetRetention")


@_attrs_define
class DatasetRetention:
    """Keep only the rows from the last `days` days, judged by `column`.

    Attributes:
        column (str): A date or timestamp column of the dataset's table. Rows where it is null are kept.
        days (int):
    """

    column: str
    days: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        column = self.column

        days = self.days

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "column": column,
                "days": days,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        column = d.pop("column")

        days = d.pop("days")

        dataset_retention = cls(
            column=column,
            days=days,
        )

        dataset_retention.additional_properties = d
        return dataset_retention

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
