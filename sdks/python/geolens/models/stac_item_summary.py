from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="StacItemSummary")


@_attrs_define
class StacItemSummary:
    """
    Attributes:
        asset_count (int): Number of assets on this item.
        id (str): Item identifier.
        title (str): Item title (falls back to ID).
        bbox (list[float] | None | Unset): Item bounding box.
        cloud_cover (float | None | Unset): Cloud cover percentage (eo extension).
        collection (None | str | Unset): Parent collection ID.
        data_asset_href (None | str | Unset): URL of the primary data asset (COG).
        data_asset_size_bytes (int | None | Unset): Size of the primary data asset in bytes (from STAC file:size). None
            when not in manifest.
        data_asset_type (None | str | Unset): Media type of the data asset.
        datetime_ (None | str | Unset): Primary datetime (ISO 8601).
        datetime_end (None | str | Unset): End datetime for ranges.
        datetime_start (None | str | Unset): Start datetime for ranges.
        epsg (int | None | Unset): EPSG code from proj extension.
        gsd (float | None | Unset): Ground sample distance in meters.
        thumbnail_href (None | str | Unset): Thumbnail URL if available.
    """

    asset_count: int
    id: str
    title: str
    bbox: list[float] | None | Unset = UNSET
    cloud_cover: float | None | Unset = UNSET
    collection: None | str | Unset = UNSET
    data_asset_href: None | str | Unset = UNSET
    data_asset_size_bytes: int | None | Unset = UNSET
    data_asset_type: None | str | Unset = UNSET
    datetime_: None | str | Unset = UNSET
    datetime_end: None | str | Unset = UNSET
    datetime_start: None | str | Unset = UNSET
    epsg: int | None | Unset = UNSET
    gsd: float | None | Unset = UNSET
    thumbnail_href: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        asset_count = self.asset_count

        id = self.id

        title = self.title

        bbox: list[float] | None | Unset
        if isinstance(self.bbox, Unset):
            bbox = UNSET
        elif isinstance(self.bbox, list):
            bbox = self.bbox

        else:
            bbox = self.bbox

        cloud_cover: float | None | Unset
        if isinstance(self.cloud_cover, Unset):
            cloud_cover = UNSET
        else:
            cloud_cover = self.cloud_cover

        collection: None | str | Unset
        if isinstance(self.collection, Unset):
            collection = UNSET
        else:
            collection = self.collection

        data_asset_href: None | str | Unset
        if isinstance(self.data_asset_href, Unset):
            data_asset_href = UNSET
        else:
            data_asset_href = self.data_asset_href

        data_asset_size_bytes: int | None | Unset
        if isinstance(self.data_asset_size_bytes, Unset):
            data_asset_size_bytes = UNSET
        else:
            data_asset_size_bytes = self.data_asset_size_bytes

        data_asset_type: None | str | Unset
        if isinstance(self.data_asset_type, Unset):
            data_asset_type = UNSET
        else:
            data_asset_type = self.data_asset_type

        datetime_: None | str | Unset
        if isinstance(self.datetime_, Unset):
            datetime_ = UNSET
        else:
            datetime_ = self.datetime_

        datetime_end: None | str | Unset
        if isinstance(self.datetime_end, Unset):
            datetime_end = UNSET
        else:
            datetime_end = self.datetime_end

        datetime_start: None | str | Unset
        if isinstance(self.datetime_start, Unset):
            datetime_start = UNSET
        else:
            datetime_start = self.datetime_start

        epsg: int | None | Unset
        if isinstance(self.epsg, Unset):
            epsg = UNSET
        else:
            epsg = self.epsg

        gsd: float | None | Unset
        if isinstance(self.gsd, Unset):
            gsd = UNSET
        else:
            gsd = self.gsd

        thumbnail_href: None | str | Unset
        if isinstance(self.thumbnail_href, Unset):
            thumbnail_href = UNSET
        else:
            thumbnail_href = self.thumbnail_href

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "asset_count": asset_count,
                "id": id,
                "title": title,
            }
        )
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if cloud_cover is not UNSET:
            field_dict["cloud_cover"] = cloud_cover
        if collection is not UNSET:
            field_dict["collection"] = collection
        if data_asset_href is not UNSET:
            field_dict["data_asset_href"] = data_asset_href
        if data_asset_size_bytes is not UNSET:
            field_dict["data_asset_size_bytes"] = data_asset_size_bytes
        if data_asset_type is not UNSET:
            field_dict["data_asset_type"] = data_asset_type
        if datetime_ is not UNSET:
            field_dict["datetime"] = datetime_
        if datetime_end is not UNSET:
            field_dict["datetime_end"] = datetime_end
        if datetime_start is not UNSET:
            field_dict["datetime_start"] = datetime_start
        if epsg is not UNSET:
            field_dict["epsg"] = epsg
        if gsd is not UNSET:
            field_dict["gsd"] = gsd
        if thumbnail_href is not UNSET:
            field_dict["thumbnail_href"] = thumbnail_href

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        asset_count = d.pop("asset_count")

        id = d.pop("id")

        title = d.pop("title")

        def _parse_bbox(data: object) -> list[float] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                bbox_type_0 = cast(list[float], data)

                return bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None | Unset, data)

        bbox = _parse_bbox(d.pop("bbox", UNSET))

        def _parse_cloud_cover(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        cloud_cover = _parse_cloud_cover(d.pop("cloud_cover", UNSET))

        def _parse_collection(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        collection = _parse_collection(d.pop("collection", UNSET))

        def _parse_data_asset_href(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        data_asset_href = _parse_data_asset_href(d.pop("data_asset_href", UNSET))

        def _parse_data_asset_size_bytes(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        data_asset_size_bytes = _parse_data_asset_size_bytes(
            d.pop("data_asset_size_bytes", UNSET)
        )

        def _parse_data_asset_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        data_asset_type = _parse_data_asset_type(d.pop("data_asset_type", UNSET))

        def _parse_datetime_(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        datetime_ = _parse_datetime_(d.pop("datetime", UNSET))

        def _parse_datetime_end(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        datetime_end = _parse_datetime_end(d.pop("datetime_end", UNSET))

        def _parse_datetime_start(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        datetime_start = _parse_datetime_start(d.pop("datetime_start", UNSET))

        def _parse_epsg(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        epsg = _parse_epsg(d.pop("epsg", UNSET))

        def _parse_gsd(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        gsd = _parse_gsd(d.pop("gsd", UNSET))

        def _parse_thumbnail_href(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        thumbnail_href = _parse_thumbnail_href(d.pop("thumbnail_href", UNSET))

        stac_item_summary = cls(
            asset_count=asset_count,
            id=id,
            title=title,
            bbox=bbox,
            cloud_cover=cloud_cover,
            collection=collection,
            data_asset_href=data_asset_href,
            data_asset_size_bytes=data_asset_size_bytes,
            data_asset_type=data_asset_type,
            datetime_=datetime_,
            datetime_end=datetime_end,
            datetime_start=datetime_start,
            epsg=epsg,
            gsd=gsd,
            thumbnail_href=thumbnail_href,
        )

        stac_item_summary.additional_properties = d
        return stac_item_summary

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
