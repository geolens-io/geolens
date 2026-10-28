from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.bar_chart_config_stat import BarChartConfigStat
from ..models.bar_chart_config_stat import check_bar_chart_config_stat
from typing import cast


T = TypeVar("T", bound="BarChartConfig")


@_attrs_define
class BarChartConfig:
    """
    Attributes:
        column (str): The column whose values become bars.
        stat (BarChartConfigStat | Unset):  Default: 'count'.
        stat_column (None | str | Unset):
        limit (int | Unset):  Default: 10.
    """

    column: str
    stat: BarChartConfigStat | Unset = "count"
    stat_column: None | str | Unset = UNSET
    limit: int | Unset = 10

    def to_dict(self) -> dict[str, Any]:
        column = self.column

        stat: str | Unset = UNSET
        if not isinstance(self.stat, Unset):
            stat = self.stat

        stat_column: None | str | Unset
        if isinstance(self.stat_column, Unset):
            stat_column = UNSET
        else:
            stat_column = self.stat_column

        limit = self.limit

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "column": column,
            }
        )
        if stat is not UNSET:
            field_dict["stat"] = stat
        if stat_column is not UNSET:
            field_dict["stat_column"] = stat_column
        if limit is not UNSET:
            field_dict["limit"] = limit

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        column = d.pop("column")

        _stat = d.pop("stat", UNSET)
        stat: BarChartConfigStat | Unset
        if isinstance(_stat, Unset):
            stat = UNSET
        else:
            stat = check_bar_chart_config_stat(_stat)

        def _parse_stat_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        stat_column = _parse_stat_column(d.pop("stat_column", UNSET))

        limit = d.pop("limit", UNSET)

        bar_chart_config = cls(
            column=column,
            stat=stat,
            stat_column=stat_column,
            limit=limit,
        )

        return bar_chart_config
