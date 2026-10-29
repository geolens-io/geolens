from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.dashboard_config_input_panel_type_0 import (
    check_dashboard_config_input_panel_type_0,
)
from ..models.dashboard_config_input_panel_type_0 import DashboardConfigInputPanelType0
from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.bar_chart_widget import BarChartWidget
    from ..models.indicator_widget import IndicatorWidget


T = TypeVar("T", bound="DashboardConfigInput")


@_attrs_define
class DashboardConfigInput:
    """
    Attributes:
        version (Literal[1] | Unset):  Default: 1.
        panel (DashboardConfigInputPanelType0 | None | Unset): Where the panel sits beside the map: `right` or `bottom`.
            On narrow screens it is always below the map. Leave it out to keep the stored panel.
        widgets (list[BarChartWidget | IndicatorWidget] | Unset): Widgets in panel order. Each names a layer of this map
            that you can read. Stored widgets you can't see are kept in place.
    """

    version: Literal[1] | Unset = 1
    panel: DashboardConfigInputPanelType0 | None | Unset = UNSET
    widgets: list[BarChartWidget | IndicatorWidget] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.indicator_widget import IndicatorWidget

        version = self.version

        panel: None | str | Unset
        if isinstance(self.panel, Unset):
            panel = UNSET
        elif isinstance(self.panel, str):
            panel = self.panel
        else:
            panel = self.panel

        widgets: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.widgets, Unset):
            widgets = []
            for widgets_item_data in self.widgets:
                widgets_item: dict[str, Any]
                if isinstance(widgets_item_data, IndicatorWidget):
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
        if widgets is not UNSET:
            field_dict["widgets"] = widgets

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.bar_chart_widget import BarChartWidget
        from ..models.indicator_widget import IndicatorWidget

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

        _widgets = d.pop("widgets", UNSET)
        widgets: list[BarChartWidget | IndicatorWidget] | Unset = UNSET
        if _widgets is not UNSET:
            widgets = []
            for widgets_item_data in _widgets:

                def _parse_widgets_item(
                    data: object,
                ) -> BarChartWidget | IndicatorWidget:
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

        dashboard_config_input = cls(
            version=version,
            panel=panel,
            widgets=widgets,
        )

        return dashboard_config_input
