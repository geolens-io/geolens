from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="MapBookmark")


@_attrs_define
class MapBookmark:
    """
    Attributes:
        name (str): Bookmark name
        extent (list[float]): [west, south, east, north] in EPSG:4326. A west greater than east means the area crosses
            the antimeridian.
        bearing (float | None | Unset): Map rotation in degrees
        pitch (float | None | Unset): Map tilt in degrees (0-85)
    """

    name: str
    extent: list[float]
    bearing: float | None | Unset = UNSET
    pitch: float | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        extent = self.extent

        bearing: float | None | Unset
        if isinstance(self.bearing, Unset):
            bearing = UNSET
        else:
            bearing = self.bearing

        pitch: float | None | Unset
        if isinstance(self.pitch, Unset):
            pitch = UNSET
        else:
            pitch = self.pitch

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "name": name,
                "extent": extent,
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
        name = d.pop("name")

        extent = cast(list[float], d.pop("extent"))

        def _parse_bearing(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        bearing = _parse_bearing(d.pop("bearing", UNSET))

        def _parse_pitch(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        pitch = _parse_pitch(d.pop("pitch", UNSET))

        map_bookmark = cls(
            name=name,
            extent=extent,
            bearing=bearing,
            pitch=pitch,
        )

        return map_bookmark
