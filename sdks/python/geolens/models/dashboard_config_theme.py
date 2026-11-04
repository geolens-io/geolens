from typing import Literal, cast

DashboardConfigTheme = Literal["dark", "follow", "light"]

DASHBOARD_CONFIG_THEME_VALUES: set[DashboardConfigTheme] = {
    "dark",
    "follow",
    "light",
}


def check_dashboard_config_theme(value: str) -> DashboardConfigTheme:
    if value in DASHBOARD_CONFIG_THEME_VALUES:
        return cast(DashboardConfigTheme, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {DASHBOARD_CONFIG_THEME_VALUES!r}"
    )
