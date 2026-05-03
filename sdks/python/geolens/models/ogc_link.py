from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="OGCLink")


@_attrs_define
class OGCLink:
    """
    Attributes:
        href (str): Target URL of the link.
        rel (str): Link relation type per RFC 8288 (e.g. 'self', 'next', 'prev', 'data', 'collection').
        type_ (str): Media type of the linked resource (e.g. 'application/json', 'application/geo+json').
        title (None | str | Unset): Optional human-readable label for the link.
    """

    href: str
    rel: str
    type_: str
    title: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        href = self.href

        rel = self.rel

        type_ = self.type_

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "href": href,
                "rel": rel,
                "type": type_,
            }
        )
        if title is not UNSET:
            field_dict["title"] = title

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        href = d.pop("href")

        rel = d.pop("rel")

        type_ = d.pop("type")

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        ogc_link = cls(
            href=href,
            rel=rel,
            type_=type_,
            title=title,
        )

        ogc_link.additional_properties = d
        return ogc_link

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
