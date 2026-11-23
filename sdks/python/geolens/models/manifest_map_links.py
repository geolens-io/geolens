from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="ManifestMapLinks")


@_attrs_define
class ManifestMapLinks:
    """Absolute links to a map.

    Attributes:
        viewer (str): The map in the web app.
        share (None | str | Unset): The public map's share link, sent once, by the publish that created it. Share links
            are stored hashed and can't be read back, so keep it: later publishes send null, as does a publish of a map that
            isn't public, a dry run and a map in error. When no web app address is configured (PUBLIC_APP_URL, or a hosted
            tenant's own origin), no link is created, this is null, and the map answers info A074.
        embed (None | str | Unset): An iframe snippet that embeds the share link, sent with `share` and null whenever it
            is.
    """

    viewer: str
    share: None | str | Unset = UNSET
    embed: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        viewer = self.viewer

        share: None | str | Unset
        if isinstance(self.share, Unset):
            share = UNSET
        else:
            share = self.share

        embed: None | str | Unset
        if isinstance(self.embed, Unset):
            embed = UNSET
        else:
            embed = self.embed

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "viewer": viewer,
            }
        )
        if share is not UNSET:
            field_dict["share"] = share
        if embed is not UNSET:
            field_dict["embed"] = embed

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        viewer = d.pop("viewer")

        def _parse_share(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        share = _parse_share(d.pop("share", UNSET))

        def _parse_embed(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        embed = _parse_embed(d.pop("embed", UNSET))

        manifest_map_links = cls(
            viewer=viewer,
            share=share,
            embed=embed,
        )

        manifest_map_links.additional_properties = d
        return manifest_map_links

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
