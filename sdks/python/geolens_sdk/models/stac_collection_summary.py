from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="StacCollectionSummary")


@_attrs_define
class StacCollectionSummary:
    """
    Attributes:
        description (str): Collection description.
        id (str): Collection identifier.
        title (str): Collection title.
        bbox (list[float] | None | Unset): Spatial extent as [west, south, east, north].
        item_count (int | None | Unset): Number of items if reported by the API.
        keywords (list[str] | Unset): Collection keywords.
        license_ (None | str | Unset): SPDX license identifier.
        temporal_end (None | str | Unset): End of temporal extent (ISO 8601).
        temporal_start (None | str | Unset): Start of temporal extent (ISO 8601).
    """

    description: str
    id: str
    title: str
    bbox: list[float] | None | Unset = UNSET
    item_count: int | None | Unset = UNSET
    keywords: list[str] | Unset = UNSET
    license_: None | str | Unset = UNSET
    temporal_end: None | str | Unset = UNSET
    temporal_start: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        description = self.description

        id = self.id

        title = self.title

        bbox: list[float] | None | Unset
        if isinstance(self.bbox, Unset):
            bbox = UNSET
        elif isinstance(self.bbox, list):
            bbox = self.bbox

        else:
            bbox = self.bbox

        item_count: int | None | Unset
        if isinstance(self.item_count, Unset):
            item_count = UNSET
        else:
            item_count = self.item_count

        keywords: list[str] | Unset = UNSET
        if not isinstance(self.keywords, Unset):
            keywords = self.keywords

        license_: None | str | Unset
        if isinstance(self.license_, Unset):
            license_ = UNSET
        else:
            license_ = self.license_

        temporal_end: None | str | Unset
        if isinstance(self.temporal_end, Unset):
            temporal_end = UNSET
        else:
            temporal_end = self.temporal_end

        temporal_start: None | str | Unset
        if isinstance(self.temporal_start, Unset):
            temporal_start = UNSET
        else:
            temporal_start = self.temporal_start

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "description": description,
                "id": id,
                "title": title,
            }
        )
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if item_count is not UNSET:
            field_dict["item_count"] = item_count
        if keywords is not UNSET:
            field_dict["keywords"] = keywords
        if license_ is not UNSET:
            field_dict["license"] = license_
        if temporal_end is not UNSET:
            field_dict["temporal_end"] = temporal_end
        if temporal_start is not UNSET:
            field_dict["temporal_start"] = temporal_start

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        description = d.pop("description")

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

        def _parse_item_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        item_count = _parse_item_count(d.pop("item_count", UNSET))

        keywords = cast(list[str], d.pop("keywords", UNSET))

        def _parse_license_(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        license_ = _parse_license_(d.pop("license", UNSET))

        def _parse_temporal_end(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        temporal_end = _parse_temporal_end(d.pop("temporal_end", UNSET))

        def _parse_temporal_start(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        temporal_start = _parse_temporal_start(d.pop("temporal_start", UNSET))

        stac_collection_summary = cls(
            description=description,
            id=id,
            title=title,
            bbox=bbox,
            item_count=item_count,
            keywords=keywords,
            license_=license_,
            temporal_end=temporal_end,
            temporal_start=temporal_start,
        )

        stac_collection_summary.additional_properties = d
        return stac_collection_summary

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
