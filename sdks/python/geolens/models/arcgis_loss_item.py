from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


T = TypeVar("T", bound="ArcgisLossItem")


@_attrs_define
class ArcgisLossItem:
    """
    Attributes:
        path (str): JSON path of the web map part that was not carried over.
        kind (str): Stable code for the kind of loss.
        detail (str | Unset): Free text; not localized. Default: ''.
    """

    path: str
    kind: str
    detail: str | Unset = ""
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        path = self.path

        kind = self.kind

        detail = self.detail

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
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

        detail = d.pop("detail", UNSET)

        arcgis_loss_item = cls(
            path=path,
            kind=kind,
            detail=detail,
        )

        arcgis_loss_item.additional_properties = d
        return arcgis_loss_item

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
