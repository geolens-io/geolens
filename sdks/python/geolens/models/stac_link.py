from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="StacLink")


@_attrs_define
class StacLink:
    """A single STAC link object.

    Attributes:
        href (str): Target URL of the link.
        rel (str): Link relation type (e.g. 'self', 'root', 'parent', 'item', 'data').
        type_ (None | str | Unset): Media type of the linked resource (e.g. 'application/json').
        method (None | str | Unset): HTTP method to use (defaults to GET).
    """

    href: str
    rel: str
    type_: None | str | Unset = UNSET
    method: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        href = self.href

        rel = self.rel

        type_: None | str | Unset
        if isinstance(self.type_, Unset):
            type_ = UNSET
        else:
            type_ = self.type_

        method: None | str | Unset
        if isinstance(self.method, Unset):
            method = UNSET
        else:
            method = self.method

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "href": href,
                "rel": rel,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_
        if method is not UNSET:
            field_dict["method"] = method

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        href = d.pop("href")

        rel = d.pop("rel")

        def _parse_type_(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        type_ = _parse_type_(d.pop("type", UNSET))

        def _parse_method(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        method = _parse_method(d.pop("method", UNSET))

        stac_link = cls(
            href=href,
            rel=rel,
            type_=type_,
            method=method,
        )

        stac_link.additional_properties = d
        return stac_link

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
