from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.bar_chart_widget import BarChartWidget
    from ..models.indicator_widget import IndicatorWidget


T = TypeVar("T", bound="DashboardConfig")


@_attrs_define
class DashboardConfig:
    """
    Attributes:
        version (int):
        widgets (list[BarChartWidget | IndicatorWidget]): The widgets on layers this response shows, in panel order.
    """

    version: int
    widgets: list[BarChartWidget | IndicatorWidget]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.indicator_widget import IndicatorWidget

        version = self.version

        widgets = []
        for widgets_item_data in self.widgets:
            widgets_item: dict[str, Any]
            if isinstance(widgets_item_data, IndicatorWidget):
                widgets_item = widgets_item_data.to_dict()
            else:
                widgets_item = widgets_item_data.to_dict()

            widgets.append(widgets_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "version": version,
                "widgets": widgets,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.bar_chart_widget import BarChartWidget
        from ..models.indicator_widget import IndicatorWidget

        d = dict(src_dict)
        version = d.pop("version")

        widgets = []
        _widgets = d.pop("widgets")
        for widgets_item_data in _widgets:

            def _parse_widgets_item(data: object) -> BarChartWidget | IndicatorWidget:
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    widgets_item_type_0 = IndicatorWidget.from_dict(data)

                    return widgets_item_type_0
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                if not isinstance(data, dict):
                    raise TypeError()
                widgets_item_type_1 = BarChartWidget.from_dict(data)

                return widgets_item_type_1

            widgets_item = _parse_widgets_item(widgets_item_data)

            widgets.append(widgets_item)

        dashboard_config = cls(
            version=version,
            widgets=widgets,
        )

        dashboard_config.additional_properties = d
        return dashboard_config

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
