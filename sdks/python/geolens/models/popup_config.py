from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="PopupConfig")


@_attrs_define
class PopupConfig:
    """Per-layer popup configuration: enable/disable + custom title template
    + ordered visible-fields allowlist. Persisted as JSONB on map_layers.

        Attributes:
            enabled (bool):
            expression (None | str | Unset): Title template with {column_name} placeholders
            visible_fields (list[str] | None | Unset): Ordered allowlist of property keys; null = all, [] = none, ordered
                list = those in order
    """

    enabled: bool
    expression: None | str | Unset = UNSET
    visible_fields: list[str] | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        enabled = self.enabled

        expression: None | str | Unset
        if isinstance(self.expression, Unset):
            expression = UNSET
        else:
            expression = self.expression

        visible_fields: list[str] | None | Unset
        if isinstance(self.visible_fields, Unset):
            visible_fields = UNSET
        elif isinstance(self.visible_fields, list):
            visible_fields = self.visible_fields

        else:
            visible_fields = self.visible_fields

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "enabled": enabled,
            }
        )
        if expression is not UNSET:
            field_dict["expression"] = expression
        if visible_fields is not UNSET:
            field_dict["visible_fields"] = visible_fields

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        enabled = d.pop("enabled")

        def _parse_expression(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        expression = _parse_expression(d.pop("expression", UNSET))

        def _parse_visible_fields(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                visible_fields_type_0 = cast(list[str], data)

                return visible_fields_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        visible_fields = _parse_visible_fields(d.pop("visible_fields", UNSET))

        popup_config = cls(
            enabled=enabled,
            expression=expression,
            visible_fields=visible_fields,
        )

        return popup_config
