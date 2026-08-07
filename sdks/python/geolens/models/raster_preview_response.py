from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime


T = TypeVar("T", bound="RasterPreviewResponse")


@_attrs_define
class RasterPreviewResponse:
    """
    Attributes:
        job_id (UUID): Identifier of the raster ingestion job being previewed.
        source_filename (None | str): Original filename of the uploaded raster file.
        crs_epsg (int | None): Detected EPSG code for the raster's CRS, if available.
        crs_wkt (None | str): Full WKT representation of the raster's CRS.
        band_count (int): Number of raster bands.
        width (int): Raster width in pixels.
        height (int): Raster height in pixels.
        dtype (str): Pixel data type (e.g. 'uint8', 'float32').
        nodata (float | None | str): Nodata value for the raster, if defined.
        res_x (float): Pixel resolution along the X axis in CRS units.
        res_y (float): Pixel resolution along the Y axis in CRS units.
        compression (None | str): Existing compression method (e.g. 'LZW', 'DEFLATE'), or null for uncompressed.
        file_size_bytes (int | None): Source file size in bytes.
        is_cog_compliant (bool): Whether the source file is already a Cloud-Optimized GeoTIFF.
        compliance_reason (str): Explanation of COG compliance status. Lists missing requirements when not compliant.
        temporal_start (datetime.datetime | None | Unset): ISO 8601 acquisition timestamp parsed from raster metadata,
            if present.
    """

    job_id: UUID
    source_filename: None | str
    crs_epsg: int | None
    crs_wkt: None | str
    band_count: int
    width: int
    height: int
    dtype: str
    nodata: float | None | str
    res_x: float
    res_y: float
    compression: None | str
    file_size_bytes: int | None
    is_cog_compliant: bool
    compliance_reason: str
    temporal_start: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        job_id = str(self.job_id)

        source_filename: None | str
        source_filename = self.source_filename

        crs_epsg: int | None
        crs_epsg = self.crs_epsg

        crs_wkt: None | str
        crs_wkt = self.crs_wkt

        band_count = self.band_count

        width = self.width

        height = self.height

        dtype = self.dtype

        nodata: float | None | str
        nodata = self.nodata

        res_x = self.res_x

        res_y = self.res_y

        compression: None | str
        compression = self.compression

        file_size_bytes: int | None
        file_size_bytes = self.file_size_bytes

        is_cog_compliant = self.is_cog_compliant

        compliance_reason = self.compliance_reason

        temporal_start: None | str | Unset
        if isinstance(self.temporal_start, Unset):
            temporal_start = UNSET
        elif isinstance(self.temporal_start, datetime.datetime):
            temporal_start = self.temporal_start.isoformat()
        else:
            temporal_start = self.temporal_start

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "job_id": job_id,
                "source_filename": source_filename,
                "crs_epsg": crs_epsg,
                "crs_wkt": crs_wkt,
                "band_count": band_count,
                "width": width,
                "height": height,
                "dtype": dtype,
                "nodata": nodata,
                "res_x": res_x,
                "res_y": res_y,
                "compression": compression,
                "file_size_bytes": file_size_bytes,
                "is_cog_compliant": is_cog_compliant,
                "compliance_reason": compliance_reason,
            }
        )
        if temporal_start is not UNSET:
            field_dict["temporal_start"] = temporal_start

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

        def _parse_crs_epsg(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        crs_epsg = _parse_crs_epsg(d.pop("crs_epsg"))

        def _parse_crs_wkt(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        crs_wkt = _parse_crs_wkt(d.pop("crs_wkt"))

        band_count = d.pop("band_count")

        width = d.pop("width")

        height = d.pop("height")

        dtype = d.pop("dtype")

        def _parse_nodata(data: object) -> float | None | str:
            if data is None:
                return data
            return cast(float | None | str, data)

        nodata = _parse_nodata(d.pop("nodata"))

        res_x = d.pop("res_x")

        res_y = d.pop("res_y")

        def _parse_compression(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        compression = _parse_compression(d.pop("compression"))

        def _parse_file_size_bytes(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        file_size_bytes = _parse_file_size_bytes(d.pop("file_size_bytes"))

        is_cog_compliant = d.pop("is_cog_compliant")

        compliance_reason = d.pop("compliance_reason")

        def _parse_temporal_start(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                temporal_start_type_0 = isoparse(data)

                return temporal_start_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        temporal_start = _parse_temporal_start(d.pop("temporal_start", UNSET))

        raster_preview_response = cls(
            job_id=job_id,
            source_filename=source_filename,
            crs_epsg=crs_epsg,
            crs_wkt=crs_wkt,
            band_count=band_count,
            width=width,
            height=height,
            dtype=dtype,
            nodata=nodata,
            res_x=res_x,
            res_y=res_y,
            compression=compression,
            file_size_bytes=file_size_bytes,
            is_cog_compliant=is_cog_compliant,
            compliance_reason=compliance_reason,
            temporal_start=temporal_start,
        )

        raster_preview_response.additional_properties = d
        return raster_preview_response

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
