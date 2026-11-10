from typing import Literal, cast

StorySceneTransitionType0 = Literal["cut", "fly", "glide"]

STORY_SCENE_TRANSITION_TYPE_0_VALUES: set[StorySceneTransitionType0] = {
    "cut",
    "fly",
    "glide",
}


def check_story_scene_transition_type_0(value: str) -> StorySceneTransitionType0:
    if value in STORY_SCENE_TRANSITION_TYPE_0_VALUES:
        return cast(StorySceneTransitionType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {STORY_SCENE_TRANSITION_TYPE_0_VALUES!r}"
    )
