from typing import Literal, cast

StorySettingsLayout = Literal["floating", "side"]

STORY_SETTINGS_LAYOUT_VALUES: set[StorySettingsLayout] = {
    "floating",
    "side",
}


def check_story_settings_layout(value: str) -> StorySettingsLayout:
    if value in STORY_SETTINGS_LAYOUT_VALUES:
        return cast(StorySettingsLayout, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {STORY_SETTINGS_LAYOUT_VALUES!r}"
    )
