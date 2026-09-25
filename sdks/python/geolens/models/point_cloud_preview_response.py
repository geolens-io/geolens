from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.point_cloud_preview_response_point_format import (
    check_point_cloud_preview_response_point_format,
)
from ..models.point_cloud_preview_response_point_format import (
    PointCloudPreviewResponsePointFormat,
)
from typing import cast
from uuid import UUID


T = TypeVar("T", bound="PointCloudPreviewResponse")


@_attrs_define
class PointCloudPreviewResponse:
    """What a staged COPC point cloud holds, read from its header and hierarchy.

    Attributes:
        job_id (UUID): Identifier of the point cloud ingestion job being previewed.
        source_filename (None | str): Original filename of the uploaded point cloud.
        point_count (int): Number of points in the file.
        point_format (PointCloudPreviewResponsePointFormat): The file's LAS point data record format.
        srid (int | None): EPSG code of the horizontal coordinate reference system, or null when it has none.
        vertical_crs (None | str): Name of the vertical coordinate reference system, if any.
        extent_bbox (list[float]): The extent as [west, south, east, north] in degrees; west > east when it crosses the
            antimeridian.
        z_min (float): Lowest elevation, in the file's units.
        z_max (float): Highest elevation, in the file's units.
        size_bytes (int): Size of the file in bytes.
    """

    job_id: UUID
    source_filename: None | str
    point_count: int
    point_format: PointCloudPreviewResponsePointFormat
    srid: int | None
    vertical_crs: None | str
    extent_bbox: list[float]
    z_min: float
    z_max: float
    size_bytes: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        job_id = str(self.job_id)

        source_filename: None | str
        source_filename = self.source_filename

        point_count = self.point_count

        point_format: int = self.point_format

        srid: int | None
        srid = self.srid

        vertical_crs: None | str
        vertical_crs = self.vertical_crs

        extent_bbox = self.extent_bbox

        z_min = self.z_min

        z_max = self.z_max

        size_bytes = self.size_bytes

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "job_id": job_id,
                "source_filename": source_filename,
                "point_count": point_count,
                "point_format": point_format,
                "srid": srid,
                "vertical_crs": vertical_crs,
                "extent_bbox": extent_bbox,
                "z_min": z_min,
                "z_max": z_max,
                "size_bytes": size_bytes,
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

        point_count = d.pop("point_count")

        point_format = check_point_cloud_preview_response_point_format(
            d.pop("point_format")
        )

        def _parse_srid(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        srid = _parse_srid(d.pop("srid"))

        def _parse_vertical_crs(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        vertical_crs = _parse_vertical_crs(d.pop("vertical_crs"))

        extent_bbox = cast(list[float], d.pop("extent_bbox"))

        z_min = d.pop("z_min")

        z_max = d.pop("z_max")

        size_bytes = d.pop("size_bytes")

        point_cloud_preview_response = cls(
            job_id=job_id,
            source_filename=source_filename,
            point_count=point_count,
            point_format=point_format,
            srid=srid,
            vertical_crs=vertical_crs,
            extent_bbox=extent_bbox,
            z_min=z_min,
            z_max=z_max,
            size_bytes=size_bytes,
        )

        point_cloud_preview_response.additional_properties = d
        return point_cloud_preview_response

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
