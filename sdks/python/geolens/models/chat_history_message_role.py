from typing import Literal, cast

ChatHistoryMessageRole = Literal["assistant", "user"]

CHAT_HISTORY_MESSAGE_ROLE_VALUES: set[ChatHistoryMessageRole] = {
    "assistant",
    "user",
}


def check_chat_history_message_role(value: str) -> ChatHistoryMessageRole:
    if value in CHAT_HISTORY_MESSAGE_ROLE_VALUES:
        return cast(ChatHistoryMessageRole, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {CHAT_HISTORY_MESSAGE_ROLE_VALUES!r}"
    )
