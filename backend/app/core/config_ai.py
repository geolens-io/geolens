"""Claude settings read from the environment.

Env-only like the API keys, so no admin-editable value can send a credential to
another host.
"""

from typing import Literal

from pydantic import BaseModel, SecretStr, field_validator


class ClaudeSettings(BaseModel):
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-sonnet-5"
    # Unset keeps claude-haiku on Anthropic's API and reuses llm_model on the
    # cloud platforms, whose model IDs differ.
    llm_model_light: str | None = None
    anthropic_platform: Literal["anthropic", "foundry", "bedrock", "vertex"] = (
        "anthropic"
    )
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
