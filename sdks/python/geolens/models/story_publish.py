from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from typing import Literal


T = TypeVar("T", bound="StoryPublish")


@_attrs_define
class StoryPublish:
    """
    Attributes:
        revision (int): The draft revision this publish or discard acts on.
        confirm (Literal['share_maps'] | None | Unset): Required to go ahead when maps the story uses block some of its
            groups; without it the request answers 409 and lists them. `share_maps` first shares each map marked `can_share`
            with the groups that lack it, which makes a private one restricted. The request is still refused while any other
            map blocks it.
    """

    revision: int
    confirm: Literal["share_maps"] | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        revision = self.revision

        confirm: Literal["share_maps"] | None | Unset
        if isinstance(self.confirm, Unset):
            confirm = UNSET
        else:
            confirm = self.confirm

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "revision": revision,
            }
        )
        if confirm is not UNSET:
            field_dict["confirm"] = confirm

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        revision = d.pop("revision")

        def _parse_confirm(data: object) -> Literal["share_maps"] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            confirm_type_0 = cast(Literal["share_maps"], data)
            if confirm_type_0 != "share_maps":
                raise ValueError(
                    f"confirm_type_0 must match const 'share_maps', got '{confirm_type_0}'"
                )
            return confirm_type_0
            return cast(Literal["share_maps"] | None | Unset, data)

        confirm = _parse_confirm(d.pop("confirm", UNSET))

        story_publish = cls(
            revision=revision,
            confirm=confirm,
        )

        return story_publish
