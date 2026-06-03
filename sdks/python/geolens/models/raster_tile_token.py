from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast
from typing import Literal


T = TypeVar("T", bound="RasterTileToken")


@_attrs_define
class RasterTileToken:
    """
    Attributes:
        bounds (list[float] | None):
        format_ (str):
        kind (Literal['raster']):
        maxzoom (int):
        minzoom (int):
        tile_size (int):
        tile_url (str):
    """

    bounds: list[float] | None
    format_: str
    kind: Literal["raster"]
    maxzoom: int
    minzoom: int
    tile_size: int
    tile_url: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        bounds: list[float] | None
        if isinstance(self.bounds, list):
            bounds = self.bounds

        else:
            bounds = self.bounds

        format_ = self.format_

        kind = self.kind

        maxzoom = self.maxzoom

        minzoom = self.minzoom

        tile_size = self.tile_size

        tile_url = self.tile_url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "bounds": bounds,
                "format": format_,
                "kind": kind,
                "maxzoom": maxzoom,
                "minzoom": minzoom,
                "tile_size": tile_size,
                "tile_url": tile_url,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_bounds(data: object) -> list[float] | None:
            if data is None:
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                bounds_type_0 = cast(list[float], data)

                return bounds_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None, data)

        bounds = _parse_bounds(d.pop("bounds"))

        format_ = d.pop("format")

        kind = cast(Literal["raster"], d.pop("kind"))
        if kind != "raster":
            raise ValueError(f"kind must match const 'raster', got '{kind}'")

        maxzoom = d.pop("maxzoom")

        minzoom = d.pop("minzoom")

        tile_size = d.pop("tile_size")

        tile_url = d.pop("tile_url")

        raster_tile_token = cls(
            bounds=bounds,
            format_=format_,
            kind=kind,
            maxzoom=maxzoom,
            minzoom=minzoom,
            tile_size=tile_size,
            tile_url=tile_url,
        )

        raster_tile_token.additional_properties = d
        return raster_tile_token

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
