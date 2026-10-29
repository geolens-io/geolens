from typing import Literal, cast

DashboardConfigInputPanelType0 = Literal["bottom", "right"]

DASHBOARD_CONFIG_INPUT_PANEL_TYPE_0_VALUES: set[DashboardConfigInputPanelType0] = {
    "bottom",
    "right",
}


def check_dashboard_config_input_panel_type_0(
    value: str,
) -> DashboardConfigInputPanelType0:
    if value in DASHBOARD_CONFIG_INPUT_PANEL_TYPE_0_VALUES:
        return cast(DashboardConfigInputPanelType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {DASHBOARD_CONFIG_INPUT_PANEL_TYPE_0_VALUES!r}"
    )
