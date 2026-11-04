from typing import Literal, cast

DashboardConfigInputThemeType0 = Literal["dark", "follow", "light"]

DASHBOARD_CONFIG_INPUT_THEME_TYPE_0_VALUES: set[DashboardConfigInputThemeType0] = {
    "dark",
    "follow",
    "light",
}


def check_dashboard_config_input_theme_type_0(
    value: str,
) -> DashboardConfigInputThemeType0:
    if value in DASHBOARD_CONFIG_INPUT_THEME_TYPE_0_VALUES:
        return cast(DashboardConfigInputThemeType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {DASHBOARD_CONFIG_INPUT_THEME_TYPE_0_VALUES!r}"
    )
