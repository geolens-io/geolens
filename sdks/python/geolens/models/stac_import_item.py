from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="StacImportItem")


@_attrs_define
class StacImportItem:
    """
    Attributes:
        data_asset_href (str): URL of the COG asset to reference.
        id (str): STAC item ID.
        title (str): Title to use for the GeoLens dataset.
        bbox (list[float] | None | Unset): Item bounding box.
        collection (None | str | Unset): Parent collection ID.
        datetime_end (None | str | Unset): Temporal end.
        datetime_start (None | str | Unset): Temporal start.
        epsg (int | None | Unset): EPSG code.
        keywords (list[str] | Unset): Keywords from STAC collection.
    """

    data_asset_href: str
    id: str
    title: str
    bbox: list[float] | None | Unset = UNSET
    collection: None | str | Unset = UNSET
    datetime_end: None | str | Unset = UNSET
    datetime_start: None | str | Unset = UNSET
    epsg: int | None | Unset = UNSET
    keywords: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data_asset_href = self.data_asset_href

        id = self.id

        title = self.title

        bbox: list[float] | None | Unset
        if isinstance(self.bbox, Unset):
            bbox = UNSET
        elif isinstance(self.bbox, list):
            bbox = self.bbox

        else:
            bbox = self.bbox

        collection: None | str | Unset
        if isinstance(self.collection, Unset):
            collection = UNSET
        else:
            collection = self.collection

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

        keywords: list[str] | Unset = UNSET
        if not isinstance(self.keywords, Unset):
            keywords = self.keywords

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "data_asset_href": data_asset_href,
                "id": id,
                "title": title,
            }
        )
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if collection is not UNSET:
            field_dict["collection"] = collection
        if datetime_end is not UNSET:
            field_dict["datetime_end"] = datetime_end
        if datetime_start is not UNSET:
            field_dict["datetime_start"] = datetime_start
        if epsg is not UNSET:
            field_dict["epsg"] = epsg
        if keywords is not UNSET:
            field_dict["keywords"] = keywords

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        data_asset_href = d.pop("data_asset_href")

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

        def _parse_collection(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        collection = _parse_collection(d.pop("collection", UNSET))

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

        keywords = cast(list[str], d.pop("keywords", UNSET))

        stac_import_item = cls(
            data_asset_href=data_asset_href,
            id=id,
            title=title,
            bbox=bbox,
            collection=collection,
            datetime_end=datetime_end,
            datetime_start=datetime_start,
            epsg=epsg,
            keywords=keywords,
        )

        stac_import_item.additional_properties = d
        return stac_import_item

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
