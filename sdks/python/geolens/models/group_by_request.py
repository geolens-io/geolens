from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.group_by_request_stat import check_group_by_request_stat
from ..models.group_by_request_stat import GroupByRequestStat
from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.group_by_request_filter_type_0 import GroupByRequestFilterType0


T = TypeVar("T", bound="GroupByRequest")


@_attrs_define
class GroupByRequest:
    """
    Attributes:
        op (Literal['group_by']):
        group_column (str):
        stat (GroupByRequestStat):
        filter_ (GroupByRequestFilterType0 | None | Unset): CQL2-JSON filter, as the OGC API Features `filter` accepts.
        bbox (list[float] | None | Unset): Map view `[west, south, east, north]` in WGS 84; west greater than east
            crosses the antimeridian. Omit for the whole layer.
        column (None | str | Unset): The numeric column `stat` reads; omit for `count`.
        limit (int | Unset):  Default: 10.
    """

    op: Literal["group_by"]
    group_column: str
    stat: GroupByRequestStat
    filter_: GroupByRequestFilterType0 | None | Unset = UNSET
    bbox: list[float] | None | Unset = UNSET
    column: None | str | Unset = UNSET
    limit: int | Unset = 10

    def to_dict(self) -> dict[str, Any]:
        from ..models.group_by_request_filter_type_0 import GroupByRequestFilterType0

        op = self.op

        group_column = self.group_column

        stat: str = self.stat

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

        column: None | str | Unset
        if isinstance(self.column, Unset):
            column = UNSET
        else:
            column = self.column

        limit = self.limit

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "op": op,
                "group_column": group_column,
                "stat": stat,
            }
        )
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if column is not UNSET:
            field_dict["column"] = column
        if limit is not UNSET:
            field_dict["limit"] = limit

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.group_by_request_filter_type_0 import GroupByRequestFilterType0

        d = dict(src_dict)
        op = cast(Literal["group_by"], d.pop("op"))
        if op != "group_by":
            raise ValueError(f"op must match const 'group_by', got '{op}'")

        group_column = d.pop("group_column")

        stat = check_group_by_request_stat(d.pop("stat"))

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

        def _parse_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        column = _parse_column(d.pop("column", UNSET))

        limit = d.pop("limit", UNSET)

        group_by_request = cls(
            op=op,
            group_column=group_column,
            stat=stat,
            filter_=filter_,
            bbox=bbox,
            column=column,
            limit=limit,
        )

        return group_by_request
