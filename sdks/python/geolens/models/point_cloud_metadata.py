from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="PointCloudMetadata")


@_attrs_define
class PointCloudMetadata:
    """A COPC point cloud's published file.

    Attributes:
        size_bytes (int | None | Unset): Size of the COPC file in bytes
        point_count (int | None | Unset): Number of points, from the file's header
        point_format (int | None | Unset): LAS point data record format: 6 (no colour), 7 (RGB) or 8 (RGB and near
            infrared)
        vertical_crs (None | str | Unset): Name of the file's vertical CRS, when its WKT gives one
    """

    size_bytes: int | None | Unset = UNSET
    point_count: int | None | Unset = UNSET
    point_format: int | None | Unset = UNSET
    vertical_crs: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        size_bytes: int | None | Unset
        if isinstance(self.size_bytes, Unset):
            size_bytes = UNSET
        else:
            size_bytes = self.size_bytes

        point_count: int | None | Unset
        if isinstance(self.point_count, Unset):
            point_count = UNSET
        else:
            point_count = self.point_count

        point_format: int | None | Unset
        if isinstance(self.point_format, Unset):
            point_format = UNSET
        else:
            point_format = self.point_format

        vertical_crs: None | str | Unset
        if isinstance(self.vertical_crs, Unset):
            vertical_crs = UNSET
        else:
            vertical_crs = self.vertical_crs

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if size_bytes is not UNSET:
            field_dict["size_bytes"] = size_bytes
        if point_count is not UNSET:
            field_dict["point_count"] = point_count
        if point_format is not UNSET:
            field_dict["point_format"] = point_format
        if vertical_crs is not UNSET:
            field_dict["vertical_crs"] = vertical_crs

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_size_bytes(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        size_bytes = _parse_size_bytes(d.pop("size_bytes", UNSET))

        def _parse_point_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        point_count = _parse_point_count(d.pop("point_count", UNSET))

        def _parse_point_format(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        point_format = _parse_point_format(d.pop("point_format", UNSET))

        def _parse_vertical_crs(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        vertical_crs = _parse_vertical_crs(d.pop("vertical_crs", UNSET))

        point_cloud_metadata = cls(
            size_bytes=size_bytes,
            point_count=point_count,
            point_format=point_format,
            vertical_crs=vertical_crs,
        )

        point_cloud_metadata.additional_properties = d
        return point_cloud_metadata

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
