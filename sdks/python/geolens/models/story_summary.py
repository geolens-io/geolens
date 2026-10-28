from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.story_visibility import check_story_visibility
from ..models.story_visibility import StoryVisibility
from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime


T = TypeVar("T", bound="StorySummary")


@_attrs_define
class StorySummary:
    """
    Attributes:
        id (UUID):
        title (str):
        summary (None | str):
        visibility (StoryVisibility): Who may read a published story, besides its owner and admins.
        created_by (None | UUID):
        published_at (datetime.datetime | None): When the story was last published; null if never.
        created_at (datetime.datetime):
        updated_at (datetime.datetime):
        can_edit (bool):
    """

    id: UUID
    title: str
    summary: None | str
    visibility: StoryVisibility
    created_by: None | UUID
    published_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    can_edit: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        title = self.title

        summary: None | str
        summary = self.summary

        visibility: str = self.visibility

        created_by: None | str
        if isinstance(self.created_by, UUID):
            created_by = str(self.created_by)
        else:
            created_by = self.created_by

        published_at: None | str
        if isinstance(self.published_at, datetime.datetime):
            published_at = self.published_at.isoformat()
        else:
            published_at = self.published_at

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        can_edit = self.can_edit

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "title": title,
                "summary": summary,
                "visibility": visibility,
                "created_by": created_by,
                "published_at": published_at,
                "created_at": created_at,
                "updated_at": updated_at,
                "can_edit": can_edit,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        title = d.pop("title")

        def _parse_summary(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        summary = _parse_summary(d.pop("summary"))

        visibility = check_story_visibility(d.pop("visibility"))

        def _parse_created_by(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                created_by_type_0 = UUID(data)

                return created_by_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        created_by = _parse_created_by(d.pop("created_by"))

        def _parse_published_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                published_at_type_0 = isoparse(data)

                return published_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        published_at = _parse_published_at(d.pop("published_at"))

        created_at = isoparse(d.pop("created_at"))

        updated_at = isoparse(d.pop("updated_at"))

        can_edit = d.pop("can_edit")

        story_summary = cls(
            id=id,
            title=title,
            summary=summary,
            visibility=visibility,
            created_by=created_by,
            published_at=published_at,
            created_at=created_at,
            updated_at=updated_at,
            can_edit=can_edit,
        )

        story_summary.additional_properties = d
        return story_summary

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
