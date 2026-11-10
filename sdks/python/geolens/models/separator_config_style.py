from typing import Literal, cast

SeparatorConfigStyle = Literal["gap", "line"]

SEPARATOR_CONFIG_STYLE_VALUES: set[SeparatorConfigStyle] = {
    "gap",
    "line",
}


def check_separator_config_style(value: str) -> SeparatorConfigStyle:
    if value in SEPARATOR_CONFIG_STYLE_VALUES:
        return cast(SeparatorConfigStyle, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {SEPARATOR_CONFIG_STYLE_VALUES!r}"
    )
