from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.register_response_next_step_type_0 import (
    check_register_response_next_step_type_0,
)
from ..models.register_response_next_step_type_0 import RegisterResponseNextStepType0
from typing import cast


T = TypeVar("T", bound="RegisterResponse")


@_attrs_define
class RegisterResponse:
    """
    Attributes:
        message (str):
        next_step (None | RegisterResponseNextStepType0 | Unset): Post-registration step for the client to display:
            'verify_email' when a verification email was (or, for a swallowed collision, would have been) sent;
            'await_approval' for the admin-approval path. None on non-register responses.
    """

    message: str
    next_step: None | RegisterResponseNextStepType0 | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        message = self.message

        next_step: None | str | Unset
        if isinstance(self.next_step, Unset):
            next_step = UNSET
        elif isinstance(self.next_step, str):
            next_step = self.next_step
        else:
            next_step = self.next_step

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "message": message,
            }
        )
        if next_step is not UNSET:
            field_dict["next_step"] = next_step

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        message = d.pop("message")

        def _parse_next_step(
            data: object,
        ) -> None | RegisterResponseNextStepType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                next_step_type_0 = check_register_response_next_step_type_0(data)

                return next_step_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RegisterResponseNextStepType0 | Unset, data)

        next_step = _parse_next_step(d.pop("next_step", UNSET))

        register_response = cls(
            message=message,
            next_step=next_step,
        )

        register_response.additional_properties = d
        return register_response

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
