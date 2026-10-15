from typing import Literal, cast

ApiKeyStatusResponseAnthropicPlatform = Literal[
    "anthropic", "bedrock", "foundry", "vertex"
]

API_KEY_STATUS_RESPONSE_ANTHROPIC_PLATFORM_VALUES: set[
    ApiKeyStatusResponseAnthropicPlatform
] = {
    "anthropic",
    "bedrock",
    "foundry",
    "vertex",
}


def check_api_key_status_response_anthropic_platform(
    value: str,
) -> ApiKeyStatusResponseAnthropicPlatform:
    if value in API_KEY_STATUS_RESPONSE_ANTHROPIC_PLATFORM_VALUES:
        return cast(ApiKeyStatusResponseAnthropicPlatform, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {API_KEY_STATUS_RESPONSE_ANTHROPIC_PLATFORM_VALUES!r}"
    )
