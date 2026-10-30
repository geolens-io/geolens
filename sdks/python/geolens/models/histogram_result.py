from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


if TYPE_CHECKING:
    from ..models.histogram_bin import HistogramBin


T = TypeVar("T", bound="HistogramResult")


@_attrs_define
class HistogramResult:
    """
    Attributes:
        bins (list[HistogramBin]): Equal-width bins over the finite values, empty with none. Unless whole_numbers is
            true, a bin holds its lower edge but not its upper one, and the last bin holds both.
        whole_numbers (bool | Unset): Whether each bin holds the whole numbers from its lower edge to one below its
            upper edge. Only an integer column has whole-number bins, and only while every edge is a safe JavaScript
            integer; they may then number fewer than requested, and the last may be narrower. Default: False.
    """

    bins: list[HistogramBin]
    whole_numbers: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        bins = []
        for bins_item_data in self.bins:
            bins_item = bins_item_data.to_dict()
            bins.append(bins_item)

        whole_numbers = self.whole_numbers

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "bins": bins,
            }
        )
        if whole_numbers is not UNSET:
            field_dict["whole_numbers"] = whole_numbers

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

        whole_numbers = d.pop("whole_numbers", UNSET)

        histogram_result = cls(
            bins=bins,
            whole_numbers=whole_numbers,
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
