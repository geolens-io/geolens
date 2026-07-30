from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


T = TypeVar("T", bound="MercatorClipDetail")


@_attrs_define
class MercatorClipDetail:
    """fix(#888): how much geometry the Web Mercator clamp destroyed.

    The clamp is a box, not a latitude cutoff: longitude -180 to 180 and
    latitude -85.06 to 85.06. Either bound can be the one that cost the user
    geometry, so clients must not present this as a latitude-only problem
    (fix(#899 codex r1)).

    ``dropped_features`` lost their geometry entirely (a valid point at lat
    -89.95 becomes ``MULTIPOINT EMPTY``); ``clipped_features`` survived in
    reduced form.

        Attributes:
            clipped_features (int):
            dropped_features (int):
    """

    clipped_features: int
    dropped_features: int

    def to_dict(self) -> dict[str, Any]:
        clipped_features = self.clipped_features

        dropped_features = self.dropped_features

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "clipped_features": clipped_features,
                "dropped_features": dropped_features,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        clipped_features = d.pop("clipped_features")

        dropped_features = d.pop("dropped_features")

        mercator_clip_detail = cls(
            clipped_features=clipped_features,
            dropped_features=dropped_features,
        )

        return mercator_clip_detail
