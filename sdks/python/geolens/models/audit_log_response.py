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
        id (UUID):
        user_id (None | UUID):
        action (str):
        resource_type (str):
        resource_id (None | UUID):
        details (AuditLogResponseDetailsType0 | None):
        ip_address (None | str):
        created_at (datetime.datetime):
        username (None | str | Unset):
        resource_name (None | str | Unset):
    """

    id: UUID
    user_id: None | UUID
    action: str
    resource_type: str
    resource_id: None | UUID
    details: AuditLogResponseDetailsType0 | None
    ip_address: None | str
    created_at: datetime.datetime
    username: None | str | Unset = UNSET
    resource_name: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.audit_log_response_details_type_0 import (
            AuditLogResponseDetailsType0,
        )

        id = str(self.id)

        user_id: None | str
        if isinstance(self.user_id, UUID):
            user_id = str(self.user_id)
        else:
            user_id = self.user_id

        action = self.action

        resource_type = self.resource_type

        resource_id: None | str
        if isinstance(self.resource_id, UUID):
            resource_id = str(self.resource_id)
        else:
            resource_id = self.resource_id

        details: dict[str, Any] | None
        if isinstance(self.details, AuditLogResponseDetailsType0):
            details = self.details.to_dict()
        else:
            details = self.details

        ip_address: None | str
        ip_address = self.ip_address

        created_at = self.created_at.isoformat()

        username: None | str | Unset
        if isinstance(self.username, Unset):
            username = UNSET
        else:
            username = self.username

        resource_name: None | str | Unset
        if isinstance(self.resource_name, Unset):
            resource_name = UNSET
        else:
            resource_name = self.resource_name

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "user_id": user_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "details": details,
                "ip_address": ip_address,
                "created_at": created_at,
            }
        )
        if username is not UNSET:
            field_dict["username"] = username
        if resource_name is not UNSET:
            field_dict["resource_name"] = resource_name

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.audit_log_response_details_type_0 import (
            AuditLogResponseDetailsType0,
        )

        d = dict(src_dict)
        id = UUID(d.pop("id"))

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

        action = d.pop("action")

        resource_type = d.pop("resource_type")

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

        def _parse_ip_address(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        ip_address = _parse_ip_address(d.pop("ip_address"))

        created_at = isoparse(d.pop("created_at"))

        def _parse_username(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        username = _parse_username(d.pop("username", UNSET))

        def _parse_resource_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        resource_name = _parse_resource_name(d.pop("resource_name", UNSET))

        audit_log_response = cls(
            id=id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            created_at=created_at,
            username=username,
            resource_name=resource_name,
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
