from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="AIProbeCheck")


@_attrs_define
class AIProbeCheck:
    """Result of one live provider check (chat or embeddings).

    Attributes:
        configured (bool): Whether this purpose has a provider key configured. False means no probe call was made.
        error (None | str | Unset): Short sanitized failure reason. Never contains the key or raw provider error bodies.
        ok (bool | None | Unset): Whether the live provider call succeeded. None when not configured (no call was made).
        status (int | None | Unset): HTTP status returned by the provider on failure, when available.
    """

    configured: bool
    error: None | str | Unset = UNSET
    ok: bool | None | Unset = UNSET
    status: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        configured = self.configured

        error: None | str | Unset
        if isinstance(self.error, Unset):
            error = UNSET
        else:
            error = self.error

        ok: bool | None | Unset
        if isinstance(self.ok, Unset):
            ok = UNSET
        else:
            ok = self.ok

        status: int | None | Unset
        if isinstance(self.status, Unset):
            status = UNSET
        else:
            status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "configured": configured,
            }
        )
        if error is not UNSET:
            field_dict["error"] = error
        if ok is not UNSET:
            field_dict["ok"] = ok
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        configured = d.pop("configured")

        def _parse_error(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        error = _parse_error(d.pop("error", UNSET))

        def _parse_ok(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        ok = _parse_ok(d.pop("ok", UNSET))

        def _parse_status(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        status = _parse_status(d.pop("status", UNSET))

        ai_probe_check = cls(
            configured=configured,
            error=error,
            ok=ok,
            status=status,
        )

        ai_probe_check.additional_properties = d
        return ai_probe_check

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
