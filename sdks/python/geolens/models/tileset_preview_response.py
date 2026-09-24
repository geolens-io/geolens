from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.tileset_preview_response_bounding_volume import (
    check_tileset_preview_response_bounding_volume,
)
from ..models.tileset_preview_response_bounding_volume import (
    TilesetPreviewResponseBoundingVolume,
)
from ..models.tileset_preview_response_version import (
    check_tileset_preview_response_version,
)
from ..models.tileset_preview_response_version import TilesetPreviewResponseVersion
from typing import cast
from uuid import UUID


T = TypeVar("T", bound="TilesetPreviewResponse")


@_attrs_define
class TilesetPreviewResponse:
    """What a staged 3D Tiles tileset archive holds, read without unpacking it.

    Attributes:
        job_id (UUID): Identifier of the tileset ingestion job being previewed.
        source_filename (None | str): Original filename of the uploaded tileset archive.
        version (TilesetPreviewResponseVersion): The tileset's asset.version from its tileset.json.
        geometric_error (float | None): The root tile's geometricError, or null when tileset.json gives none.
        bounding_volume (TilesetPreviewResponseBoundingVolume): The kind of the root tile's bounding volume.
        extent_bbox (list[float] | None): The root region as [west, south, east, north] in degrees; west > east when it
            crosses the antimeridian. Null for a box or sphere.
        unpacked_bytes (int): Total size of the archive's files once unpacked.
        entry_count (int): Number of entries, files and folders, in the archive.
    """

    job_id: UUID
    source_filename: None | str
    version: TilesetPreviewResponseVersion
    geometric_error: float | None
    bounding_volume: TilesetPreviewResponseBoundingVolume
    extent_bbox: list[float] | None
    unpacked_bytes: int
    entry_count: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        job_id = str(self.job_id)

        source_filename: None | str
        source_filename = self.source_filename

        version: str = self.version

        geometric_error: float | None
        geometric_error = self.geometric_error

        bounding_volume: str = self.bounding_volume

        extent_bbox: list[float] | None
        if isinstance(self.extent_bbox, list):
            extent_bbox = self.extent_bbox

        else:
            extent_bbox = self.extent_bbox

        unpacked_bytes = self.unpacked_bytes

        entry_count = self.entry_count

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "job_id": job_id,
                "source_filename": source_filename,
                "version": version,
                "geometric_error": geometric_error,
                "bounding_volume": bounding_volume,
                "extent_bbox": extent_bbox,
                "unpacked_bytes": unpacked_bytes,
                "entry_count": entry_count,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        job_id = UUID(d.pop("job_id"))

        def _parse_source_filename(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source_filename = _parse_source_filename(d.pop("source_filename"))

        version = check_tileset_preview_response_version(d.pop("version"))

        def _parse_geometric_error(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        geometric_error = _parse_geometric_error(d.pop("geometric_error"))

        bounding_volume = check_tileset_preview_response_bounding_volume(
            d.pop("bounding_volume")
        )

        def _parse_extent_bbox(data: object) -> list[float] | None:
            if data is None:
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                extent_bbox_type_0 = cast(list[float], data)

                return extent_bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None, data)

        extent_bbox = _parse_extent_bbox(d.pop("extent_bbox"))

        unpacked_bytes = d.pop("unpacked_bytes")

        entry_count = d.pop("entry_count")

        tileset_preview_response = cls(
            job_id=job_id,
            source_filename=source_filename,
            version=version,
            geometric_error=geometric_error,
            bounding_volume=bounding_volume,
            extent_bbox=extent_bbox,
            unpacked_bytes=unpacked_bytes,
            entry_count=entry_count,
        )

        tileset_preview_response.additional_properties = d
        return tileset_preview_response

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
