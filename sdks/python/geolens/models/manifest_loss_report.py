from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset


if TYPE_CHECKING:
    from ..models.manifest_loss_item import ManifestLossItem
    from ..models.manifest_loss_report_summary import ManifestLossReportSummary


T = TypeVar("T", bound="ManifestLossReport")


@_attrs_define
class ManifestLossReport:
    """
    Attributes:
        items (list[ManifestLossItem] | Unset):
        summary (ManifestLossReportSummary | Unset):
    """

    items: list[ManifestLossItem] | Unset = UNSET
    summary: ManifestLossReportSummary | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        items: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.items, Unset):
            items = []
            for items_item_data in self.items:
                items_item = items_item_data.to_dict()
                items.append(items_item)

        summary: dict[str, Any] | Unset = UNSET
        if not isinstance(self.summary, Unset):
            summary = self.summary.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if items is not UNSET:
            field_dict["items"] = items
        if summary is not UNSET:
            field_dict["summary"] = summary

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manifest_loss_item import ManifestLossItem
        from ..models.manifest_loss_report_summary import ManifestLossReportSummary

        d = dict(src_dict)
        _items = d.pop("items", UNSET)
        items: list[ManifestLossItem] | Unset = UNSET
        if _items is not UNSET:
            items = []
            for items_item_data in _items:
                items_item = ManifestLossItem.from_dict(items_item_data)

                items.append(items_item)

        _summary = d.pop("summary", UNSET)
        summary: ManifestLossReportSummary | Unset
        if isinstance(_summary, Unset):
            summary = UNSET
        else:
            summary = ManifestLossReportSummary.from_dict(_summary)

        manifest_loss_report = cls(
            items=items,
            summary=summary,
        )

        return manifest_loss_report
