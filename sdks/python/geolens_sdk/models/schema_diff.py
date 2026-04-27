from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast

if TYPE_CHECKING:
    from ..models.column_change import ColumnChange
    from ..models.type_change import TypeChange


T = TypeVar("T", bound="SchemaDiff")


@_attrs_define
class SchemaDiff:
    """
    Attributes:
        columns_added (list[ColumnChange]): Columns present in new but not old schema
        columns_removed (list[ColumnChange]): Columns present in old but not new schema
        row_count_delta (int): row_count_new minus row_count_old
        row_count_new (int | None):
        row_count_old (int | None):
        type_changes (list[TypeChange]): Columns whose data type changed
    """

    columns_added: list[ColumnChange]
    columns_removed: list[ColumnChange]
    row_count_delta: int
    row_count_new: int | None
    row_count_old: int | None
    type_changes: list[TypeChange]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        columns_added = []
        for columns_added_item_data in self.columns_added:
            columns_added_item = columns_added_item_data.to_dict()
            columns_added.append(columns_added_item)

        columns_removed = []
        for columns_removed_item_data in self.columns_removed:
            columns_removed_item = columns_removed_item_data.to_dict()
            columns_removed.append(columns_removed_item)

        row_count_delta = self.row_count_delta

        row_count_new: int | None
        row_count_new = self.row_count_new

        row_count_old: int | None
        row_count_old = self.row_count_old

        type_changes = []
        for type_changes_item_data in self.type_changes:
            type_changes_item = type_changes_item_data.to_dict()
            type_changes.append(type_changes_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "columns_added": columns_added,
                "columns_removed": columns_removed,
                "row_count_delta": row_count_delta,
                "row_count_new": row_count_new,
                "row_count_old": row_count_old,
                "type_changes": type_changes,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.column_change import ColumnChange
        from ..models.type_change import TypeChange

        d = dict(src_dict)
        columns_added = []
        _columns_added = d.pop("columns_added")
        for columns_added_item_data in _columns_added:
            columns_added_item = ColumnChange.from_dict(columns_added_item_data)

            columns_added.append(columns_added_item)

        columns_removed = []
        _columns_removed = d.pop("columns_removed")
        for columns_removed_item_data in _columns_removed:
            columns_removed_item = ColumnChange.from_dict(columns_removed_item_data)

            columns_removed.append(columns_removed_item)

        row_count_delta = d.pop("row_count_delta")

        def _parse_row_count_new(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        row_count_new = _parse_row_count_new(d.pop("row_count_new"))

        def _parse_row_count_old(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        row_count_old = _parse_row_count_old(d.pop("row_count_old"))

        type_changes = []
        _type_changes = d.pop("type_changes")
        for type_changes_item_data in _type_changes:
            type_changes_item = TypeChange.from_dict(type_changes_item_data)

            type_changes.append(type_changes_item)

        schema_diff = cls(
            columns_added=columns_added,
            columns_removed=columns_removed,
            row_count_delta=row_count_delta,
            row_count_new=row_count_new,
            row_count_old=row_count_old,
            type_changes=type_changes,
        )

        schema_diff.additional_properties = d
        return schema_diff

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
