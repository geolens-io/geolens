from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.bar_chart_config_date_bucket_type_0 import BarChartConfigDateBucketType0
from ..models.bar_chart_config_date_bucket_type_0 import (
    check_bar_chart_config_date_bucket_type_0,
)
from ..models.bar_chart_config_mode import BarChartConfigMode
from ..models.bar_chart_config_mode import check_bar_chart_config_mode
from ..models.bar_chart_config_sort import BarChartConfigSort
from ..models.bar_chart_config_sort import check_bar_chart_config_sort
from ..models.bar_chart_config_stat import BarChartConfigStat
from ..models.bar_chart_config_stat import check_bar_chart_config_stat
from typing import cast


T = TypeVar("T", bound="BarChartConfig")


@_attrs_define
class BarChartConfig:
    """
    Attributes:
        mode (BarChartConfigMode | Unset): `category`: one bar per value of `column`. `by_feature`: one bar per feature,
            labelled by `label_column`, sized by `value_column`. `by_fields`: one bar per name in `fields`, each showing
            `stat` of that field. `date`: `column` grouped by `date_bucket`. Default: 'category'.
        column (None | str | Unset): The column whose values become bars (`category` and `date`).
        stat (BarChartConfigStat | Unset):  Default: 'count'.
        stat_column (None | str | Unset):
        limit (int | Unset):  Default: 10.
        label_column (None | str | Unset): `by_feature`: the field that labels each bar.
        value_column (None | str | Unset): `by_feature`: the numeric field that sizes each bar.
        sort (BarChartConfigSort | Unset): `by_feature`: bar order by value. Default: 'desc'.
        fields (list[str] | Unset): `by_fields`: the numeric fields to chart, one bar each.
        date_bucket (BarChartConfigDateBucketType0 | None | Unset): `date`: the span each bar covers.
        use_layer_colors (bool | Unset): `category`: colour bars as the layer does when `column` is its style column.
            Default: True.
    """

    mode: BarChartConfigMode | Unset = "category"
    column: None | str | Unset = UNSET
    stat: BarChartConfigStat | Unset = "count"
    stat_column: None | str | Unset = UNSET
    limit: int | Unset = 10
    label_column: None | str | Unset = UNSET
    value_column: None | str | Unset = UNSET
    sort: BarChartConfigSort | Unset = "desc"
    fields: list[str] | Unset = UNSET
    date_bucket: BarChartConfigDateBucketType0 | None | Unset = UNSET
    use_layer_colors: bool | Unset = True

    def to_dict(self) -> dict[str, Any]:
        mode: str | Unset = UNSET
        if not isinstance(self.mode, Unset):
            mode = self.mode

        column: None | str | Unset
        if isinstance(self.column, Unset):
            column = UNSET
        else:
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

        label_column: None | str | Unset
        if isinstance(self.label_column, Unset):
            label_column = UNSET
        else:
            label_column = self.label_column

        value_column: None | str | Unset
        if isinstance(self.value_column, Unset):
            value_column = UNSET
        else:
            value_column = self.value_column

        sort: str | Unset = UNSET
        if not isinstance(self.sort, Unset):
            sort = self.sort

        fields: list[str] | Unset = UNSET
        if not isinstance(self.fields, Unset):
            fields = self.fields

        date_bucket: None | str | Unset
        if isinstance(self.date_bucket, Unset):
            date_bucket = UNSET
        elif isinstance(self.date_bucket, str):
            date_bucket = self.date_bucket
        else:
            date_bucket = self.date_bucket

        use_layer_colors = self.use_layer_colors

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if mode is not UNSET:
            field_dict["mode"] = mode
        if column is not UNSET:
            field_dict["column"] = column
        if stat is not UNSET:
            field_dict["stat"] = stat
        if stat_column is not UNSET:
            field_dict["stat_column"] = stat_column
        if limit is not UNSET:
            field_dict["limit"] = limit
        if label_column is not UNSET:
            field_dict["label_column"] = label_column
        if value_column is not UNSET:
            field_dict["value_column"] = value_column
        if sort is not UNSET:
            field_dict["sort"] = sort
        if fields is not UNSET:
            field_dict["fields"] = fields
        if date_bucket is not UNSET:
            field_dict["date_bucket"] = date_bucket
        if use_layer_colors is not UNSET:
            field_dict["use_layer_colors"] = use_layer_colors

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        _mode = d.pop("mode", UNSET)
        mode: BarChartConfigMode | Unset
        if isinstance(_mode, Unset):
            mode = UNSET
        else:
            mode = check_bar_chart_config_mode(_mode)

        def _parse_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        column = _parse_column(d.pop("column", UNSET))

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

        def _parse_label_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        label_column = _parse_label_column(d.pop("label_column", UNSET))

        def _parse_value_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        value_column = _parse_value_column(d.pop("value_column", UNSET))

        _sort = d.pop("sort", UNSET)
        sort: BarChartConfigSort | Unset
        if isinstance(_sort, Unset):
            sort = UNSET
        else:
            sort = check_bar_chart_config_sort(_sort)

        fields = cast(list[str], d.pop("fields", UNSET))

        def _parse_date_bucket(
            data: object,
        ) -> BarChartConfigDateBucketType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                date_bucket_type_0 = check_bar_chart_config_date_bucket_type_0(data)

                return date_bucket_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(BarChartConfigDateBucketType0 | None | Unset, data)

        date_bucket = _parse_date_bucket(d.pop("date_bucket", UNSET))

        use_layer_colors = d.pop("use_layer_colors", UNSET)

        bar_chart_config = cls(
            mode=mode,
            column=column,
            stat=stat,
            stat_column=stat_column,
            limit=limit,
            label_column=label_column,
            value_column=value_column,
            sort=sort,
            fields=fields,
            date_bucket=date_bucket,
            use_layer_colors=use_layer_colors,
        )

        return bar_chart_config
