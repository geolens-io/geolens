from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="ManifestDatasetLinks")


@_attrs_define
class ManifestDatasetLinks:
    """Absolute links to a dataset, each one a route the server serves.

    Attributes:
        page (str): The dataset's page in the web app.
        items (None | str | Unset): The OGC API Features items. Null for a dataset with no items.
        tiles (None | str | Unset): The vector tile URL template, with {z}, {x} and {y}. Null for a dataset with no
            vector tiles, and while a job is still writing the dataset (queued, running or held): read the template again
            once it completes. A private dataset's tiles need the caller's API key header.
    """

    page: str
    items: None | str | Unset = UNSET
    tiles: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        page = self.page

        items: None | str | Unset
        if isinstance(self.items, Unset):
            items = UNSET
        else:
            items = self.items

        tiles: None | str | Unset
        if isinstance(self.tiles, Unset):
            tiles = UNSET
        else:
            tiles = self.tiles

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "page": page,
            }
        )
        if items is not UNSET:
            field_dict["items"] = items
        if tiles is not UNSET:
            field_dict["tiles"] = tiles

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        page = d.pop("page")

        def _parse_items(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        items = _parse_items(d.pop("items", UNSET))

        def _parse_tiles(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        tiles = _parse_tiles(d.pop("tiles", UNSET))

        manifest_dataset_links = cls(
            page=page,
            items=items,
            tiles=tiles,
        )

        manifest_dataset_links.additional_properties = d
        return manifest_dataset_links

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
