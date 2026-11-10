from typing import Literal, cast

StoredStoryVisibility = Literal["internal", "private", "public", "restricted"]

STORED_STORY_VISIBILITY_VALUES: set[StoredStoryVisibility] = {
    "internal",
    "private",
    "public",
    "restricted",
}


def check_stored_story_visibility(value: str) -> StoredStoryVisibility:
    if value in STORED_STORY_VISIBILITY_VALUES:
        return cast(StoredStoryVisibility, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {STORED_STORY_VISIBILITY_VALUES!r}"
    )
