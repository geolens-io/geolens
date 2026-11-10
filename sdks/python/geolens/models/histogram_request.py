from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.histogram_request_filter_type_0 import HistogramRequestFilterType0


T = TypeVar("T", bound="HistogramRequest")


@_attrs_define
class HistogramRequest:
    """
    Attributes:
        op (Literal['histogram']):
        column (str):
        filter_ (HistogramRequestFilterType0 | None | Unset): CQL2-JSON filter, as the OGC API Features `filter`
            accepts.
        bbox (list[float] | None | Unset): Map view `[west, south, east, north]` in WGS 84; west greater than east
            crosses the antimeridian. Omit for the whole layer.
        bins (int | Unset):  Default: 10.
    """

    op: Literal["histogram"]
    column: str
    filter_: HistogramRequestFilterType0 | None | Unset = UNSET
    bbox: list[float] | None | Unset = UNSET
    bins: int | Unset = 10

    def to_dict(self) -> dict[str, Any]:
        from ..models.histogram_request_filter_type_0 import HistogramRequestFilterType0

        op = self.op

        column = self.column

        filter_: dict[str, Any] | None | Unset
        if isinstance(self.filter_, Unset):
            filter_ = UNSET
        elif isinstance(self.filter_, HistogramRequestFilterType0):
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

        bins = self.bins

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
        if bins is not UNSET:
            field_dict["bins"] = bins

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.histogram_request_filter_type_0 import HistogramRequestFilterType0

        d = dict(src_dict)
        op = cast(Literal["histogram"], d.pop("op"))
        if op != "histogram":
            raise ValueError(f"op must match const 'histogram', got '{op}'")

        column = d.pop("column")

        def _parse_filter_(data: object) -> HistogramRequestFilterType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                filter_type_0 = HistogramRequestFilterType0.from_dict(data)

                return filter_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(HistogramRequestFilterType0 | None | Unset, data)

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

        bins = d.pop("bins", UNSET)

        histogram_request = cls(
            op=op,
            column=column,
            filter_=filter_,
            bbox=bbox,
            bins=bins,
        )

        return histogram_request
