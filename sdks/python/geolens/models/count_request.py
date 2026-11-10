from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.count_request_filter_type_0 import CountRequestFilterType0


T = TypeVar("T", bound="CountRequest")


@_attrs_define
class CountRequest:
    """
    Attributes:
        op (Literal['count']):
        filter_ (CountRequestFilterType0 | None | Unset): CQL2-JSON filter, as the OGC API Features `filter` accepts.
        bbox (list[float] | None | Unset): Map view `[west, south, east, north]` in WGS 84; west greater than east
            crosses the antimeridian. Omit for the whole layer.
    """

    op: Literal["count"]
    filter_: CountRequestFilterType0 | None | Unset = UNSET
    bbox: list[float] | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.count_request_filter_type_0 import CountRequestFilterType0

        op = self.op

        filter_: dict[str, Any] | None | Unset
        if isinstance(self.filter_, Unset):
            filter_ = UNSET
        elif isinstance(self.filter_, CountRequestFilterType0):
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

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "op": op,
            }
        )
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if bbox is not UNSET:
            field_dict["bbox"] = bbox

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.count_request_filter_type_0 import CountRequestFilterType0

        d = dict(src_dict)
        op = cast(Literal["count"], d.pop("op"))
        if op != "count":
            raise ValueError(f"op must match const 'count', got '{op}'")

        def _parse_filter_(data: object) -> CountRequestFilterType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                filter_type_0 = CountRequestFilterType0.from_dict(data)

                return filter_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(CountRequestFilterType0 | None | Unset, data)

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

        count_request = cls(
            op=op,
            filter_=filter_,
            bbox=bbox,
        )

        return count_request
