from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.rows_request_sort import check_rows_request_sort
from ..models.rows_request_sort import RowsRequestSort
from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.rows_request_filter_type_0 import RowsRequestFilterType0


T = TypeVar("T", bound="RowsRequest")


@_attrs_define
class RowsRequest:
    """
    Attributes:
        op (Literal['rows']):
        columns (list[str]):
        filter_ (None | RowsRequestFilterType0 | Unset): CQL2-JSON filter, as the OGC API Features `filter` accepts.
        bbox (list[float] | None | Unset): Map view `[west, south, east, north]` in WGS 84; west greater than east
            crosses the antimeridian. Omit for the whole layer.
        sort_column (None | str | Unset): Order rows by this column with nulls last, then by gid; omit to order by gid.
        sort (RowsRequestSort | Unset):  Default: 'asc'.
        limit (int | Unset):  Default: 25.
        cursor (None | str | Unset): The previous page's `next_cursor`, under the same sort.
    """

    op: Literal["rows"]
    columns: list[str]
    filter_: None | RowsRequestFilterType0 | Unset = UNSET
    bbox: list[float] | None | Unset = UNSET
    sort_column: None | str | Unset = UNSET
    sort: RowsRequestSort | Unset = "asc"
    limit: int | Unset = 25
    cursor: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.rows_request_filter_type_0 import RowsRequestFilterType0

        op = self.op

        columns = self.columns

        filter_: dict[str, Any] | None | Unset
        if isinstance(self.filter_, Unset):
            filter_ = UNSET
        elif isinstance(self.filter_, RowsRequestFilterType0):
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

        sort_column: None | str | Unset
        if isinstance(self.sort_column, Unset):
            sort_column = UNSET
        else:
            sort_column = self.sort_column

        sort: str | Unset = UNSET
        if not isinstance(self.sort, Unset):
            sort = self.sort

        limit = self.limit

        cursor: None | str | Unset
        if isinstance(self.cursor, Unset):
            cursor = UNSET
        else:
            cursor = self.cursor

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "op": op,
                "columns": columns,
            }
        )
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if sort_column is not UNSET:
            field_dict["sort_column"] = sort_column
        if sort is not UNSET:
            field_dict["sort"] = sort
        if limit is not UNSET:
            field_dict["limit"] = limit
        if cursor is not UNSET:
            field_dict["cursor"] = cursor

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.rows_request_filter_type_0 import RowsRequestFilterType0

        d = dict(src_dict)
        op = cast(Literal["rows"], d.pop("op"))
        if op != "rows":
            raise ValueError(f"op must match const 'rows', got '{op}'")

        columns = cast(list[str], d.pop("columns"))

        def _parse_filter_(data: object) -> None | RowsRequestFilterType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                filter_type_0 = RowsRequestFilterType0.from_dict(data)

                return filter_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RowsRequestFilterType0 | Unset, data)

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

        def _parse_sort_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        sort_column = _parse_sort_column(d.pop("sort_column", UNSET))

        _sort = d.pop("sort", UNSET)
        sort: RowsRequestSort | Unset
        if isinstance(_sort, Unset):
            sort = UNSET
        else:
            sort = check_rows_request_sort(_sort)

        limit = d.pop("limit", UNSET)

        def _parse_cursor(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        cursor = _parse_cursor(d.pop("cursor", UNSET))

        rows_request = cls(
            op=op,
            columns=columns,
            filter_=filter_,
            bbox=bbox,
            sort_column=sort_column,
            sort=sort,
            limit=limit,
            cursor=cursor,
        )

        return rows_request
