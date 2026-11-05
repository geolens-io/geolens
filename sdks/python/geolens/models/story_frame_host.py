from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset


T = TypeVar("T", bound="StoryFrameHost")


@_attrs_define
class StoryFrameHost:
    """One approved host.

    Attributes:
        host (str): An exact host name, such as media.example.org.
        allow_same_origin (bool | Unset): Let this host's frames keep their own origin, which some video players need
            for playback. Default: False.
    """

    host: str
    allow_same_origin: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        host = self.host

        allow_same_origin = self.allow_same_origin

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "host": host,
            }
        )
        if allow_same_origin is not UNSET:
            field_dict["allow_same_origin"] = allow_same_origin

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        host = d.pop("host")

        allow_same_origin = d.pop("allow_same_origin", UNSET)

        story_frame_host = cls(
            host=host,
            allow_same_origin=allow_same_origin,
        )

        return story_frame_host
