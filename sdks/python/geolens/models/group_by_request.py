from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.group_by_request_date_bucket_type_0 import (
    check_group_by_request_date_bucket_type_0,
)
from ..models.group_by_request_date_bucket_type_0 import GroupByRequestDateBucketType0
from ..models.group_by_request_sort_type_0 import check_group_by_request_sort_type_0
from ..models.group_by_request_sort_type_0 import GroupByRequestSortType0
from ..models.group_by_request_stat_type_0 import check_group_by_request_stat_type_0
from ..models.group_by_request_stat_type_0 import GroupByRequestStatType0
from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.group_by_request_filter_type_0 import GroupByRequestFilterType0
    from ..models.group_stat import GroupStat


T = TypeVar("T", bound="GroupByRequest")


@_attrs_define
class GroupByRequest:
    """
    Attributes:
        op (Literal['group_by']):
        group_column (str):
        filter_ (GroupByRequestFilterType0 | None | Unset): CQL2-JSON filter, as the OGC API Features `filter` accepts.
        bbox (list[float] | None | Unset): Map view `[west, south, east, north]` in WGS 84; west greater than east
            crosses the antimeridian. Omit for the whole layer.
        stat (GroupByRequestStatType0 | None | Unset): One statistic; or give `stats`.
        column (None | str | Unset): The numeric column `stat` reads; omit for `count`.
        stats (list[GroupStat] | None | Unset): Statistics returned as each group's `values`, in this order.
        date_bucket (GroupByRequestDateBucketType0 | None | Unset): Group a date or timestamp column by the UTC day,
            Monday-first week, month or year it falls in.
        sort_by (int | Literal['group'] | None | Unset): Order and keep groups by a statistic's index in `stats` (0 with
            `stat`) or by `group`. Defaults to the first statistic, or to the group with `date_bucket`.
        sort (GroupByRequestSortType0 | None | Unset): Defaults to `desc`, or `asc` with `date_bucket`.
        limit (int | Unset):  Default: 10.
        blank_text_as_null (bool | Unset): Count a text column's empty strings with its NULLs, as one `null` key, before
            the groups are limited. Whitespace-only text keeps its own key. Default: False.
    """

    op: Literal["group_by"]
    group_column: str
    filter_: GroupByRequestFilterType0 | None | Unset = UNSET
    bbox: list[float] | None | Unset = UNSET
    stat: GroupByRequestStatType0 | None | Unset = UNSET
    column: None | str | Unset = UNSET
    stats: list[GroupStat] | None | Unset = UNSET
    date_bucket: GroupByRequestDateBucketType0 | None | Unset = UNSET
    sort_by: int | Literal["group"] | None | Unset = UNSET
    sort: GroupByRequestSortType0 | None | Unset = UNSET
    limit: int | Unset = 10
    blank_text_as_null: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        from ..models.group_by_request_filter_type_0 import GroupByRequestFilterType0

        op = self.op

        group_column = self.group_column

        filter_: dict[str, Any] | None | Unset
        if isinstance(self.filter_, Unset):
            filter_ = UNSET
        elif isinstance(self.filter_, GroupByRequestFilterType0):
            filter_ = self.filter_.to_dict()
        else:
            filter_ = self.filter_

        bbox: list[float] | None | Unset
        if isinstance(self.bbox, Unset):
            bbox = UNSET
        elif isinstance(self.bbox, list):
            bbox = self.bbox

        else:
            bbox = self.bbox

        stat: None | str | Unset
        if isinstance(self.stat, Unset):
            stat = UNSET
        elif isinstance(self.stat, str):
            stat = self.stat
        else:
            stat = self.stat

        column: None | str | Unset
        if isinstance(self.column, Unset):
            column = UNSET
        else:
            column = self.column

        stats: list[dict[str, Any]] | None | Unset
        if isinstance(self.stats, Unset):
            stats = UNSET
        elif isinstance(self.stats, list):
            stats = []
            for stats_type_0_item_data in self.stats:
                stats_type_0_item = stats_type_0_item_data.to_dict()
                stats.append(stats_type_0_item)

        else:
            stats = self.stats

        date_bucket: None | str | Unset
        if isinstance(self.date_bucket, Unset):
            date_bucket = UNSET
        elif isinstance(self.date_bucket, str):
            date_bucket = self.date_bucket
        else:
            date_bucket = self.date_bucket

        sort_by: int | Literal["group"] | None | Unset
        if isinstance(self.sort_by, Unset):
            sort_by = UNSET
        else:
            sort_by = self.sort_by

        sort: None | str | Unset
        if isinstance(self.sort, Unset):
            sort = UNSET
        elif isinstance(self.sort, str):
            sort = self.sort
        else:
            sort = self.sort

        limit = self.limit

        blank_text_as_null = self.blank_text_as_null

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "op": op,
                "group_column": group_column,
            }
        )
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if stat is not UNSET:
            field_dict["stat"] = stat
        if column is not UNSET:
            field_dict["column"] = column
        if stats is not UNSET:
            field_dict["stats"] = stats
        if date_bucket is not UNSET:
            field_dict["date_bucket"] = date_bucket
        if sort_by is not UNSET:
            field_dict["sort_by"] = sort_by
        if sort is not UNSET:
            field_dict["sort"] = sort
        if limit is not UNSET:
            field_dict["limit"] = limit
        if blank_text_as_null is not UNSET:
            field_dict["blank_text_as_null"] = blank_text_as_null

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.group_by_request_filter_type_0 import GroupByRequestFilterType0
        from ..models.group_stat import GroupStat

        d = dict(src_dict)
        op = cast(Literal["group_by"], d.pop("op"))
        if op != "group_by":
            raise ValueError(f"op must match const 'group_by', got '{op}'")

        group_column = d.pop("group_column")

        def _parse_filter_(data: object) -> GroupByRequestFilterType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                filter_type_0 = GroupByRequestFilterType0.from_dict(data)

                return filter_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(GroupByRequestFilterType0 | None | Unset, data)

        filter_ = _parse_filter_(d.pop("filter", UNSET))

        def _parse_bbox(data: object) -> list[float] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                bbox_type_0 = cast(list[float], data)

                return bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None | Unset, data)

        bbox = _parse_bbox(d.pop("bbox", UNSET))

        def _parse_stat(data: object) -> GroupByRequestStatType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                stat_type_0 = check_group_by_request_stat_type_0(data)

                return stat_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(GroupByRequestStatType0 | None | Unset, data)

        stat = _parse_stat(d.pop("stat", UNSET))

        def _parse_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        column = _parse_column(d.pop("column", UNSET))

        def _parse_stats(data: object) -> list[GroupStat] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                stats_type_0 = []
                _stats_type_0 = data
                for stats_type_0_item_data in _stats_type_0:
                    stats_type_0_item = GroupStat.from_dict(stats_type_0_item_data)

                    stats_type_0.append(stats_type_0_item)

                return stats_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[GroupStat] | None | Unset, data)

        stats = _parse_stats(d.pop("stats", UNSET))

        def _parse_date_bucket(
            data: object,
        ) -> GroupByRequestDateBucketType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                date_bucket_type_0 = check_group_by_request_date_bucket_type_0(data)

                return date_bucket_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(GroupByRequestDateBucketType0 | None | Unset, data)

        date_bucket = _parse_date_bucket(d.pop("date_bucket", UNSET))

        def _parse_sort_by(data: object) -> int | Literal["group"] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            sort_by_type_0 = cast(Literal["group"], data)
            if sort_by_type_0 != "group":
                raise ValueError(
                    f"sort_by_type_0 must match const 'group', got '{sort_by_type_0}'"
                )
            return sort_by_type_0
            return cast(int | Literal["group"] | None | Unset, data)

        sort_by = _parse_sort_by(d.pop("sort_by", UNSET))

        def _parse_sort(data: object) -> GroupByRequestSortType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                sort_type_0 = check_group_by_request_sort_type_0(data)

                return sort_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(GroupByRequestSortType0 | None | Unset, data)

        sort = _parse_sort(d.pop("sort", UNSET))

        limit = d.pop("limit", UNSET)

        blank_text_as_null = d.pop("blank_text_as_null", UNSET)

        group_by_request = cls(
            op=op,
            group_column=group_column,
            filter_=filter_,
            bbox=bbox,
            stat=stat,
            column=column,
            stats=stats,
            date_bucket=date_bucket,
            sort_by=sort_by,
            sort=sort,
            limit=limit,
            blank_text_as_null=blank_text_as_null,
        )

        return group_by_request
