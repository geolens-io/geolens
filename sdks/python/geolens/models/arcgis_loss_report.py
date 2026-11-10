from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.arcgis_loss_item import ArcgisLossItem
    from ..models.arcgis_loss_report_summary import ArcgisLossReportSummary


T = TypeVar("T", bound="ArcgisLossReport")


@_attrs_define
class ArcgisLossReport:
    """
    Attributes:
        items (list[ArcgisLossItem]):
        summary (ArcgisLossReportSummary): Item count per `kind`.
    """

    items: list[ArcgisLossItem]
    summary: ArcgisLossReportSummary
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        items = []
        for items_item_data in self.items:
            items_item = items_item_data.to_dict()
            items.append(items_item)

        summary = self.summary.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "items": items,
                "summary": summary,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.arcgis_loss_item import ArcgisLossItem
        from ..models.arcgis_loss_report_summary import ArcgisLossReportSummary

        d = dict(src_dict)
        items = []
        _items = d.pop("items")
        for items_item_data in _items:
            items_item = ArcgisLossItem.from_dict(items_item_data)

            items.append(items_item)

        summary = ArcgisLossReportSummary.from_dict(d.pop("summary"))

        arcgis_loss_report = cls(
            items=items,
            summary=summary,
        )

        arcgis_loss_report.additional_properties = d
        return arcgis_loss_report

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
