from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.ogc_raster_band_statistics_type_0 import OGCRasterBandStatisticsType0


T = TypeVar("T", bound="OGCRasterBand")


@_attrs_define
class OGCRasterBand:
    """One entry in the raster:bands STAC extension array.

    fix(#1805 review round 3 P2): matches the shape service_records.py
    actually serializes per band. `statistics` matches the normalized
    band_info shape core/raster_bands.py (introduced by #1803, the raster
    lifecycle PR) produces on read; keep this in sync if that PR changes
    the per-band keys.

        Attributes:
            name (None | str | Unset):
            data_type (None | str | Unset):
            nodata (float | int | None | str | Unset):
            statistics (None | OGCRasterBandStatisticsType0 | Unset):
            description (None | str | Unset):
    """

    name: None | str | Unset = UNSET
    data_type: None | str | Unset = UNSET
    nodata: float | int | None | str | Unset = UNSET
    statistics: None | OGCRasterBandStatisticsType0 | Unset = UNSET
    description: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.ogc_raster_band_statistics_type_0 import (
            OGCRasterBandStatisticsType0,
        )

        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        data_type: None | str | Unset
        if isinstance(self.data_type, Unset):
            data_type = UNSET
        else:
            data_type = self.data_type

        nodata: float | int | None | str | Unset
        if isinstance(self.nodata, Unset):
            nodata = UNSET
        else:
            nodata = self.nodata

        statistics: dict[str, Any] | None | Unset
        if isinstance(self.statistics, Unset):
            statistics = UNSET
        elif isinstance(self.statistics, OGCRasterBandStatisticsType0):
            statistics = self.statistics.to_dict()
        else:
            statistics = self.statistics

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if name is not UNSET:
            field_dict["name"] = name
        if data_type is not UNSET:
            field_dict["data_type"] = data_type
        if nodata is not UNSET:
            field_dict["nodata"] = nodata
        if statistics is not UNSET:
            field_dict["statistics"] = statistics
        if description is not UNSET:
            field_dict["description"] = description

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ogc_raster_band_statistics_type_0 import (
            OGCRasterBandStatisticsType0,
        )

        d = dict(src_dict)

        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))

        def _parse_data_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        data_type = _parse_data_type(d.pop("data_type", UNSET))

        def _parse_nodata(data: object) -> float | int | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | int | None | str | Unset, data)

        nodata = _parse_nodata(d.pop("nodata", UNSET))

        def _parse_statistics(
            data: object,
        ) -> None | OGCRasterBandStatisticsType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                statistics_type_0 = OGCRasterBandStatisticsType0.from_dict(data)

                return statistics_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OGCRasterBandStatisticsType0 | Unset, data)

        statistics = _parse_statistics(d.pop("statistics", UNSET))

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        ogc_raster_band = cls(
            name=name,
            data_type=data_type,
            nodata=nodata,
            statistics=statistics,
            description=description,
        )

        ogc_raster_band.additional_properties = d
        return ogc_raster_band

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
