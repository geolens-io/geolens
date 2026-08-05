from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


T = TypeVar("T", bound="ManifestPublication")


@_attrs_define
class ManifestPublication:
    """
    Attributes:
        intent (str): Publication intent. Deliberately not pinned to an enum: the values come from the workflow
            extension's status_order(), so an overlay may define its own, and apply validates against the live extension.
            Community default order: draft, ready, internal, published.
    """

    intent: str

    def to_dict(self) -> dict[str, Any]:
        intent = self.intent

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "intent": intent,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        intent = d.pop("intent")

        manifest_publication = cls(
            intent=intent,
        )

        return manifest_publication
