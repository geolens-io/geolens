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
        band_count (int): Number of raster bands.
        compliance_reason (str): Explanation of COG compliance status. Lists missing requirements when not compliant.
        compression (None | str): Existing compression method (e.g. 'LZW', 'DEFLATE'), or null for uncompressed.
        crs_epsg (int | None): Detected EPSG code for the raster's CRS, if available.
        crs_wkt (None | str): Full WKT representation of the raster's CRS.
        dtype (str): Pixel data type (e.g. 'uint8', 'float32').
        file_size_bytes (int | None): Source file size in bytes.
        height (int): Raster height in pixels.
        is_cog_compliant (bool): Whether the source file is already a Cloud-Optimized GeoTIFF.
        job_id (UUID): Identifier of the raster ingestion job being previewed.
        nodata (float | None | str): Nodata value for the raster, if defined.
        res_x (float): Pixel resolution along the X axis in CRS units.
        res_y (float): Pixel resolution along the Y axis in CRS units.
        source_filename (None | str): Original filename of the uploaded raster file.
        width (int): Raster width in pixels.
        temporal_start (datetime.datetime | None | Unset): ISO 8601 acquisition timestamp parsed from raster metadata,
            if present.
    """

    band_count: int
    compliance_reason: str
    compression: None | str
    crs_epsg: int | None
    crs_wkt: None | str
    dtype: str
    file_size_bytes: int | None
    height: int
    is_cog_compliant: bool
    job_id: UUID
    nodata: float | None | str
    res_x: float
    res_y: float
    source_filename: None | str
    width: int
    temporal_start: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        band_count = self.band_count

        compliance_reason = self.compliance_reason

        compression: None | str
        compression = self.compression

        crs_epsg: int | None
        crs_epsg = self.crs_epsg

        crs_wkt: None | str
        crs_wkt = self.crs_wkt

        dtype = self.dtype

        file_size_bytes: int | None
        file_size_bytes = self.file_size_bytes

        height = self.height

        is_cog_compliant = self.is_cog_compliant

        job_id = str(self.job_id)

        nodata: float | None | str
        nodata = self.nodata

        res_x = self.res_x

        res_y = self.res_y

        source_filename: None | str
        source_filename = self.source_filename

        width = self.width

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
                "band_count": band_count,
                "compliance_reason": compliance_reason,
                "compression": compression,
                "crs_epsg": crs_epsg,
                "crs_wkt": crs_wkt,
                "dtype": dtype,
                "file_size_bytes": file_size_bytes,
                "height": height,
                "is_cog_compliant": is_cog_compliant,
                "job_id": job_id,
                "nodata": nodata,
                "res_x": res_x,
                "res_y": res_y,
                "source_filename": source_filename,
                "width": width,
            }
        )
        if temporal_start is not UNSET:
            field_dict["temporal_start"] = temporal_start

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        band_count = d.pop("band_count")

        compliance_reason = d.pop("compliance_reason")

        def _parse_compression(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        compression = _parse_compression(d.pop("compression"))

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

        dtype = d.pop("dtype")

        def _parse_file_size_bytes(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        file_size_bytes = _parse_file_size_bytes(d.pop("file_size_bytes"))

        height = d.pop("height")

        is_cog_compliant = d.pop("is_cog_compliant")

        job_id = UUID(d.pop("job_id"))

        def _parse_nodata(data: object) -> float | None | str:
            if data is None:
                return data
            return cast(float | None | str, data)

        nodata = _parse_nodata(d.pop("nodata"))

        res_x = d.pop("res_x")

        res_y = d.pop("res_y")

        def _parse_source_filename(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source_filename = _parse_source_filename(d.pop("source_filename"))

        width = d.pop("width")

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
            band_count=band_count,
            compliance_reason=compliance_reason,
            compression=compression,
            crs_epsg=crs_epsg,
            crs_wkt=crs_wkt,
            dtype=dtype,
            file_size_bytes=file_size_bytes,
            height=height,
            is_cog_compliant=is_cog_compliant,
            job_id=job_id,
            nodata=nodata,
            res_x=res_x,
            res_y=res_y,
            source_filename=source_filename,
            width=width,
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
