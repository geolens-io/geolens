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
        count (int | Unset):  Default: 0.
        data_type (None | str | Unset): 'categorical' for non-numeric columns; null for numeric.
        distinct_count (int | None | Unset): Distinct non-null value count (categorical columns only).
        max_ (float | None | Unset):
        mean (float | None | Unset):
        min_ (float | None | Unset):
        quantiles (list[float] | Unset):
        stddev (float | None | Unset):
    """

    count: int | Unset = 0
    data_type: None | str | Unset = UNSET
    distinct_count: int | None | Unset = UNSET
    max_: float | None | Unset = UNSET
    mean: float | None | Unset = UNSET
    min_: float | None | Unset = UNSET
    quantiles: list[float] | Unset = UNSET
    stddev: float | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        count = self.count

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

        max_: float | None | Unset
        if isinstance(self.max_, Unset):
            max_ = UNSET
        else:
            max_ = self.max_

        mean: float | None | Unset
        if isinstance(self.mean, Unset):
            mean = UNSET
        else:
            mean = self.mean

        min_: float | None | Unset
        if isinstance(self.min_, Unset):
            min_ = UNSET
        else:
            min_ = self.min_

        quantiles: list[float] | Unset = UNSET
        if not isinstance(self.quantiles, Unset):
            quantiles = self.quantiles

        stddev: float | None | Unset
        if isinstance(self.stddev, Unset):
            stddev = UNSET
        else:
            stddev = self.stddev

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if count is not UNSET:
            field_dict["count"] = count
        if data_type is not UNSET:
            field_dict["data_type"] = data_type
        if distinct_count is not UNSET:
            field_dict["distinct_count"] = distinct_count
        if max_ is not UNSET:
            field_dict["max"] = max_
        if mean is not UNSET:
            field_dict["mean"] = mean
        if min_ is not UNSET:
            field_dict["min"] = min_
        if quantiles is not UNSET:
            field_dict["quantiles"] = quantiles
        if stddev is not UNSET:
            field_dict["stddev"] = stddev

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        count = d.pop("count", UNSET)

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

        def _parse_max_(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        max_ = _parse_max_(d.pop("max", UNSET))

        def _parse_mean(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        mean = _parse_mean(d.pop("mean", UNSET))

        def _parse_min_(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        min_ = _parse_min_(d.pop("min", UNSET))

        quantiles = cast(list[float], d.pop("quantiles", UNSET))

        def _parse_stddev(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        stddev = _parse_stddev(d.pop("stddev", UNSET))

        column_stats_response = cls(
            count=count,
            data_type=data_type,
            distinct_count=distinct_count,
            max_=max_,
            mean=mean,
            min_=min_,
            quantiles=quantiles,
            stddev=stddev,
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
