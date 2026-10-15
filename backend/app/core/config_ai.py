"""Claude and OpenAI-compatible settings read from the environment.

Env-only like the API keys, so no admin-editable value can send a credential to
another host.
"""

from typing import Literal

from pydantic import BaseModel, SecretStr, field_validator

ClaudePlatform = Literal["anthropic", "foundry", "bedrock", "vertex"]

DEFAULT_LLM_MODEL = "claude-sonnet-5-5"


class ClaudeSettings(BaseModel):
    anthropic_api_key: SecretStr | None = None
    # Unset means DEFAULT_LLM_MODEL, which Bedrock and Vertex don't serve.
    llm_model: str | None = None
    # Unset keeps claude-haiku on Anthropic's API and reuses llm_model on the
    # cloud platforms, whose model IDs differ.
    llm_model_light: str | None = None
    anthropic_platform: ClaudePlatform = "anthropic"
    anthropic_base_url: str | None = None
    anthropic_foundry_api_key: SecretStr | None = None
    anthropic_foundry_resource: str | None = None
    # Not the AWS_* names: GDAL reads those for S3 storage, and the SDK treats
    # the blank AWS_BEARER_TOKEN_BEDROCK Compose passes as a key.
    anthropic_bedrock_api_key: SecretStr | None = None
    anthropic_bedrock_aws_region: str | None = None
    anthropic_bedrock_aws_access_key_id: str | None = None
    anthropic_bedrock_aws_secret_access_key: SecretStr | None = None
    cloud_ml_region: str | None = None
    anthropic_vertex_project_id: str | None = None

    # Compose passes an unset variable as "", which means not set.
    @field_validator(
        "anthropic_api_key",
        "llm_model",
        "llm_model_light",
        "anthropic_base_url",
        "anthropic_foundry_api_key",
        "anthropic_foundry_resource",
        "anthropic_bedrock_api_key",
        "anthropic_bedrock_aws_region",
        "anthropic_bedrock_aws_access_key_id",
        "anthropic_bedrock_aws_secret_access_key",
        "cloud_ml_region",
        "anthropic_vertex_project_id",
        mode="before",
    )
    @classmethod
    def blank_claude_setting_to_none(cls, v: str | None) -> str | None:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


OpenAIAPIStyle = Literal["chat_completions", "responses"]


class OpenAISettings(BaseModel):
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o"
    # Light model for SQL generation / metadata. Unset reuses openai_model, since
    # on Azure OpenAI and gateways a hardcoded default 404s unless it names a
    # real deployment.
    openai_model_light: str | None = None
    openai_base_url: str | None = None
    openai_reasoning_effort: str | None = None
    # Chat Completions is what other OpenAI-compatible servers speak; some
    # OpenAI models call tools only through the Responses API.
    openai_api_style: OpenAIAPIStyle = "chat_completions"

    @field_validator(
        "openai_api_key",
        "openai_model_light",
        "openai_base_url",
        "openai_reasoning_effort",
        mode="before",
    )
    @classmethod
    def blank_openai_setting_to_none(cls, v: str | None) -> str | None:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("openai_api_style", mode="before")
    @classmethod
    def blank_api_style_to_default(cls, v: object) -> object:
        if isinstance(v, str) and v.strip() == "":
            return "chat_completions"
        return v
