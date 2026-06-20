from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="NotificationStatusResponse")


@_attrs_define
class NotificationStatusResponse:
    """Response for GET /settings/notifications/status/ (NOTIF-05 / NOTIF-06).

    Returns only boolean presence flags — never a secret value (SMTP password,
    webhook URL, or webhook secret).

        Attributes:
            notifications_enabled (bool): Whether the NOTIFICATIONS_ENABLED master toggle is set to true.
            smtp_configured (bool): Whether an SMTP host is configured (SMTP_HOST is set). Does not echo the host value.
            webhook_configured (bool): Whether a notification webhook URL is configured (NOTIFICATION_WEBHOOK_URL is set).
                Does not echo the URL.
    """

    notifications_enabled: bool
    smtp_configured: bool
    webhook_configured: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        notifications_enabled = self.notifications_enabled

        smtp_configured = self.smtp_configured

        webhook_configured = self.webhook_configured

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "notifications_enabled": notifications_enabled,
                "smtp_configured": smtp_configured,
                "webhook_configured": webhook_configured,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        notifications_enabled = d.pop("notifications_enabled")

        smtp_configured = d.pop("smtp_configured")

        webhook_configured = d.pop("webhook_configured")

        notification_status_response = cls(
            notifications_enabled=notifications_enabled,
            smtp_configured=smtp_configured,
            webhook_configured=webhook_configured,
        )

        notification_status_response.additional_properties = d
        return notification_status_response

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
