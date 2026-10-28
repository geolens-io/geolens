from typing import Literal, cast

StoryVisibility = Literal["internal", "private", "public"]

STORY_VISIBILITY_VALUES: set[StoryVisibility] = {
    "internal",
    "private",
    "public",
}


def check_story_visibility(value: str) -> StoryVisibility:
    if value in STORY_VISIBILITY_VALUES:
        return cast(StoryVisibility, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {STORY_VISIBILITY_VALUES!r}"
    )
