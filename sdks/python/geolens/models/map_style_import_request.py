from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.map_style_import_request_layers_type_0_item import (
        MapStyleImportRequestLayersType0Item,
    )
    from ..models.map_style_import_request_metadata_type_0 import (
        MapStyleImportRequestMetadataType0,
    )
    from ..models.map_style_import_request_sources_type_0 import (
        MapStyleImportRequestSourcesType0,
    )
    from ..models.map_style_import_request_terrain_type_0 import (
        MapStyleImportRequestTerrainType0,
    )


T = TypeVar("T", bound="MapStyleImportRequest")


@_attrs_define
class MapStyleImportRequest:
    """Typed request body for POST /maps/import — API-01 / M-05.

    Mirrors the top-level keys of the MapLibre Style Specification that
    ``parse_maplibre_style_import`` actually reads. ``extra="allow"`` keeps
    forward-compatibility with future MapLibre fields (e.g. ``projection``,
    ``light``, ``transition``) so adding a new key on the client side
    doesn't require a server release.

    Replacing the previous bare-``dict`` body parameter removes
    ``additionalProperties: true`` from the OpenAPI schema and lets
    openapi-python-client generate a navigable named model class.

        Attributes:
            bearing (float | None | Unset):
            center (list[float] | None | Unset): [longitude, latitude] map center
            glyphs (None | str | Unset):
            layers (list[MapStyleImportRequestLayersType0Item] | None | Unset): MapLibre layer specifications
            metadata (MapStyleImportRequestMetadataType0 | None | Unset): Free-form metadata bag (used by GeoLens for
                center/zoom/basemap hints)
            name (None | str | Unset): Display name for the imported map
            pitch (float | None | Unset):
            sources (MapStyleImportRequestSourcesType0 | None | Unset): MapLibre sources object keyed by source id
            sprite (None | str | Unset):
            terrain (MapStyleImportRequestTerrainType0 | None | Unset): MapLibre terrain config (source + exaggeration)
            version (int | None | Unset): MapLibre style version (always 8 in current spec)
            zoom (float | None | Unset):
    """

    bearing: float | None | Unset = UNSET
    center: list[float] | None | Unset = UNSET
    glyphs: None | str | Unset = UNSET
    layers: list[MapStyleImportRequestLayersType0Item] | None | Unset = UNSET
    metadata: MapStyleImportRequestMetadataType0 | None | Unset = UNSET
    name: None | str | Unset = UNSET
    pitch: float | None | Unset = UNSET
    sources: MapStyleImportRequestSourcesType0 | None | Unset = UNSET
    sprite: None | str | Unset = UNSET
    terrain: MapStyleImportRequestTerrainType0 | None | Unset = UNSET
    version: int | None | Unset = UNSET
    zoom: float | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.map_style_import_request_metadata_type_0 import (
            MapStyleImportRequestMetadataType0,
        )
        from ..models.map_style_import_request_sources_type_0 import (
            MapStyleImportRequestSourcesType0,
        )
        from ..models.map_style_import_request_terrain_type_0 import (
            MapStyleImportRequestTerrainType0,
        )

        bearing: float | None | Unset
        if isinstance(self.bearing, Unset):
            bearing = UNSET
        else:
            bearing = self.bearing

        center: list[float] | None | Unset
        if isinstance(self.center, Unset):
            center = UNSET
        elif isinstance(self.center, list):
            center = self.center

        else:
            center = self.center

        glyphs: None | str | Unset
        if isinstance(self.glyphs, Unset):
            glyphs = UNSET
        else:
            glyphs = self.glyphs

        layers: list[dict[str, Any]] | None | Unset
        if isinstance(self.layers, Unset):
            layers = UNSET
        elif isinstance(self.layers, list):
            layers = []
            for layers_type_0_item_data in self.layers:
                layers_type_0_item = layers_type_0_item_data.to_dict()
                layers.append(layers_type_0_item)

        else:
            layers = self.layers

        metadata: dict[str, Any] | None | Unset
        if isinstance(self.metadata, Unset):
            metadata = UNSET
        elif isinstance(self.metadata, MapStyleImportRequestMetadataType0):
            metadata = self.metadata.to_dict()
        else:
            metadata = self.metadata

        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        pitch: float | None | Unset
        if isinstance(self.pitch, Unset):
            pitch = UNSET
        else:
            pitch = self.pitch

        sources: dict[str, Any] | None | Unset
        if isinstance(self.sources, Unset):
            sources = UNSET
        elif isinstance(self.sources, MapStyleImportRequestSourcesType0):
            sources = self.sources.to_dict()
        else:
            sources = self.sources

        sprite: None | str | Unset
        if isinstance(self.sprite, Unset):
            sprite = UNSET
        else:
            sprite = self.sprite

        terrain: dict[str, Any] | None | Unset
        if isinstance(self.terrain, Unset):
            terrain = UNSET
        elif isinstance(self.terrain, MapStyleImportRequestTerrainType0):
            terrain = self.terrain.to_dict()
        else:
            terrain = self.terrain

        version: int | None | Unset
        if isinstance(self.version, Unset):
            version = UNSET
        else:
            version = self.version

        zoom: float | None | Unset
        if isinstance(self.zoom, Unset):
            zoom = UNSET
        else:
            zoom = self.zoom

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if bearing is not UNSET:
            field_dict["bearing"] = bearing
        if center is not UNSET:
            field_dict["center"] = center
        if glyphs is not UNSET:
            field_dict["glyphs"] = glyphs
        if layers is not UNSET:
            field_dict["layers"] = layers
        if metadata is not UNSET:
            field_dict["metadata"] = metadata
        if name is not UNSET:
            field_dict["name"] = name
        if pitch is not UNSET:
            field_dict["pitch"] = pitch
        if sources is not UNSET:
            field_dict["sources"] = sources
        if sprite is not UNSET:
            field_dict["sprite"] = sprite
        if terrain is not UNSET:
            field_dict["terrain"] = terrain
        if version is not UNSET:
            field_dict["version"] = version
        if zoom is not UNSET:
            field_dict["zoom"] = zoom

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.map_style_import_request_layers_type_0_item import (
            MapStyleImportRequestLayersType0Item,
        )
        from ..models.map_style_import_request_metadata_type_0 import (
            MapStyleImportRequestMetadataType0,
        )
        from ..models.map_style_import_request_sources_type_0 import (
            MapStyleImportRequestSourcesType0,
        )
        from ..models.map_style_import_request_terrain_type_0 import (
            MapStyleImportRequestTerrainType0,
        )

        d = dict(src_dict)

        def _parse_bearing(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        bearing = _parse_bearing(d.pop("bearing", UNSET))

        def _parse_center(data: object) -> list[float] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                center_type_0 = cast(list[float], data)

                return center_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None | Unset, data)

        center = _parse_center(d.pop("center", UNSET))

        def _parse_glyphs(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        glyphs = _parse_glyphs(d.pop("glyphs", UNSET))

        def _parse_layers(
            data: object,
        ) -> list[MapStyleImportRequestLayersType0Item] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                layers_type_0 = []
                _layers_type_0 = data
                for layers_type_0_item_data in _layers_type_0:
                    layers_type_0_item = MapStyleImportRequestLayersType0Item.from_dict(
                        layers_type_0_item_data
                    )

                    layers_type_0.append(layers_type_0_item)

                return layers_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[MapStyleImportRequestLayersType0Item] | None | Unset, data)

        layers = _parse_layers(d.pop("layers", UNSET))

        def _parse_metadata(
            data: object,
        ) -> MapStyleImportRequestMetadataType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                metadata_type_0 = MapStyleImportRequestMetadataType0.from_dict(data)

                return metadata_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MapStyleImportRequestMetadataType0 | None | Unset, data)

        metadata = _parse_metadata(d.pop("metadata", UNSET))

        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))

        def _parse_pitch(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        pitch = _parse_pitch(d.pop("pitch", UNSET))

        def _parse_sources(
            data: object,
        ) -> MapStyleImportRequestSourcesType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                sources_type_0 = MapStyleImportRequestSourcesType0.from_dict(data)

                return sources_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MapStyleImportRequestSourcesType0 | None | Unset, data)

        sources = _parse_sources(d.pop("sources", UNSET))

        def _parse_sprite(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        sprite = _parse_sprite(d.pop("sprite", UNSET))

        def _parse_terrain(
            data: object,
        ) -> MapStyleImportRequestTerrainType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                terrain_type_0 = MapStyleImportRequestTerrainType0.from_dict(data)

                return terrain_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MapStyleImportRequestTerrainType0 | None | Unset, data)

        terrain = _parse_terrain(d.pop("terrain", UNSET))

        def _parse_version(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        version = _parse_version(d.pop("version", UNSET))

        def _parse_zoom(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        zoom = _parse_zoom(d.pop("zoom", UNSET))

        map_style_import_request = cls(
            bearing=bearing,
            center=center,
            glyphs=glyphs,
            layers=layers,
            metadata=metadata,
            name=name,
            pitch=pitch,
            sources=sources,
            sprite=sprite,
            terrain=terrain,
            version=version,
            zoom=zoom,
        )

        map_style_import_request.additional_properties = d
        return map_style_import_request

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
