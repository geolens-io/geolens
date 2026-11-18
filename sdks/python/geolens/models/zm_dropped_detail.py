from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


T = TypeVar("T", bound="ZmDroppedDetail")


@_attrs_define
class ZmDroppedDetail:
    """How many source features had Z or M values that the copy doesn't keep.

    Z and M are dropped when the source mixes dimensions or holds curves that
    lose them when linearized, and M alone when measured features cross the
    Web Mercator latitude limit; X and Y are unchanged. The count is taken on
    the source just before and after the copy, so a row written during the
    copy can be counted.

        Attributes:
            features (int):
    """

    features: int

    def to_dict(self) -> dict[str, Any]:
        features = self.features

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "features": features,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        features = d.pop("features")

        zm_dropped_detail = cls(
            features=features,
        )

        return zm_dropped_detail
