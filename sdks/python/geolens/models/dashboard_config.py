from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.dashboard_config_panel import check_dashboard_config_panel
from ..models.dashboard_config_panel import DashboardConfigPanel

if TYPE_CHECKING:
    from ..models.bar_chart_widget import BarChartWidget
    from ..models.category_selector_widget import CategorySelectorWidget
    from ..models.histogram_widget import HistogramWidget
    from ..models.indicator_widget import IndicatorWidget
    from ..models.markdown_widget import MarkdownWidget


T = TypeVar("T", bound="DashboardConfig")


@_attrs_define
class DashboardConfig:
    """
    Attributes:
        version (int):
        widgets (list[BarChartWidget | CategorySelectorWidget | HistogramWidget | IndicatorWidget | MarkdownWidget]):
            The widgets on layers this response shows, in panel order.
        panel (DashboardConfigPanel | Unset): Where the panel sits beside the map: `right` or `bottom`. On narrow
            screens it is always below the map. Default: 'right'.
    """

    version: int
    widgets: list[
        BarChartWidget
        | CategorySelectorWidget
        | HistogramWidget
        | IndicatorWidget
        | MarkdownWidget
    ]
    panel: DashboardConfigPanel | Unset = "right"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.bar_chart_widget import BarChartWidget
        from ..models.histogram_widget import HistogramWidget
        from ..models.indicator_widget import IndicatorWidget
        from ..models.markdown_widget import MarkdownWidget

        version = self.version

        widgets = []
        for widgets_item_data in self.widgets:
            widgets_item: dict[str, Any]
            if isinstance(widgets_item_data, MarkdownWidget):
                widgets_item = widgets_item_data.to_dict()
            elif isinstance(widgets_item_data, IndicatorWidget):
                widgets_item = widgets_item_data.to_dict()
            elif isinstance(widgets_item_data, BarChartWidget):
                widgets_item = widgets_item_data.to_dict()
            elif isinstance(widgets_item_data, HistogramWidget):
                widgets_item = widgets_item_data.to_dict()
            else:
                widgets_item = widgets_item_data.to_dict()

            widgets.append(widgets_item)

        panel: str | Unset = UNSET
        if not isinstance(self.panel, Unset):
            panel = self.panel

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "version": version,
                "widgets": widgets,
            }
        )
        if panel is not UNSET:
            field_dict["panel"] = panel

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.bar_chart_widget import BarChartWidget
        from ..models.category_selector_widget import CategorySelectorWidget
        from ..models.histogram_widget import HistogramWidget
        from ..models.indicator_widget import IndicatorWidget
        from ..models.markdown_widget import MarkdownWidget

        d = dict(src_dict)
        version = d.pop("version")

        widgets = []
        _widgets = d.pop("widgets")
        for widgets_item_data in _widgets:

            def _parse_widgets_item(
                data: object,
            ) -> (
                BarChartWidget
                | CategorySelectorWidget
                | HistogramWidget
                | IndicatorWidget
                | MarkdownWidget
            ):
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    widgets_item_type_0 = MarkdownWidget.from_dict(data)

                    return widgets_item_type_0
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    widgets_item_type_1 = IndicatorWidget.from_dict(data)

                    return widgets_item_type_1
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    widgets_item_type_2 = BarChartWidget.from_dict(data)

                    return widgets_item_type_2
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    widgets_item_type_3 = HistogramWidget.from_dict(data)

                    return widgets_item_type_3
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                if not isinstance(data, dict):
                    raise TypeError()
                widgets_item_type_4 = CategorySelectorWidget.from_dict(data)

                return widgets_item_type_4

            widgets_item = _parse_widgets_item(widgets_item_data)

            widgets.append(widgets_item)

        _panel = d.pop("panel", UNSET)
        panel: DashboardConfigPanel | Unset
        if isinstance(_panel, Unset):
            panel = UNSET
        else:
            panel = check_dashboard_config_panel(_panel)

        dashboard_config = cls(
            version=version,
            widgets=widgets,
            panel=panel,
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
