from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.table_config_sort import check_table_config_sort
from ..models.table_config_sort import TableConfigSort
from typing import cast

if TYPE_CHECKING:
    from ..models.table_stat import TableStat


T = TypeVar("T", bound="TableConfig")


@_attrs_define
class TableConfig:
    """
    Attributes:
        group_column (str):
        stats (list[TableStat]):
        sort_by (int | None | Unset): The index in `stats` of the statistic to sort by; leave it out to sort by the
            group value.
        sort (TableConfigSort | Unset):  Default: 'desc'.
        limit (int | Unset):  Default: 10.
    """

    group_column: str
    stats: list[TableStat]
    sort_by: int | None | Unset = UNSET
    sort: TableConfigSort | Unset = "desc"
    limit: int | Unset = 10

    def to_dict(self) -> dict[str, Any]:
        group_column = self.group_column

        stats = []
        for stats_item_data in self.stats:
            stats_item = stats_item_data.to_dict()
            stats.append(stats_item)

        sort_by: int | None | Unset
        if isinstance(self.sort_by, Unset):
            sort_by = UNSET
        else:
            sort_by = self.sort_by

        sort: str | Unset = UNSET
        if not isinstance(self.sort, Unset):
            sort = self.sort

        limit = self.limit

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "group_column": group_column,
                "stats": stats,
            }
        )
        if sort_by is not UNSET:
            field_dict["sort_by"] = sort_by
        if sort is not UNSET:
            field_dict["sort"] = sort
        if limit is not UNSET:
            field_dict["limit"] = limit

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.table_stat import TableStat

        d = dict(src_dict)
        group_column = d.pop("group_column")

        stats = []
        _stats = d.pop("stats")
        for stats_item_data in _stats:
            stats_item = TableStat.from_dict(stats_item_data)

            stats.append(stats_item)

        def _parse_sort_by(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        sort_by = _parse_sort_by(d.pop("sort_by", UNSET))

        _sort = d.pop("sort", UNSET)
        sort: TableConfigSort | Unset
        if isinstance(_sort, Unset):
            sort = UNSET
        else:
            sort = check_table_config_sort(_sort)

        limit = d.pop("limit", UNSET)

        table_config = cls(
            group_column=group_column,
            stats=stats,
            sort_by=sort_by,
            sort=sort,
            limit=limit,
        )

        return table_config
