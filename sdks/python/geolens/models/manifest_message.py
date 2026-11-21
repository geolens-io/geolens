from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.manifest_message_severity import check_manifest_message_severity
from ..models.manifest_message_severity import ManifestMessageSeverity
from typing import cast


T = TypeVar("T", bound="ManifestMessage")


@_attrs_define
class ManifestMessage:
    """
    Attributes:
        code (str): Stable code, for example `A020`.
        severity (ManifestMessageSeverity):
        message (str):
        fix (None | str | Unset):
        layer (None | str | Unset): The map layer key the message is about. Left out otherwise.
    """

    code: str
    severity: ManifestMessageSeverity
    message: str
    fix: None | str | Unset = UNSET
    layer: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        code = self.code

        severity: str = self.severity

        message = self.message

        fix: None | str | Unset
        if isinstance(self.fix, Unset):
            fix = UNSET
        else:
            fix = self.fix

        layer: None | str | Unset
        if isinstance(self.layer, Unset):
            layer = UNSET
        else:
            layer = self.layer

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "code": code,
                "severity": severity,
                "message": message,
            }
        )
        if fix is not UNSET:
            field_dict["fix"] = fix
        if layer is not UNSET:
            field_dict["layer"] = layer

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        code = d.pop("code")

        severity = check_manifest_message_severity(d.pop("severity"))

        message = d.pop("message")

        def _parse_fix(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        fix = _parse_fix(d.pop("fix", UNSET))

        def _parse_layer(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        layer = _parse_layer(d.pop("layer", UNSET))

        manifest_message = cls(
            code=code,
            severity=severity,
            message=message,
            fix=fix,
            layer=layer,
        )

        manifest_message.additional_properties = d
        return manifest_message

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
