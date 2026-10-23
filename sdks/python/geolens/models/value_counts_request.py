from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.value_counts_request_filter_type_0 import (
        ValueCountsRequestFilterType0,
    )


T = TypeVar("T", bound="ValueCountsRequest")


@_attrs_define
class ValueCountsRequest:
    """
    Attributes:
        op (Literal['value_counts']):
        column (str):
        filter_ (None | Unset | ValueCountsRequestFilterType0): CQL2-JSON filter, as the OGC API Features `filter`
            accepts.
        bbox (list[float] | None | Unset): Map view `[west, south, east, north]` in WGS 84; west greater than east
            crosses the antimeridian. Omit for the whole layer.
        limit (int | Unset):  Default: 10.
    """

    op: Literal["value_counts"]
    column: str
    filter_: None | Unset | ValueCountsRequestFilterType0 = UNSET
    bbox: list[float] | None | Unset = UNSET
    limit: int | Unset = 10

    def to_dict(self) -> dict[str, Any]:
        from ..models.value_counts_request_filter_type_0 import (
            ValueCountsRequestFilterType0,
        )

        op = self.op

        column = self.column

        filter_: dict[str, Any] | None | Unset
        if isinstance(self.filter_, Unset):
            filter_ = UNSET
        elif isinstance(self.filter_, ValueCountsRequestFilterType0):
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

        limit = self.limit

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "op": op,
                "column": column,
            }
        )
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if limit is not UNSET:
            field_dict["limit"] = limit

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.value_counts_request_filter_type_0 import (
            ValueCountsRequestFilterType0,
        )

        d = dict(src_dict)
        op = cast(Literal["value_counts"], d.pop("op"))
        if op != "value_counts":
            raise ValueError(f"op must match const 'value_counts', got '{op}'")

        column = d.pop("column")

        def _parse_filter_(
            data: object,
        ) -> None | Unset | ValueCountsRequestFilterType0:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                filter_type_0 = ValueCountsRequestFilterType0.from_dict(data)

                return filter_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | ValueCountsRequestFilterType0, data)

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

        limit = d.pop("limit", UNSET)

        value_counts_request = cls(
            op=op,
            column=column,
            filter_=filter_,
            bbox=bbox,
            limit=limit,
        )

        return value_counts_request
