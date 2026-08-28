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
        id (str): STAC item ID.
        title (str): Title to use for the GeoLens dataset.
        data_asset_href (str): URL of the COG asset to reference.
        collection (None | str | Unset): Parent collection ID.
        item_href (None | str | Unset): The item's own canonical URL, echoed from search results.
        data_asset_key (None | str | Unset): The asset key on the item, echoed from search results.
        data_asset_type (None | str | Unset): Media type of the data asset, echoed from search results.
        bbox (list[float] | None | Unset): Item bounding box.
        epsg (int | None | Unset): EPSG code.
        datetime_start (None | str | Unset): Temporal start.
        datetime_end (None | str | Unset): Temporal end.
        keywords (list[str] | Unset): Keywords from STAC collection.
    """

    id: str
    title: str
    data_asset_href: str
    collection: None | str | Unset = UNSET
    item_href: None | str | Unset = UNSET
    data_asset_key: None | str | Unset = UNSET
    data_asset_type: None | str | Unset = UNSET
    bbox: list[float] | None | Unset = UNSET
    epsg: int | None | Unset = UNSET
    datetime_start: None | str | Unset = UNSET
    datetime_end: None | str | Unset = UNSET
    keywords: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        title = self.title

        data_asset_href = self.data_asset_href

        collection: None | str | Unset
        if isinstance(self.collection, Unset):
            collection = UNSET
        else:
            collection = self.collection

        item_href: None | str | Unset
        if isinstance(self.item_href, Unset):
            item_href = UNSET
        else:
            item_href = self.item_href

        data_asset_key: None | str | Unset
        if isinstance(self.data_asset_key, Unset):
            data_asset_key = UNSET
        else:
            data_asset_key = self.data_asset_key

        data_asset_type: None | str | Unset
        if isinstance(self.data_asset_type, Unset):
            data_asset_type = UNSET
        else:
            data_asset_type = self.data_asset_type

        bbox: list[float] | None | Unset
        if isinstance(self.bbox, Unset):
            bbox = UNSET
        elif isinstance(self.bbox, list):
            bbox = self.bbox

        else:
            bbox = self.bbox

        epsg: int | None | Unset
        if isinstance(self.epsg, Unset):
            epsg = UNSET
        else:
            epsg = self.epsg

        datetime_start: None | str | Unset
        if isinstance(self.datetime_start, Unset):
            datetime_start = UNSET
        else:
            datetime_start = self.datetime_start

        datetime_end: None | str | Unset
        if isinstance(self.datetime_end, Unset):
            datetime_end = UNSET
        else:
            datetime_end = self.datetime_end

        keywords: list[str] | Unset = UNSET
        if not isinstance(self.keywords, Unset):
            keywords = self.keywords

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "title": title,
                "data_asset_href": data_asset_href,
            }
        )
        if collection is not UNSET:
            field_dict["collection"] = collection
        if item_href is not UNSET:
            field_dict["item_href"] = item_href
        if data_asset_key is not UNSET:
            field_dict["data_asset_key"] = data_asset_key
        if data_asset_type is not UNSET:
            field_dict["data_asset_type"] = data_asset_type
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if epsg is not UNSET:
            field_dict["epsg"] = epsg
        if datetime_start is not UNSET:
            field_dict["datetime_start"] = datetime_start
        if datetime_end is not UNSET:
            field_dict["datetime_end"] = datetime_end
        if keywords is not UNSET:
            field_dict["keywords"] = keywords

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        title = d.pop("title")

        data_asset_href = d.pop("data_asset_href")

        def _parse_collection(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        collection = _parse_collection(d.pop("collection", UNSET))

        def _parse_item_href(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        item_href = _parse_item_href(d.pop("item_href", UNSET))

        def _parse_data_asset_key(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        data_asset_key = _parse_data_asset_key(d.pop("data_asset_key", UNSET))

        def _parse_data_asset_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        data_asset_type = _parse_data_asset_type(d.pop("data_asset_type", UNSET))

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

        def _parse_epsg(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        epsg = _parse_epsg(d.pop("epsg", UNSET))

        def _parse_datetime_start(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        datetime_start = _parse_datetime_start(d.pop("datetime_start", UNSET))

        def _parse_datetime_end(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        datetime_end = _parse_datetime_end(d.pop("datetime_end", UNSET))

        keywords = cast(list[str], d.pop("keywords", UNSET))

        stac_import_item = cls(
            id=id,
            title=title,
            data_asset_href=data_asset_href,
            collection=collection,
            item_href=item_href,
            data_asset_key=data_asset_key,
            data_asset_type=data_asset_type,
            bbox=bbox,
            epsg=epsg,
            datetime_start=datetime_start,
            datetime_end=datetime_end,
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
