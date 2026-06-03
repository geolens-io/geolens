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
    from ..models.column_ddl_entry_details_type_0 import ColumnDdlEntryDetailsType0


T = TypeVar("T", bound="ColumnDdlEntry")


@_attrs_define
class ColumnDdlEntry:
    """A single column-DDL audit event for the owner-facing feed endpoint.

    Omits PII beyond the actor's username (no email or sensitive details).
    Mirrors AuditLogResponse shape, scoped to column-DDL events only.

        Attributes:
            action (str):
            created_at (datetime.datetime):
            details (ColumnDdlEntryDetailsType0 | None):
            user_id (None | UUID):
            username (None | str | Unset):
    """

    action: str
    created_at: datetime.datetime
    details: ColumnDdlEntryDetailsType0 | None
    user_id: None | UUID
    username: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.column_ddl_entry_details_type_0 import ColumnDdlEntryDetailsType0

        action = self.action

        created_at = self.created_at.isoformat()

        details: dict[str, Any] | None
        if isinstance(self.details, ColumnDdlEntryDetailsType0):
            details = self.details.to_dict()
        else:
            details = self.details

        user_id: None | str
        if isinstance(self.user_id, UUID):
            user_id = str(self.user_id)
        else:
            user_id = self.user_id

        username: None | str | Unset
        if isinstance(self.username, Unset):
            username = UNSET
        else:
            username = self.username

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "action": action,
                "created_at": created_at,
                "details": details,
                "user_id": user_id,
            }
        )
        if username is not UNSET:
            field_dict["username"] = username

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.column_ddl_entry_details_type_0 import ColumnDdlEntryDetailsType0

        d = dict(src_dict)
        action = d.pop("action")

        created_at = isoparse(d.pop("created_at"))

        def _parse_details(data: object) -> ColumnDdlEntryDetailsType0 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                details_type_0 = ColumnDdlEntryDetailsType0.from_dict(data)

                return details_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ColumnDdlEntryDetailsType0 | None, data)

        details = _parse_details(d.pop("details"))

        def _parse_user_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                user_id_type_0 = UUID(data)

                return user_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        user_id = _parse_user_id(d.pop("user_id"))

        def _parse_username(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        username = _parse_username(d.pop("username", UNSET))

        column_ddl_entry = cls(
            action=action,
            created_at=created_at,
            details=details,
            user_id=user_id,
            username=username,
        )

        column_ddl_entry.additional_properties = d
        return column_ddl_entry

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
