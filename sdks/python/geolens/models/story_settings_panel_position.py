from typing import Literal, cast

StorySettingsPanelPosition = Literal["center", "left", "right"]

STORY_SETTINGS_PANEL_POSITION_VALUES: set[StorySettingsPanelPosition] = {
    "center",
    "left",
    "right",
}


def check_story_settings_panel_position(value: str) -> StorySettingsPanelPosition:
    if value in STORY_SETTINGS_PANEL_POSITION_VALUES:
        return cast(StorySettingsPanelPosition, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {STORY_SETTINGS_PANEL_POSITION_VALUES!r}"
    )
