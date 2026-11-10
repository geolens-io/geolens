from typing import Literal, cast

DashboardConfigPanel = Literal["bottom", "right"]

DASHBOARD_CONFIG_PANEL_VALUES: set[DashboardConfigPanel] = {
    "bottom",
    "right",
}


def check_dashboard_config_panel(value: str) -> DashboardConfigPanel:
    if value in DASHBOARD_CONFIG_PANEL_VALUES:
        return cast(DashboardConfigPanel, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {DASHBOARD_CONFIG_PANEL_VALUES!r}"
    )
