from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="ColumnStatsResponse")


@_attrs_define
class ColumnStatsResponse:
    """
    Attributes:
        min_ (float | None | Unset):
        max_ (float | None | Unset):
        count (int | Unset):  Default: 0.
        mean (float | None | Unset):
        quantiles (list[float] | Unset):
        stddev (float | None | Unset):
        data_type (None | str | Unset): 'categorical' for non-numeric columns; null for numeric.
        distinct_count (int | None | Unset): Distinct non-null value count (categorical columns only).
    """

    min_: float | None | Unset = UNSET
    max_: float | None | Unset = UNSET
    count: int | Unset = 0
    mean: float | None | Unset = UNSET
    quantiles: list[float] | Unset = UNSET
    stddev: float | None | Unset = UNSET
    data_type: None | str | Unset = UNSET
    distinct_count: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        min_: float | None | Unset
        if isinstance(self.min_, Unset):
            min_ = UNSET
        else:
            min_ = self.min_

        max_: float | None | Unset
        if isinstance(self.max_, Unset):
            max_ = UNSET
        else:
            max_ = self.max_

        count = self.count

        mean: float | None | Unset
        if isinstance(self.mean, Unset):
            mean = UNSET
        else:
            mean = self.mean

        quantiles: list[float] | Unset = UNSET
        if not isinstance(self.quantiles, Unset):
            quantiles = self.quantiles

        stddev: float | None | Unset
        if isinstance(self.stddev, Unset):
            stddev = UNSET
        else:
            stddev = self.stddev

        data_type: None | str | Unset
        if isinstance(self.data_type, Unset):
            data_type = UNSET
        else:
            data_type = self.data_type

        distinct_count: int | None | Unset
        if isinstance(self.distinct_count, Unset):
            distinct_count = UNSET
        else:
            distinct_count = self.distinct_count

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if min_ is not UNSET:
            field_dict["min"] = min_
        if max_ is not UNSET:
            field_dict["max"] = max_
        if count is not UNSET:
            field_dict["count"] = count
        if mean is not UNSET:
            field_dict["mean"] = mean
        if quantiles is not UNSET:
            field_dict["quantiles"] = quantiles
        if stddev is not UNSET:
            field_dict["stddev"] = stddev
        if data_type is not UNSET:
            field_dict["data_type"] = data_type
        if distinct_count is not UNSET:
            field_dict["distinct_count"] = distinct_count

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_min_(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        min_ = _parse_min_(d.pop("min", UNSET))

        def _parse_max_(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        max_ = _parse_max_(d.pop("max", UNSET))

        count = d.pop("count", UNSET)

        def _parse_mean(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        mean = _parse_mean(d.pop("mean", UNSET))

        quantiles = cast(list[float], d.pop("quantiles", UNSET))

        def _parse_stddev(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        stddev = _parse_stddev(d.pop("stddev", UNSET))

        def _parse_data_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        data_type = _parse_data_type(d.pop("data_type", UNSET))

        def _parse_distinct_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        distinct_count = _parse_distinct_count(d.pop("distinct_count", UNSET))

        column_stats_response = cls(
            min_=min_,
            max_=max_,
            count=count,
            mean=mean,
            quantiles=quantiles,
            stddev=stddev,
            data_type=data_type,
            distinct_count=distinct_count,
        )

        column_stats_response.additional_properties = d
        return column_stats_response

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
