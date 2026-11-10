from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.stats_request_stats_item import check_stats_request_stats_item
from ..models.stats_request_stats_item import StatsRequestStatsItem
from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.stats_request_filter_type_0 import StatsRequestFilterType0


T = TypeVar("T", bound="StatsRequest")


@_attrs_define
class StatsRequest:
    """
    Attributes:
        op (Literal['stats']):
        column (str):
        stats (list[StatsRequestStatsItem]):
        filter_ (None | StatsRequestFilterType0 | Unset): CQL2-JSON filter, as the OGC API Features `filter` accepts.
        bbox (list[float] | None | Unset): Map view `[west, south, east, north]` in WGS 84; west greater than east
            crosses the antimeridian. Omit for the whole layer.
    """

    op: Literal["stats"]
    column: str
    stats: list[StatsRequestStatsItem]
    filter_: None | StatsRequestFilterType0 | Unset = UNSET
    bbox: list[float] | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.stats_request_filter_type_0 import StatsRequestFilterType0

        op = self.op

        column = self.column

        stats = []
        for stats_item_data in self.stats:
            stats_item: str = stats_item_data
            stats.append(stats_item)

        filter_: dict[str, Any] | None | Unset
        if isinstance(self.filter_, Unset):
            filter_ = UNSET
        elif isinstance(self.filter_, StatsRequestFilterType0):
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
                "column": column,
                "stats": stats,
            }
        )
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if bbox is not UNSET:
            field_dict["bbox"] = bbox

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stats_request_filter_type_0 import StatsRequestFilterType0

        d = dict(src_dict)
        op = cast(Literal["stats"], d.pop("op"))
        if op != "stats":
            raise ValueError(f"op must match const 'stats', got '{op}'")

        column = d.pop("column")

        stats = []
        _stats = d.pop("stats")
        for stats_item_data in _stats:
            stats_item = check_stats_request_stats_item(stats_item_data)

            stats.append(stats_item)

        def _parse_filter_(data: object) -> None | StatsRequestFilterType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                filter_type_0 = StatsRequestFilterType0.from_dict(data)

                return filter_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | StatsRequestFilterType0 | Unset, data)

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

        stats_request = cls(
            op=op,
            column=column,
            stats=stats,
            filter_=filter_,
            bbox=bbox,
        )

        return stats_request
