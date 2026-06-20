from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="NotificationTestChannelResult")


@_attrs_define
class NotificationTestChannelResult:
    """Per-channel result from POST /settings/notifications/test/.

    The ``error`` field contains only the exception type name and a short
    safe message — never the SMTP password, webhook URL, or webhook secret
    (T-1229-09 / NOTIF-05).

        Attributes:
            channel (str): Channel name, e.g. 'smtp' or 'webhook'.
            ok (bool): True if the channel delivered the test notification without error.
            error (None | str | Unset): Safe error string (exception type name + short message) if ok=False, else null.
                Never contains secrets.
    """

    channel: str
    ok: bool
    error: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        channel = self.channel

        ok = self.ok

        error: None | str | Unset
        if isinstance(self.error, Unset):
            error = UNSET
        else:
            error = self.error

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "channel": channel,
                "ok": ok,
            }
        )
        if error is not UNSET:
            field_dict["error"] = error

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        channel = d.pop("channel")

        ok = d.pop("ok")

        def _parse_error(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        error = _parse_error(d.pop("error", UNSET))

        notification_test_channel_result = cls(
            channel=channel,
            ok=ok,
            error=error,
        )

        notification_test_channel_result.additional_properties = d
        return notification_test_channel_result

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
