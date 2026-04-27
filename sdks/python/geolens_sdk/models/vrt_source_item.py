from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID


T = TypeVar("T", bound="VrtSourceItem")


@_attrs_define
class VrtSourceItem:
    """
    Attributes:
        dataset_id (UUID):
        position (int):
        title (str):
        band_count (int | None | Unset):
        crs_epsg (int | None | Unset):
        extent_bbox (list[float] | None | Unset):
        resolution_x (float | None | Unset):
        resolution_y (float | None | Unset):
    """

    dataset_id: UUID
    position: int
    title: str
    band_count: int | None | Unset = UNSET
    crs_epsg: int | None | Unset = UNSET
    extent_bbox: list[float] | None | Unset = UNSET
    resolution_x: float | None | Unset = UNSET
    resolution_y: float | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        dataset_id = str(self.dataset_id)

        position = self.position

        title = self.title

        band_count: int | None | Unset
        if isinstance(self.band_count, Unset):
            band_count = UNSET
        else:
            band_count = self.band_count

        crs_epsg: int | None | Unset
        if isinstance(self.crs_epsg, Unset):
            crs_epsg = UNSET
        else:
            crs_epsg = self.crs_epsg

        extent_bbox: list[float] | None | Unset
        if isinstance(self.extent_bbox, Unset):
            extent_bbox = UNSET
        elif isinstance(self.extent_bbox, list):
            extent_bbox = self.extent_bbox

        else:
            extent_bbox = self.extent_bbox

        resolution_x: float | None | Unset
        if isinstance(self.resolution_x, Unset):
            resolution_x = UNSET
        else:
            resolution_x = self.resolution_x

        resolution_y: float | None | Unset
        if isinstance(self.resolution_y, Unset):
            resolution_y = UNSET
        else:
            resolution_y = self.resolution_y

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dataset_id": dataset_id,
                "position": position,
                "title": title,
            }
        )
        if band_count is not UNSET:
            field_dict["band_count"] = band_count
        if crs_epsg is not UNSET:
            field_dict["crs_epsg"] = crs_epsg
        if extent_bbox is not UNSET:
            field_dict["extent_bbox"] = extent_bbox
        if resolution_x is not UNSET:
            field_dict["resolution_x"] = resolution_x
        if resolution_y is not UNSET:
            field_dict["resolution_y"] = resolution_y

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        dataset_id = UUID(d.pop("dataset_id"))

        position = d.pop("position")

        title = d.pop("title")

        def _parse_band_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        band_count = _parse_band_count(d.pop("band_count", UNSET))

        def _parse_crs_epsg(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        crs_epsg = _parse_crs_epsg(d.pop("crs_epsg", UNSET))

        def _parse_extent_bbox(data: object) -> list[float] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                extent_bbox_type_0 = cast(list[float], data)

                return extent_bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None | Unset, data)

        extent_bbox = _parse_extent_bbox(d.pop("extent_bbox", UNSET))

        def _parse_resolution_x(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        resolution_x = _parse_resolution_x(d.pop("resolution_x", UNSET))

        def _parse_resolution_y(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        resolution_y = _parse_resolution_y(d.pop("resolution_y", UNSET))

        vrt_source_item = cls(
            dataset_id=dataset_id,
            position=position,
            title=title,
            band_count=band_count,
            crs_epsg=crs_epsg,
            extent_bbox=extent_bbox,
            resolution_x=resolution_x,
            resolution_y=resolution_y,
        )

        vrt_source_item.additional_properties = d
        return vrt_source_item

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
