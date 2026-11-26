from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


T = TypeVar("T", bound="ManifestWideningKeptDetail")


@_attrs_define
class ManifestWideningKeptDetail:
    """
    Attributes:
        visibility (str): The wider level the entry asked for.
    """

    visibility: str

    def to_dict(self) -> dict[str, Any]:
        visibility = self.visibility

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "visibility": visibility,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        visibility = d.pop("visibility")

        manifest_widening_kept_detail = cls(
            visibility=visibility,
        )

        return manifest_widening_kept_detail
