from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.dashboard_config_panel import check_dashboard_config_panel
from ..models.dashboard_config_panel import DashboardConfigPanel
from ..models.dashboard_config_theme import check_dashboard_config_theme
from ..models.dashboard_config_theme import DashboardConfigTheme

if TYPE_CHECKING:
    from ..models.bar_chart_widget import BarChartWidget
    from ..models.category_selector_widget import CategorySelectorWidget
    from ..models.feature_list_widget import FeatureListWidget
    from ..models.histogram_widget import HistogramWidget
    from ..models.indicator_widget import IndicatorWidget
    from ..models.markdown_widget import MarkdownWidget
    from ..models.pie_chart_widget import PieChartWidget
    from ..models.table_widget import TableWidget


T = TypeVar("T", bound="DashboardConfig")


@_attrs_define
class DashboardConfig:
    """
    Attributes:
        version (int):
        widgets (list[BarChartWidget | CategorySelectorWidget | FeatureListWidget | HistogramWidget | IndicatorWidget |
            MarkdownWidget | PieChartWidget | TableWidget]): The widgets on layers this response shows, in panel order.
        panel (DashboardConfigPanel | Unset): Where the panel sits beside the map: `right` or `bottom`. On narrow
            screens it is always below the map. Default: 'right'.
        map_hidden (bool | Unset): Show the widgets across the full page and don't mount the map. Widgets scoped to the
            map view fall back to the whole layer. Default: False.
        theme (DashboardConfigTheme | Unset): The page's colours: `light`, `dark`, or `follow` the reader's setting.
            Default: 'follow'.
    """

    version: int
    widgets: list[
        BarChartWidget
        | CategorySelectorWidget
        | FeatureListWidget
        | HistogramWidget
        | IndicatorWidget
        | MarkdownWidget
        | PieChartWidget
        | TableWidget
    ]
    panel: DashboardConfigPanel | Unset = "right"
    map_hidden: bool | Unset = False
    theme: DashboardConfigTheme | Unset = "follow"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.bar_chart_widget import BarChartWidget
        from ..models.feature_list_widget import FeatureListWidget
        from ..models.histogram_widget import HistogramWidget
        from ..models.indicator_widget import IndicatorWidget
        from ..models.markdown_widget import MarkdownWidget
        from ..models.pie_chart_widget import PieChartWidget
        from ..models.table_widget import TableWidget

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
            elif isinstance(widgets_item_data, PieChartWidget):
                widgets_item = widgets_item_data.to_dict()
            elif isinstance(widgets_item_data, FeatureListWidget):
                widgets_item = widgets_item_data.to_dict()
            elif isinstance(widgets_item_data, TableWidget):
                widgets_item = widgets_item_data.to_dict()
            elif isinstance(widgets_item_data, HistogramWidget):
                widgets_item = widgets_item_data.to_dict()
            else:
                widgets_item = widgets_item_data.to_dict()

            widgets.append(widgets_item)

        panel: str | Unset = UNSET
        if not isinstance(self.panel, Unset):
            panel = self.panel

        map_hidden = self.map_hidden

        theme: str | Unset = UNSET
        if not isinstance(self.theme, Unset):
            theme = self.theme

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
        if map_hidden is not UNSET:
            field_dict["map_hidden"] = map_hidden
        if theme is not UNSET:
            field_dict["theme"] = theme

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.bar_chart_widget import BarChartWidget
        from ..models.category_selector_widget import CategorySelectorWidget
        from ..models.feature_list_widget import FeatureListWidget
        from ..models.histogram_widget import HistogramWidget
        from ..models.indicator_widget import IndicatorWidget
        from ..models.markdown_widget import MarkdownWidget
        from ..models.pie_chart_widget import PieChartWidget
        from ..models.table_widget import TableWidget

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
                | FeatureListWidget
                | HistogramWidget
                | IndicatorWidget
                | MarkdownWidget
                | PieChartWidget
                | TableWidget
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
                    widgets_item_type_3 = PieChartWidget.from_dict(data)

                    return widgets_item_type_3
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    widgets_item_type_4 = FeatureListWidget.from_dict(data)

                    return widgets_item_type_4
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    widgets_item_type_5 = TableWidget.from_dict(data)

                    return widgets_item_type_5
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    widgets_item_type_6 = HistogramWidget.from_dict(data)

                    return widgets_item_type_6
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                if not isinstance(data, dict):
                    raise TypeError()
                widgets_item_type_7 = CategorySelectorWidget.from_dict(data)

                return widgets_item_type_7

            widgets_item = _parse_widgets_item(widgets_item_data)

            widgets.append(widgets_item)

        _panel = d.pop("panel", UNSET)
        panel: DashboardConfigPanel | Unset
        if isinstance(_panel, Unset):
            panel = UNSET
        else:
            panel = check_dashboard_config_panel(_panel)

        map_hidden = d.pop("map_hidden", UNSET)

        _theme = d.pop("theme", UNSET)
        theme: DashboardConfigTheme | Unset
        if isinstance(_theme, Unset):
            theme = UNSET
        else:
            theme = check_dashboard_config_theme(_theme)

        dashboard_config = cls(
            version=version,
            widgets=widgets,
            panel=panel,
            map_hidden=map_hidden,
            theme=theme,
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
