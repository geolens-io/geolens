from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
    from ..models.map_history_event_response_details import (
        MapHistoryEventResponseDetails,
    )


T = TypeVar("T", bound="MapHistoryEventResponse")


@_attrs_define
class MapHistoryEventResponse:
    """
    Attributes:
        action (str):
        created_at (datetime.datetime):
        id (UUID):
        map_id (UUID):
        summary (str):
        target_type (str):
        actor_id (None | Unset | UUID):
        actor_username (None | str | Unset):
        details (MapHistoryEventResponseDetails | Unset):
        target_id (None | Unset | UUID):
        target_name (None | str | Unset):
    """

    action: str
    created_at: datetime.datetime
    id: UUID
    map_id: UUID
    summary: str
    target_type: str
    actor_id: None | Unset | UUID = UNSET
    actor_username: None | str | Unset = UNSET
    details: MapHistoryEventResponseDetails | Unset = UNSET
    target_id: None | Unset | UUID = UNSET
    target_name: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        action = self.action

        created_at = self.created_at.isoformat()

        id = str(self.id)

        map_id = str(self.map_id)

        summary = self.summary

        target_type = self.target_type

        actor_id: None | str | Unset
        if isinstance(self.actor_id, Unset):
            actor_id = UNSET
        elif isinstance(self.actor_id, UUID):
            actor_id = str(self.actor_id)
        else:
            actor_id = self.actor_id

        actor_username: None | str | Unset
        if isinstance(self.actor_username, Unset):
            actor_username = UNSET
        else:
            actor_username = self.actor_username

        details: dict[str, Any] | Unset = UNSET
        if not isinstance(self.details, Unset):
            details = self.details.to_dict()

        target_id: None | str | Unset
        if isinstance(self.target_id, Unset):
            target_id = UNSET
        elif isinstance(self.target_id, UUID):
            target_id = str(self.target_id)
        else:
            target_id = self.target_id

        target_name: None | str | Unset
        if isinstance(self.target_name, Unset):
            target_name = UNSET
        else:
            target_name = self.target_name

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "action": action,
                "created_at": created_at,
                "id": id,
                "map_id": map_id,
                "summary": summary,
                "target_type": target_type,
            }
        )
        if actor_id is not UNSET:
            field_dict["actor_id"] = actor_id
        if actor_username is not UNSET:
            field_dict["actor_username"] = actor_username
        if details is not UNSET:
            field_dict["details"] = details
        if target_id is not UNSET:
            field_dict["target_id"] = target_id
        if target_name is not UNSET:
            field_dict["target_name"] = target_name

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.map_history_event_response_details import (
            MapHistoryEventResponseDetails,
        )

        d = dict(src_dict)
        action = d.pop("action")

        created_at = isoparse(d.pop("created_at"))

        id = UUID(d.pop("id"))

        map_id = UUID(d.pop("map_id"))

        summary = d.pop("summary")

        target_type = d.pop("target_type")

        def _parse_actor_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                actor_id_type_0 = UUID(data)

                return actor_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        actor_id = _parse_actor_id(d.pop("actor_id", UNSET))

        def _parse_actor_username(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        actor_username = _parse_actor_username(d.pop("actor_username", UNSET))

        _details = d.pop("details", UNSET)
        details: MapHistoryEventResponseDetails | Unset
        if isinstance(_details, Unset):
            details = UNSET
        else:
            details = MapHistoryEventResponseDetails.from_dict(_details)

        def _parse_target_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                target_id_type_0 = UUID(data)

                return target_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        target_id = _parse_target_id(d.pop("target_id", UNSET))

        def _parse_target_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        target_name = _parse_target_name(d.pop("target_name", UNSET))

        map_history_event_response = cls(
            action=action,
            created_at=created_at,
            id=id,
            map_id=map_id,
            summary=summary,
            target_type=target_type,
            actor_id=actor_id,
            actor_username=actor_username,
            details=details,
            target_id=target_id,
            target_name=target_name,
        )

        map_history_event_response.additional_properties = d
        return map_history_event_response

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
