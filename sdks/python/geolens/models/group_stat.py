from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.group_stat_stat import check_group_stat_stat
from ..models.group_stat_stat import GroupStatStat
from typing import cast


T = TypeVar("T", bound="GroupStat")


@_attrs_define
class GroupStat:
    """
    Attributes:
        stat (GroupStatStat):
        column (None | str | Unset): The numeric column `stat` reads. Optional for `count`, which then counts rows, and
            otherwise counts the column's non-null values.
    """

    stat: GroupStatStat
    column: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        stat: str = self.stat

        column: None | str | Unset
        if isinstance(self.column, Unset):
            column = UNSET
        else:
            column = self.column

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "stat": stat,
            }
        )
        if column is not UNSET:
            field_dict["column"] = column

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        stat = check_group_stat_stat(d.pop("stat"))

        def _parse_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        column = _parse_column(d.pop("column", UNSET))

        group_stat = cls(
            stat=stat,
            column=column,
        )

        return group_stat
