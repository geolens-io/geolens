from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.histogram_bin import HistogramBin


T = TypeVar("T", bound="HistogramResult")


@_attrs_define
class HistogramResult:
    """
    Attributes:
        bins (list[HistogramBin]): Equal-width bins over the finite values, empty with none; an integer column's bins
            hold whole numbers, may number fewer than requested, and the last may be narrower.
    """

    bins: list[HistogramBin]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        bins = []
        for bins_item_data in self.bins:
            bins_item = bins_item_data.to_dict()
            bins.append(bins_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "bins": bins,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.histogram_bin import HistogramBin

        d = dict(src_dict)
        bins = []
        _bins = d.pop("bins")
        for bins_item_data in _bins:
            bins_item = HistogramBin.from_dict(bins_item_data)

            bins.append(bins_item)

        histogram_result = cls(
            bins=bins,
        )

        histogram_result.additional_properties = d
        return histogram_result

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
