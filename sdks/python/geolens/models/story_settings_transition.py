from typing import Literal, cast

StorySettingsTransition = Literal["cut", "fly", "glide"]

STORY_SETTINGS_TRANSITION_VALUES: set[StorySettingsTransition] = {
    "cut",
    "fly",
    "glide",
}


def check_story_settings_transition(value: str) -> StorySettingsTransition:
    if value in STORY_SETTINGS_TRANSITION_VALUES:
        return cast(StorySettingsTransition, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {STORY_SETTINGS_TRANSITION_VALUES!r}"
    )
