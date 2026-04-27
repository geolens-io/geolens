from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="RasterBandInfo")


@_attrs_define
class RasterBandInfo:
    """
    Attributes:
        dtype (str): Pixel data type, e.g. uint8, float32
        index (int): 1-based band index
        color_interp (None | str | Unset): Color interpretation, e.g. Red, Green, Gray
        nodata (None | str | Unset): Nodata sentinel value for this band
    """

    dtype: str
    index: int
    color_interp: None | str | Unset = UNSET
    nodata: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        dtype = self.dtype

        index = self.index

        color_interp: None | str | Unset
        if isinstance(self.color_interp, Unset):
            color_interp = UNSET
        else:
            color_interp = self.color_interp

        nodata: None | str | Unset
        if isinstance(self.nodata, Unset):
            nodata = UNSET
        else:
            nodata = self.nodata

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dtype": dtype,
                "index": index,
            }
        )
        if color_interp is not UNSET:
            field_dict["color_interp"] = color_interp
        if nodata is not UNSET:
            field_dict["nodata"] = nodata

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        dtype = d.pop("dtype")

        index = d.pop("index")

        def _parse_color_interp(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        color_interp = _parse_color_interp(d.pop("color_interp", UNSET))

        def _parse_nodata(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        nodata = _parse_nodata(d.pop("nodata", UNSET))

        raster_band_info = cls(
            dtype=dtype,
            index=index,
            color_interp=color_interp,
            nodata=nodata,
        )

        raster_band_info.additional_properties = d
        return raster_band_info

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
