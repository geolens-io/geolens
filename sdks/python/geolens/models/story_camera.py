from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="StoryCamera")


@_attrs_define
class StoryCamera:
    """
    Attributes:
        center (list[float]): Longitude, latitude.
        zoom (float):
        bearing (float | Unset):  Default: 0.0.
        pitch (float | Unset):  Default: 0.0.
    """

    center: list[float]
    zoom: float
    bearing: float | Unset = 0.0
    pitch: float | Unset = 0.0

    def to_dict(self) -> dict[str, Any]:
        center = []
        for center_item_data in self.center:
            center_item: float
            center_item = center_item_data
            center.append(center_item)

        zoom = self.zoom

        bearing = self.bearing

        pitch = self.pitch

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "center": center,
                "zoom": zoom,
            }
        )
        if bearing is not UNSET:
            field_dict["bearing"] = bearing
        if pitch is not UNSET:
            field_dict["pitch"] = pitch

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        center = []
        _center = d.pop("center")
        for center_item_data in _center:

            def _parse_center_item(data: object) -> float:
                return cast(float, data)

            center_item = _parse_center_item(center_item_data)

            center.append(center_item)

        zoom = d.pop("zoom")

        bearing = d.pop("bearing", UNSET)

        pitch = d.pop("pitch", UNSET)

        story_camera = cls(
            center=center,
            zoom=zoom,
            bearing=bearing,
            pitch=pitch,
        )

        return story_camera
