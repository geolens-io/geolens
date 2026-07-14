from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.sse_error_event_message_type_1 import SSEErrorEventMessageType1


T = TypeVar("T", bound="SSEErrorEvent")


@_attrs_define
class SSEErrorEvent:
    """Error payload carried inside an already-open SSE response.

    Attributes:
        message (list[Any] | SSEErrorEventMessageType1 | str):
        type_ (Literal['error']):
        status (int | None | Unset): HTTP-equivalent status for router-level failures; provider and model errors raised
            inside the stream may omit it.
    """

    message: list[Any] | SSEErrorEventMessageType1 | str
    type_: Literal["error"]
    status: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.sse_error_event_message_type_1 import SSEErrorEventMessageType1

        message: dict[str, Any] | list[Any] | str
        if isinstance(self.message, SSEErrorEventMessageType1):
            message = self.message.to_dict()
        elif isinstance(self.message, list):
            message = self.message

        else:
            message = self.message

        type_ = self.type_

        status: int | None | Unset
        if isinstance(self.status, Unset):
            status = UNSET
        else:
            status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "message": message,
                "type": type_,
            }
        )
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sse_error_event_message_type_1 import SSEErrorEventMessageType1

        d = dict(src_dict)

        def _parse_message(data: object) -> list[Any] | SSEErrorEventMessageType1 | str:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                message_type_1 = SSEErrorEventMessageType1.from_dict(data)

                return message_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, list):
                    raise TypeError()
                message_type_2 = cast(list[Any], data)

                return message_type_2
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[Any] | SSEErrorEventMessageType1 | str, data)

        message = _parse_message(d.pop("message"))

        type_ = cast(Literal["error"], d.pop("type"))
        if type_ != "error":
            raise ValueError(f"type must match const 'error', got '{type_}'")

        def _parse_status(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        status = _parse_status(d.pop("status", UNSET))

        sse_error_event = cls(
            message=message,
            type_=type_,
            status=status,
        )

        sse_error_event.additional_properties = d
        return sse_error_event

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
