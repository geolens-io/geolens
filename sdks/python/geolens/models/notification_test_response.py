from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.notification_test_channel_result import NotificationTestChannelResult


T = TypeVar("T", bound="NotificationTestResponse")


@_attrs_define
class NotificationTestResponse:
    """Response for POST /settings/notifications/test/ (NOTIF-06).

    Always returns HTTP 200 — a channel delivery failure is captured in the
    per-channel ``channels`` list rather than as a 5xx. Never contains secret
    values (T-1229-09 / NOTIF-05).

        Attributes:
            channels (list[NotificationTestChannelResult]): Per-channel delivery results. Empty when no channel is
                configured.
            message (str): Human-readable summary of the test result.
            sent (bool): True if at least one channel successfully delivered the test notification.
    """

    channels: list[NotificationTestChannelResult]
    message: str
    sent: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        channels = []
        for channels_item_data in self.channels:
            channels_item = channels_item_data.to_dict()
            channels.append(channels_item)

        message = self.message

        sent = self.sent

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "channels": channels,
                "message": message,
                "sent": sent,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.notification_test_channel_result import (
            NotificationTestChannelResult,
        )

        d = dict(src_dict)
        channels = []
        _channels = d.pop("channels")
        for channels_item_data in _channels:
            channels_item = NotificationTestChannelResult.from_dict(channels_item_data)

            channels.append(channels_item)

        message = d.pop("message")

        sent = d.pop("sent")

        notification_test_response = cls(
            channels=channels,
            message=message,
            sent=sent,
        )

        notification_test_response.additional_properties = d
        return notification_test_response

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
