from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.dashboard_config_input_panel_type_0 import (
    check_dashboard_config_input_panel_type_0,
)
from ..models.dashboard_config_input_panel_type_0 import DashboardConfigInputPanelType0
from ..models.dashboard_config_input_theme_type_0 import (
    check_dashboard_config_input_theme_type_0,
)
from ..models.dashboard_config_input_theme_type_0 import DashboardConfigInputThemeType0
from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.bar_chart_widget import BarChartWidget
    from ..models.category_selector_widget import CategorySelectorWidget
    from ..models.feature_list_widget import FeatureListWidget
    from ..models.histogram_widget import HistogramWidget
    from ..models.indicator_widget import IndicatorWidget
    from ..models.markdown_widget import MarkdownWidget
    from ..models.pie_chart_widget import PieChartWidget
    from ..models.table_widget import TableWidget


T = TypeVar("T", bound="DashboardConfigInput")


@_attrs_define
class DashboardConfigInput:
    """
    Attributes:
        version (Literal[1] | Unset):  Default: 1.
        panel (DashboardConfigInputPanelType0 | None | Unset): Where the panel sits beside the map: `right` or `bottom`.
            On narrow screens it is always below the map. Leave it out to keep the stored panel.
        map_hidden (bool | None | Unset): Show the widgets across the full page and don't mount the map. Widgets scoped
            to the map view fall back to the whole layer. Leave it out to keep the stored value.
        theme (DashboardConfigInputThemeType0 | None | Unset): The page's colours: `light`, `dark`, or `follow` the
            reader's setting. Leave it out to keep the stored theme.
        readable (list[str] | None | Unset): The widget `type:v` pairs this client can parse, such as `bar_chart:1`.
            Stored widgets outside the list are kept in place. Leave it out for the widgets of earlier releases.
        widgets (list[BarChartWidget | CategorySelectorWidget | FeatureListWidget | HistogramWidget | IndicatorWidget |
            MarkdownWidget | PieChartWidget | TableWidget] | Unset): Widgets in panel order. Each, except a text widget,
            names a layer of this map that you can read. Stored widgets you can't see are kept in place.
    """

    version: Literal[1] | Unset = 1
    panel: DashboardConfigInputPanelType0 | None | Unset = UNSET
    map_hidden: bool | None | Unset = UNSET
    theme: DashboardConfigInputThemeType0 | None | Unset = UNSET
    readable: list[str] | None | Unset = UNSET
    widgets: (
        list[
            BarChartWidget
            | CategorySelectorWidget
            | FeatureListWidget
            | HistogramWidget
            | IndicatorWidget
            | MarkdownWidget
            | PieChartWidget
            | TableWidget
        ]
        | Unset
    ) = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.bar_chart_widget import BarChartWidget
        from ..models.feature_list_widget import FeatureListWidget
        from ..models.histogram_widget import HistogramWidget
        from ..models.indicator_widget import IndicatorWidget
        from ..models.markdown_widget import MarkdownWidget
        from ..models.pie_chart_widget import PieChartWidget
        from ..models.table_widget import TableWidget

        version = self.version

        panel: None | str | Unset
        if isinstance(self.panel, Unset):
            panel = UNSET
        elif isinstance(self.panel, str):
            panel = self.panel
        else:
            panel = self.panel

        map_hidden: bool | None | Unset
        if isinstance(self.map_hidden, Unset):
            map_hidden = UNSET
        else:
            map_hidden = self.map_hidden

        theme: None | str | Unset
        if isinstance(self.theme, Unset):
            theme = UNSET
        elif isinstance(self.theme, str):
            theme = self.theme
        else:
            theme = self.theme

        readable: list[str] | None | Unset
        if isinstance(self.readable, Unset):
            readable = UNSET
        elif isinstance(self.readable, list):
            readable = self.readable

        else:
            readable = self.readable

        widgets: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.widgets, Unset):
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

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if version is not UNSET:
            field_dict["version"] = version
        if panel is not UNSET:
            field_dict["panel"] = panel
        if map_hidden is not UNSET:
            field_dict["map_hidden"] = map_hidden
        if theme is not UNSET:
            field_dict["theme"] = theme
        if readable is not UNSET:
            field_dict["readable"] = readable
        if widgets is not UNSET:
            field_dict["widgets"] = widgets

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
        version = cast(Literal[1] | Unset, d.pop("version", UNSET))
        if version != 1 and not isinstance(version, Unset):
            raise ValueError(f"version must match const 1, got '{version}'")

        def _parse_panel(data: object) -> DashboardConfigInputPanelType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                panel_type_0 = check_dashboard_config_input_panel_type_0(data)

                return panel_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DashboardConfigInputPanelType0 | None | Unset, data)

        panel = _parse_panel(d.pop("panel", UNSET))

        def _parse_map_hidden(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        map_hidden = _parse_map_hidden(d.pop("map_hidden", UNSET))

        def _parse_theme(data: object) -> DashboardConfigInputThemeType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                theme_type_0 = check_dashboard_config_input_theme_type_0(data)

                return theme_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DashboardConfigInputThemeType0 | None | Unset, data)

        theme = _parse_theme(d.pop("theme", UNSET))

        def _parse_readable(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                readable_type_0 = cast(list[str], data)

                return readable_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        readable = _parse_readable(d.pop("readable", UNSET))

        _widgets = d.pop("widgets", UNSET)
        widgets: (
            list[
                BarChartWidget
                | CategorySelectorWidget
                | FeatureListWidget
                | HistogramWidget
                | IndicatorWidget
                | MarkdownWidget
                | PieChartWidget
                | TableWidget
            ]
            | Unset
        ) = UNSET
        if _widgets is not UNSET:
            widgets = []
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

        dashboard_config_input = cls(
            version=version,
            panel=panel,
            map_hidden=map_hidden,
            theme=theme,
            readable=readable,
            widgets=widgets,
        )

        return dashboard_config_input
