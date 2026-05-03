from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.raster_band_info import RasterBandInfo
    from ..models.raster_connect import RasterConnect


T = TypeVar("T", bound="RasterMetadata")


@_attrs_define
class RasterMetadata:
    """
    Attributes:
        band_count (int | None | Unset):
        bands (list[RasterBandInfo] | Unset):
        compression (None | str | Unset): Internal compression, e.g. DEFLATE, LZW
        connect (None | RasterConnect | Unset):
        epsg (int | None | Unset): EPSG code of the raster CRS
        height (int | None | Unset): Raster height in pixels
        nodata (None | str | Unset): Global nodata sentinel value
        res_x (float | None | Unset): Pixel resolution in X (CRS units)
        res_y (float | None | Unset): Pixel resolution in Y (CRS units)
        resolution_strategy (None | str | Unset): VRT resolution strategy, e.g. highest, average
        size_bytes (int | None | Unset): File size on disk in bytes
        source_count (int | None | Unset): Number of source rasters in a VRT mosaic
        status (None | str | Unset): Processing status, e.g. ready, failed
        tile_url (None | str | Unset): Titiler XYZ tile endpoint
        vrt_type (None | str | Unset): VRT variant: mosaic or timeseries
        width (int | None | Unset): Raster width in pixels
    """

    band_count: int | None | Unset = UNSET
    bands: list[RasterBandInfo] | Unset = UNSET
    compression: None | str | Unset = UNSET
    connect: None | RasterConnect | Unset = UNSET
    epsg: int | None | Unset = UNSET
    height: int | None | Unset = UNSET
    nodata: None | str | Unset = UNSET
    res_x: float | None | Unset = UNSET
    res_y: float | None | Unset = UNSET
    resolution_strategy: None | str | Unset = UNSET
    size_bytes: int | None | Unset = UNSET
    source_count: int | None | Unset = UNSET
    status: None | str | Unset = UNSET
    tile_url: None | str | Unset = UNSET
    vrt_type: None | str | Unset = UNSET
    width: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.raster_connect import RasterConnect

        band_count: int | None | Unset
        if isinstance(self.band_count, Unset):
            band_count = UNSET
        else:
            band_count = self.band_count

        bands: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.bands, Unset):
            bands = []
            for bands_item_data in self.bands:
                bands_item = bands_item_data.to_dict()
                bands.append(bands_item)

        compression: None | str | Unset
        if isinstance(self.compression, Unset):
            compression = UNSET
        else:
            compression = self.compression

        connect: dict[str, Any] | None | Unset
        if isinstance(self.connect, Unset):
            connect = UNSET
        elif isinstance(self.connect, RasterConnect):
            connect = self.connect.to_dict()
        else:
            connect = self.connect

        epsg: int | None | Unset
        if isinstance(self.epsg, Unset):
            epsg = UNSET
        else:
            epsg = self.epsg

        height: int | None | Unset
        if isinstance(self.height, Unset):
            height = UNSET
        else:
            height = self.height

        nodata: None | str | Unset
        if isinstance(self.nodata, Unset):
            nodata = UNSET
        else:
            nodata = self.nodata

        res_x: float | None | Unset
        if isinstance(self.res_x, Unset):
            res_x = UNSET
        else:
            res_x = self.res_x

        res_y: float | None | Unset
        if isinstance(self.res_y, Unset):
            res_y = UNSET
        else:
            res_y = self.res_y

        resolution_strategy: None | str | Unset
        if isinstance(self.resolution_strategy, Unset):
            resolution_strategy = UNSET
        else:
            resolution_strategy = self.resolution_strategy

        size_bytes: int | None | Unset
        if isinstance(self.size_bytes, Unset):
            size_bytes = UNSET
        else:
            size_bytes = self.size_bytes

        source_count: int | None | Unset
        if isinstance(self.source_count, Unset):
            source_count = UNSET
        else:
            source_count = self.source_count

        status: None | str | Unset
        if isinstance(self.status, Unset):
            status = UNSET
        else:
            status = self.status

        tile_url: None | str | Unset
        if isinstance(self.tile_url, Unset):
            tile_url = UNSET
        else:
            tile_url = self.tile_url

        vrt_type: None | str | Unset
        if isinstance(self.vrt_type, Unset):
            vrt_type = UNSET
        else:
            vrt_type = self.vrt_type

        width: int | None | Unset
        if isinstance(self.width, Unset):
            width = UNSET
        else:
            width = self.width

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if band_count is not UNSET:
            field_dict["band_count"] = band_count
        if bands is not UNSET:
            field_dict["bands"] = bands
        if compression is not UNSET:
            field_dict["compression"] = compression
        if connect is not UNSET:
            field_dict["connect"] = connect
        if epsg is not UNSET:
            field_dict["epsg"] = epsg
        if height is not UNSET:
            field_dict["height"] = height
        if nodata is not UNSET:
            field_dict["nodata"] = nodata
        if res_x is not UNSET:
            field_dict["res_x"] = res_x
        if res_y is not UNSET:
            field_dict["res_y"] = res_y
        if resolution_strategy is not UNSET:
            field_dict["resolution_strategy"] = resolution_strategy
        if size_bytes is not UNSET:
            field_dict["size_bytes"] = size_bytes
        if source_count is not UNSET:
            field_dict["source_count"] = source_count
        if status is not UNSET:
            field_dict["status"] = status
        if tile_url is not UNSET:
            field_dict["tile_url"] = tile_url
        if vrt_type is not UNSET:
            field_dict["vrt_type"] = vrt_type
        if width is not UNSET:
            field_dict["width"] = width

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.raster_band_info import RasterBandInfo
        from ..models.raster_connect import RasterConnect

        d = dict(src_dict)

        def _parse_band_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        band_count = _parse_band_count(d.pop("band_count", UNSET))

        _bands = d.pop("bands", UNSET)
        bands: list[RasterBandInfo] | Unset = UNSET
        if _bands is not UNSET:
            bands = []
            for bands_item_data in _bands:
                bands_item = RasterBandInfo.from_dict(bands_item_data)

                bands.append(bands_item)

        def _parse_compression(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        compression = _parse_compression(d.pop("compression", UNSET))

        def _parse_connect(data: object) -> None | RasterConnect | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                connect_type_0 = RasterConnect.from_dict(data)

                return connect_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RasterConnect | Unset, data)

        connect = _parse_connect(d.pop("connect", UNSET))

        def _parse_epsg(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        epsg = _parse_epsg(d.pop("epsg", UNSET))

        def _parse_height(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        height = _parse_height(d.pop("height", UNSET))

        def _parse_nodata(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        nodata = _parse_nodata(d.pop("nodata", UNSET))

        def _parse_res_x(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        res_x = _parse_res_x(d.pop("res_x", UNSET))

        def _parse_res_y(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        res_y = _parse_res_y(d.pop("res_y", UNSET))

        def _parse_resolution_strategy(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        resolution_strategy = _parse_resolution_strategy(
            d.pop("resolution_strategy", UNSET)
        )

        def _parse_size_bytes(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        size_bytes = _parse_size_bytes(d.pop("size_bytes", UNSET))

        def _parse_source_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        source_count = _parse_source_count(d.pop("source_count", UNSET))

        def _parse_status(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        status = _parse_status(d.pop("status", UNSET))

        def _parse_tile_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        tile_url = _parse_tile_url(d.pop("tile_url", UNSET))

        def _parse_vrt_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        vrt_type = _parse_vrt_type(d.pop("vrt_type", UNSET))

        def _parse_width(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        width = _parse_width(d.pop("width", UNSET))

        raster_metadata = cls(
            band_count=band_count,
            bands=bands,
            compression=compression,
            connect=connect,
            epsg=epsg,
            height=height,
            nodata=nodata,
            res_x=res_x,
            res_y=res_y,
            resolution_strategy=resolution_strategy,
            size_bytes=size_bytes,
            source_count=source_count,
            status=status,
            tile_url=tile_url,
            vrt_type=vrt_type,
            width=width,
        )

        raster_metadata.additional_properties = d
        return raster_metadata

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
