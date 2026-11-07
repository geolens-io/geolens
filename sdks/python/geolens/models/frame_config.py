from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


T = TypeVar("T", bound="FrameConfig")


@_attrs_define
class FrameConfig:
    """
    Attributes:
        url (str): An https address on a host an admin approved for stories. Stored as given and never fetched by the
            server.
        title (str): Names the frame for screen readers.
    """

    url: str
    title: str

    def to_dict(self) -> dict[str, Any]:
        url = self.url

        title = self.title

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "url": url,
                "title": title,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        url = d.pop("url")

        title = d.pop("title")

        frame_config = cls(
            url=url,
            title=title,
        )

        return frame_config
