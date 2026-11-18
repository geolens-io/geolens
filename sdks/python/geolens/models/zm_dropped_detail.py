from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


T = TypeVar("T", bound="ZmDroppedDetail")


@_attrs_define
class ZmDroppedDetail:
    """How many features were stored without the Z or M values they had.

    A source whose geometries mix dimensions is stored in 2D, so the features
    that had Z or M lose those values; X and Y are unchanged.

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
