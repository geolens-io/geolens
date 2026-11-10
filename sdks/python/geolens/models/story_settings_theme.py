from typing import Literal, cast

StorySettingsTheme = Literal["dark", "follow", "light"]

STORY_SETTINGS_THEME_VALUES: set[StorySettingsTheme] = {
    "dark",
    "follow",
    "light",
}


def check_story_settings_theme(value: str) -> StorySettingsTheme:
    if value in STORY_SETTINGS_THEME_VALUES:
        return cast(StorySettingsTheme, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {STORY_SETTINGS_THEME_VALUES!r}"
    )
