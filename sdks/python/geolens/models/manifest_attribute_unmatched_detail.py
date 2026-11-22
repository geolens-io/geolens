from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


from typing import cast


T = TypeVar("T", bound="ManifestAttributeUnmatchedDetail")


@_attrs_define
class ManifestAttributeUnmatchedDetail:
    """
    Attributes:
        source_names (list[str]):
    """

    source_names: list[str]

    def to_dict(self) -> dict[str, Any]:
        source_names = self.source_names

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "source_names": source_names,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        source_names = cast(list[str], d.pop("source_names"))

        manifest_attribute_unmatched_detail = cls(
            source_names=source_names,
        )

        return manifest_attribute_unmatched_detail
