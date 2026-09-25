from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.tileset_metadata_bounding_volume_type_0 import (
    check_tileset_metadata_bounding_volume_type_0,
)
from ..models.tileset_metadata_bounding_volume_type_0 import (
    TilesetMetadataBoundingVolumeType0,
)
from typing import cast


T = TypeVar("T", bound="TilesetMetadata")


@_attrs_define
class TilesetMetadata:
    """A 3D Tiles dataset's published tileset.

    Attributes:
        url (str): URL path of the tileset's tileset.json on the app origin, e.g.
            /api/datasets/{id}/tiles3d/tileset.json
        size_bytes (int | None | Unset): Unpacked size of the tileset in bytes
        version (None | str | Unset): The tileset's asset.version: '1.0' or '1.1'
        geometric_error (float | None | Unset): The root tile's geometricError, when tileset.json gives one
        bounding_volume (None | TilesetMetadataBoundingVolumeType0 | Unset): The kind of the root tile's bounding
            volume. Only a region yields the dataset's extent; a box or sphere leaves it null.
        content_types (list[str] | None | Unset): The tile formats in the tileset, sorted: b3dm, i3dm, pnts, cmpt, glb,
            gltf, subtree, vctr or geom, including the tiles inside a cmpt. Null for a tileset published before GeoLens
            recorded them.
        extensions_required (list[str] | None | Unset): Every extension a client must support to load the tileset,
            sorted: the extensionsRequired of its tileset JSON, external tilesets included, and of its glTF content. Null
            for a tileset published before GeoLens recorded them.
    """

    url: str
    size_bytes: int | None | Unset = UNSET
    version: None | str | Unset = UNSET
    geometric_error: float | None | Unset = UNSET
    bounding_volume: None | TilesetMetadataBoundingVolumeType0 | Unset = UNSET
    content_types: list[str] | None | Unset = UNSET
    extensions_required: list[str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        url = self.url

        size_bytes: int | None | Unset
        if isinstance(self.size_bytes, Unset):
            size_bytes = UNSET
        else:
            size_bytes = self.size_bytes

        version: None | str | Unset
        if isinstance(self.version, Unset):
            version = UNSET
        else:
            version = self.version

        geometric_error: float | None | Unset
        if isinstance(self.geometric_error, Unset):
            geometric_error = UNSET
        else:
            geometric_error = self.geometric_error

        bounding_volume: None | str | Unset
        if isinstance(self.bounding_volume, Unset):
            bounding_volume = UNSET
        elif isinstance(self.bounding_volume, str):
            bounding_volume = self.bounding_volume
        else:
            bounding_volume = self.bounding_volume

        content_types: list[str] | None | Unset
        if isinstance(self.content_types, Unset):
            content_types = UNSET
        elif isinstance(self.content_types, list):
            content_types = self.content_types

        else:
            content_types = self.content_types

        extensions_required: list[str] | None | Unset
        if isinstance(self.extensions_required, Unset):
            extensions_required = UNSET
        elif isinstance(self.extensions_required, list):
            extensions_required = self.extensions_required

        else:
            extensions_required = self.extensions_required

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "url": url,
            }
        )
        if size_bytes is not UNSET:
            field_dict["size_bytes"] = size_bytes
        if version is not UNSET:
            field_dict["version"] = version
        if geometric_error is not UNSET:
            field_dict["geometric_error"] = geometric_error
        if bounding_volume is not UNSET:
            field_dict["bounding_volume"] = bounding_volume
        if content_types is not UNSET:
            field_dict["content_types"] = content_types
        if extensions_required is not UNSET:
            field_dict["extensions_required"] = extensions_required

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        url = d.pop("url")

        def _parse_size_bytes(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        size_bytes = _parse_size_bytes(d.pop("size_bytes", UNSET))

        def _parse_version(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        version = _parse_version(d.pop("version", UNSET))

        def _parse_geometric_error(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        geometric_error = _parse_geometric_error(d.pop("geometric_error", UNSET))

        def _parse_bounding_volume(
            data: object,
        ) -> None | TilesetMetadataBoundingVolumeType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                bounding_volume_type_0 = check_tileset_metadata_bounding_volume_type_0(
                    data
                )

                return bounding_volume_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TilesetMetadataBoundingVolumeType0 | Unset, data)

        bounding_volume = _parse_bounding_volume(d.pop("bounding_volume", UNSET))

        def _parse_content_types(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                content_types_type_0 = cast(list[str], data)

                return content_types_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        content_types = _parse_content_types(d.pop("content_types", UNSET))

        def _parse_extensions_required(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                extensions_required_type_0 = cast(list[str], data)

                return extensions_required_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        extensions_required = _parse_extensions_required(
            d.pop("extensions_required", UNSET)
        )

        tileset_metadata = cls(
            url=url,
            size_bytes=size_bytes,
            version=version,
            geometric_error=geometric_error,
            bounding_volume=bounding_volume,
            content_types=content_types,
            extensions_required=extensions_required,
        )

        tileset_metadata.additional_properties = d
        return tileset_metadata

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
