from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.story_visibility import check_story_visibility
from ..models.story_visibility import StoryVisibility
from typing import cast
from uuid import UUID


T = TypeVar("T", bound="StoryUpdate")


@_attrs_define
class StoryUpdate:
    """
    Attributes:
        title (None | str | Unset):
        summary (None | str | Unset):
        visibility (None | StoryVisibility | Unset): Refused with 409 when a map the published story uses is narrower
            than the new visibility.
        cover_asset_id (None | Unset | UUID): An image uploaded to this story to use as its cover, or null for none. 422
            `story_assets_not_found` for an image this story doesn't have.
    """

    title: None | str | Unset = UNSET
    summary: None | str | Unset = UNSET
    visibility: None | StoryVisibility | Unset = UNSET
    cover_asset_id: None | Unset | UUID = UNSET

    def to_dict(self) -> dict[str, Any]:
        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        summary: None | str | Unset
        if isinstance(self.summary, Unset):
            summary = UNSET
        else:
            summary = self.summary

        visibility: None | str | Unset
        if isinstance(self.visibility, Unset):
            visibility = UNSET
        elif isinstance(self.visibility, str):
            visibility = self.visibility
        else:
            visibility = self.visibility

        cover_asset_id: None | str | Unset
        if isinstance(self.cover_asset_id, Unset):
            cover_asset_id = UNSET
        elif isinstance(self.cover_asset_id, UUID):
            cover_asset_id = str(self.cover_asset_id)
        else:
            cover_asset_id = self.cover_asset_id

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if title is not UNSET:
            field_dict["title"] = title
        if summary is not UNSET:
            field_dict["summary"] = summary
        if visibility is not UNSET:
            field_dict["visibility"] = visibility
        if cover_asset_id is not UNSET:
            field_dict["cover_asset_id"] = cover_asset_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        def _parse_summary(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        summary = _parse_summary(d.pop("summary", UNSET))

        def _parse_visibility(data: object) -> None | StoryVisibility | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                visibility_type_0 = check_story_visibility(data)

                return visibility_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | StoryVisibility | Unset, data)

        visibility = _parse_visibility(d.pop("visibility", UNSET))

        def _parse_cover_asset_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                cover_asset_id_type_0 = UUID(data)

                return cover_asset_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        cover_asset_id = _parse_cover_asset_id(d.pop("cover_asset_id", UNSET))

        story_update = cls(
            title=title,
            summary=summary,
            visibility=visibility,
            cover_asset_id=cover_asset_id,
        )

        return story_update
