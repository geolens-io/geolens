from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="ManifestLossItem")


@_attrs_define
class ManifestLossItem:
    """
    Attributes:
        path (str):
        kind (str):
        detail (None | str | Unset):
    """

    path: str
    kind: str
    detail: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        path = self.path

        kind = self.kind

        detail: None | str | Unset
        if isinstance(self.detail, Unset):
            detail = UNSET
        else:
            detail = self.detail

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "path": path,
                "kind": kind,
            }
        )
        if detail is not UNSET:
            field_dict["detail"] = detail

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        path = d.pop("path")

        kind = d.pop("kind")

        def _parse_detail(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        detail = _parse_detail(d.pop("detail", UNSET))

        manifest_loss_item = cls(
            path=path,
            kind=kind,
            detail=detail,
        )

        return manifest_loss_item
