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
    """A raster tile template, signed like its vector sibling.

    fix(#688): the raster shape used to carry no signature at all, so a client
    following the API contract literally received an *unauthenticated* template
    for a private raster. MapLibre issues the tile image requests itself and
    attaches no `X-Api-Key`, so an API-key-only client could not render one —
    the workarounds were `setTransformRequest` (not available to every consumer)
    or `?api_key=` in the tile URL, which puts a non-expiring unscoped
    credential into tile URLs, server logs, and saved client project files.

    `tile_url` now arrives with `sig`/`exp`/`scope` already in its query string,
    so the template is self-sufficient and expires. The three are also returned
    as fields, mirroring `VectorTileToken`, for clients that rebuild the URL.

        Attributes:
            kind (Literal['raster']):
            tile_url (str):
            sig (str):
            exp (int):
            scope (str):
            expires_in (int):
            bounds (list[float] | None):
            minzoom (int):
            maxzoom (int):
            tile_size (int):
            format_ (str):
    """

    kind: Literal["raster"]
    tile_url: str
    sig: str
    exp: int
    scope: str
    expires_in: int
    bounds: list[float] | None
    minzoom: int
    maxzoom: int
    tile_size: int
    format_: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind

        tile_url = self.tile_url

        sig = self.sig

        exp = self.exp

        scope = self.scope

        expires_in = self.expires_in

        bounds: list[float] | None
        if isinstance(self.bounds, list):
            bounds = self.bounds

        else:
            bounds = self.bounds

        minzoom = self.minzoom

        maxzoom = self.maxzoom

        tile_size = self.tile_size

        format_ = self.format_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "kind": kind,
                "tile_url": tile_url,
                "sig": sig,
                "exp": exp,
                "scope": scope,
                "expires_in": expires_in,
                "bounds": bounds,
                "minzoom": minzoom,
                "maxzoom": maxzoom,
                "tile_size": tile_size,
                "format": format_,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        kind = cast(Literal["raster"], d.pop("kind"))
        if kind != "raster":
            raise ValueError(f"kind must match const 'raster', got '{kind}'")

        tile_url = d.pop("tile_url")

        sig = d.pop("sig")

        exp = d.pop("exp")

        scope = d.pop("scope")

        expires_in = d.pop("expires_in")

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

        minzoom = d.pop("minzoom")

        maxzoom = d.pop("maxzoom")

        tile_size = d.pop("tile_size")

        format_ = d.pop("format")

        raster_tile_token = cls(
            kind=kind,
            tile_url=tile_url,
            sig=sig,
            exp=exp,
            scope=scope,
            expires_in=expires_in,
            bounds=bounds,
            minzoom=minzoom,
            maxzoom=maxzoom,
            tile_size=tile_size,
            format_=format_,
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
