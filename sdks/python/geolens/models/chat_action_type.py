from typing import Literal, cast

ChatActionType = Literal[
    "add_layer",
    "remove_layer",
    "set_data_driven_style",
    "set_filter",
    "set_label",
    "set_opacity",
    "set_style",
    "show_query_result",
    "toggle_visibility",
]

CHAT_ACTION_TYPE_VALUES: set[ChatActionType] = {
    "add_layer",
    "remove_layer",
    "set_data_driven_style",
    "set_filter",
    "set_label",
    "set_opacity",
    "set_style",
    "show_query_result",
    "toggle_visibility",
}


def check_chat_action_type(value: str) -> ChatActionType:
    if value in CHAT_ACTION_TYPE_VALUES:
        return cast(ChatActionType, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {CHAT_ACTION_TYPE_VALUES!r}"
    )
