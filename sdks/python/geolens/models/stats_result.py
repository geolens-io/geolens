from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="StatsResult")


@_attrs_define
class StatsResult:
    """The requested statistics; one over no rows is null.

    ``sum``, ``min`` and ``max`` are exact: a number when JSON can carry it
    exactly, else text. ``avg`` is a float, or text for NaN and infinity.

        Attributes:
            count (int | None | Unset):
            sum_ (float | int | None | str | Unset):
            avg (float | None | str | Unset):
            min_ (float | int | None | str | Unset):
            max_ (float | int | None | str | Unset):
    """

    count: int | None | Unset = UNSET
    sum_: float | int | None | str | Unset = UNSET
    avg: float | None | str | Unset = UNSET
    min_: float | int | None | str | Unset = UNSET
    max_: float | int | None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        count: int | None | Unset
        if isinstance(self.count, Unset):
            count = UNSET
        else:
            count = self.count

        sum_: float | int | None | str | Unset
        if isinstance(self.sum_, Unset):
            sum_ = UNSET
        else:
            sum_ = self.sum_

        avg: float | None | str | Unset
        if isinstance(self.avg, Unset):
            avg = UNSET
        else:
            avg = self.avg

        min_: float | int | None | str | Unset
        if isinstance(self.min_, Unset):
            min_ = UNSET
        else:
            min_ = self.min_

        max_: float | int | None | str | Unset
        if isinstance(self.max_, Unset):
            max_ = UNSET
        else:
            max_ = self.max_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if count is not UNSET:
            field_dict["count"] = count
        if sum_ is not UNSET:
            field_dict["sum"] = sum_
        if avg is not UNSET:
            field_dict["avg"] = avg
        if min_ is not UNSET:
            field_dict["min"] = min_
        if max_ is not UNSET:
            field_dict["max"] = max_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        count = _parse_count(d.pop("count", UNSET))

        def _parse_sum_(data: object) -> float | int | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | int | None | str | Unset, data)

        sum_ = _parse_sum_(d.pop("sum", UNSET))

        def _parse_avg(data: object) -> float | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | str | Unset, data)

        avg = _parse_avg(d.pop("avg", UNSET))

        def _parse_min_(data: object) -> float | int | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | int | None | str | Unset, data)

        min_ = _parse_min_(d.pop("min", UNSET))

        def _parse_max_(data: object) -> float | int | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | int | None | str | Unset, data)

        max_ = _parse_max_(d.pop("max", UNSET))

        stats_result = cls(
            count=count,
            sum_=sum_,
            avg=avg,
            min_=min_,
            max_=max_,
        )

        stats_result.additional_properties = d
        return stats_result

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
