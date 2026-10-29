from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset


T = TypeVar("T", bound="HistogramConfig")


@_attrs_define
class HistogramConfig:
    """
    Attributes:
        column (str):
        bins (int | Unset):  Default: 20.
    """

    column: str
    bins: int | Unset = 20

    def to_dict(self) -> dict[str, Any]:
        column = self.column

        bins = self.bins

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "column": column,
            }
        )
        if bins is not UNSET:
            field_dict["bins"] = bins

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        column = d.pop("column")

        bins = d.pop("bins", UNSET)

        histogram_config = cls(
            column=column,
            bins=bins,
        )

        return histogram_config
