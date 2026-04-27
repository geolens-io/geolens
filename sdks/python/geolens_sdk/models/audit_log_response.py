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
    from ..models.audit_log_response_details_type_0 import AuditLogResponseDetailsType0


T = TypeVar("T", bound="AuditLogResponse")


@_attrs_define
class AuditLogResponse:
    """
    Attributes:
        action (str):
        created_at (datetime.datetime):
        details (AuditLogResponseDetailsType0 | None):
        id (UUID):
        ip_address (None | str):
        resource_id (None | UUID):
        resource_type (str):
        user_id (UUID):
        username (None | str | Unset):
    """

    action: str
    created_at: datetime.datetime
    details: AuditLogResponseDetailsType0 | None
    id: UUID
    ip_address: None | str
    resource_id: None | UUID
    resource_type: str
    user_id: UUID
    username: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.audit_log_response_details_type_0 import (
            AuditLogResponseDetailsType0,
        )

        action = self.action

        created_at = self.created_at.isoformat()

        details: dict[str, Any] | None
        if isinstance(self.details, AuditLogResponseDetailsType0):
            details = self.details.to_dict()
        else:
            details = self.details

        id = str(self.id)

        ip_address: None | str
        ip_address = self.ip_address

        resource_id: None | str
        if isinstance(self.resource_id, UUID):
            resource_id = str(self.resource_id)
        else:
            resource_id = self.resource_id

        resource_type = self.resource_type

        user_id = str(self.user_id)

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
                "id": id,
                "ip_address": ip_address,
                "resource_id": resource_id,
                "resource_type": resource_type,
                "user_id": user_id,
            }
        )
        if username is not UNSET:
            field_dict["username"] = username

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.audit_log_response_details_type_0 import (
            AuditLogResponseDetailsType0,
        )

        d = dict(src_dict)
        action = d.pop("action")

        created_at = isoparse(d.pop("created_at"))

        def _parse_details(data: object) -> AuditLogResponseDetailsType0 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                details_type_0 = AuditLogResponseDetailsType0.from_dict(data)

                return details_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AuditLogResponseDetailsType0 | None, data)

        details = _parse_details(d.pop("details"))

        id = UUID(d.pop("id"))

        def _parse_ip_address(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        ip_address = _parse_ip_address(d.pop("ip_address"))

        def _parse_resource_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                resource_id_type_0 = UUID(data)

                return resource_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        resource_id = _parse_resource_id(d.pop("resource_id"))

        resource_type = d.pop("resource_type")

        user_id = UUID(d.pop("user_id"))

        def _parse_username(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        username = _parse_username(d.pop("username", UNSET))

        audit_log_response = cls(
            action=action,
            created_at=created_at,
            details=details,
            id=id,
            ip_address=ip_address,
            resource_id=resource_id,
            resource_type=resource_type,
            user_id=user_id,
            username=username,
        )

        audit_log_response.additional_properties = d
        return audit_log_response

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
