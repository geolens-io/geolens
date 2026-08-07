from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.ogc_link import OGCLink


T = TypeVar("T", bound="LandingPage")


@_attrs_define
class LandingPage:
    """
    Attributes:
        title (str): OGC API landing page title.
        description (str): Human-readable API description.
        links (list[OGCLink]): Top-level navigation links to conformance, collections, and API document.
    """

    title: str
    description: str
    links: list[OGCLink]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        title = self.title

        description = self.description

        links = []
        for links_item_data in self.links:
            links_item = links_item_data.to_dict()
            links.append(links_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "title": title,
                "description": description,
                "links": links,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ogc_link import OGCLink

        d = dict(src_dict)
        title = d.pop("title")

        description = d.pop("description")

        links = []
        _links = d.pop("links")
        for links_item_data in _links:
            links_item = OGCLink.from_dict(links_item_data)

            links.append(links_item)

        landing_page = cls(
            title=title,
            description=description,
            links=links,
        )

        landing_page.additional_properties = d
        return landing_page

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
