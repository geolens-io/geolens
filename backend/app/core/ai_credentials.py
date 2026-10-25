"""Bind environment-provided AI credentials to operator-approved endpoints.

The OpenAI-compatible API key is intentionally environment-only.  A base URL
loaded from ``app_settings`` therefore must not be allowed to redirect that
credential: only the operator-controlled environment may choose its network
destination.  This module keeps the invariant in the lowest shared layer so
both settings validation and every SDK client boundary can enforce it.

Claude's platform settings are environment-only for the same reason.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from app.core.config import settings

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

OpenAIPurpose = Literal["chat", "embedding"]


class OpenAICredentialDestinationError(ValueError):
    """Raised when a DB/runtime URL would redirect the environment API key."""


def canonicalize_openai_base_url(value: str) -> str:
    """Validate and canonicalize an OpenAI-compatible HTTP(S) base URL.

    Explicit operator-configured HTTP endpoints remain supported for local and
    private OpenAI-compatible services.  Userinfo, query strings, and fragments
    are excluded because they are not part of a stable credential destination
    and may themselves contain secrets.
    """
    if not isinstance(value, str):
        raise OpenAICredentialDestinationError(
            "OpenAI-compatible base URL must be a string"
        )

    stripped = value.strip()
    parsed = urlsplit(stripped)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise OpenAICredentialDestinationError(
            "OpenAI-compatible base URL must be an absolute HTTP(S) URL"
        )
    if parsed.username is not None or parsed.password is not None:
        raise OpenAICredentialDestinationError(
            "OpenAI-compatible base URL must not contain userinfo"
        )
    if parsed.query or parsed.fragment:
        raise OpenAICredentialDestinationError(
            "OpenAI-compatible base URL must not contain a query string or fragment"
        )

    try:
        port = parsed.port
    except ValueError as exc:
        raise OpenAICredentialDestinationError(
            "OpenAI-compatible base URL contains an invalid port"
        ) from exc

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and not (
        (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    ):
        host = f"{host}:{port}"

    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, host, path, "", ""))


def operator_openai_base_url(*, purpose: OpenAIPurpose) -> str:
    """Return the canonical endpoint approved alongside ``OPENAI_API_KEY``."""
    if purpose == "embedding" and settings.embedding_base_url:
        configured = settings.embedding_base_url
    else:
        configured = settings.openai_base_url or DEFAULT_OPENAI_BASE_URL
    return canonicalize_openai_base_url(configured)


def bind_openai_credential_base_url(
    candidate: str | None,
    *,
    purpose: OpenAIPurpose,
) -> str:
    """Return an operator-approved URL or fail before the API key is exposed.

    ``candidate`` can come from persistent configuration, an imported stale
    row, or a provider call argument. Empty values resolve through the
    operator-owned environment fallback for the requested purpose.
    """
    effective = candidate
    if not effective:
        effective = (
            operator_openai_base_url(purpose=purpose)
            if settings.openai_api_key
            else DEFAULT_OPENAI_BASE_URL
        )
    canonical_candidate = canonicalize_openai_base_url(effective)
    if not settings.openai_api_key:
        # No key yet, so nothing to protect; keeps the ability to stage an
        # endpoint before a key exists (checked once one appears).
        return canonical_candidate
    approved = operator_openai_base_url(purpose=purpose)
    if canonical_candidate != approved:
        env_name = (
            "EMBEDDING_BASE_URL (or OPENAI_BASE_URL when unset)"
            if purpose == "embedding"
            else "OPENAI_BASE_URL"
        )
        raise OpenAICredentialDestinationError(
            "The environment-provided OpenAI-compatible credential is bound to "
            f"the operator-approved {env_name}; change the endpoint in deployment "
            "configuration and reset any database override"
        )
    # Hand the SDK the operator-owned value, not a merely equivalent DB
    # representation, to keep the credential/destination tuple atomic.
    return approved


def validate_persistent_openai_base_url(
    value: object,
    *,
    purpose: OpenAIPurpose,
) -> str:
    """Validate an admin/import value and enforce binding when a key exists."""
    if not isinstance(value, str):
        raise OpenAICredentialDestinationError(
            "OpenAI-compatible base URL must be a string"
        )
    stripped = value.strip()

    # Blank is the historical "use fallback" value. Validate the effective
    # fallback when a credential is present, but keep the blank so persistent
    # configuration keeps inheriting it.
    if settings.openai_api_key:
        if not stripped:
            operator_openai_base_url(purpose=purpose)
            return ""
        return bind_openai_credential_base_url(stripped, purpose=purpose)
    if not stripped:
        return ""
    return canonicalize_openai_base_url(stripped)


def bedrock_credentials() -> dict[str, str]:
    """Bedrock client credentials as SDK arguments, never the S3 storage keys.

    API and worker startup export the S3 storage key pair as AWS_ACCESS_KEY_ID
    for GDAL, and the AWS default chain reads that variable before any role,
    so the chain is refused while storage holds a static key. Raises
    ValueError naming what to set.
    """
    if settings.anthropic_bedrock_api_key:
        return {"api_key": settings.anthropic_bedrock_api_key.get_secret_value()}
    key_id = settings.anthropic_bedrock_aws_access_key_id
    secret = settings.anthropic_bedrock_aws_secret_access_key
    if key_id and secret:
        return {"aws_access_key": key_id, "aws_secret_key": secret.get_secret_value()}
    if key_id or secret:
        raise ValueError(
            "Claude on Bedrock needs both ANTHROPIC_BEDROCK_AWS_ACCESS_KEY_ID and "
            "ANTHROPIC_BEDROCK_AWS_SECRET_ACCESS_KEY"
        )
    if settings.storage_provider == "s3" and settings.s3_access_key_id:
        raise ValueError(
            "Claude on Bedrock would sign with the S3 storage key; set "
            "ANTHROPIC_BEDROCK_API_KEY or the ANTHROPIC_BEDROCK_AWS_* key pair"
        )
    return {}


def anthropic_unconfigured_reason() -> str | None:
    """Why the selected Claude platform can't build a client, or None if it can.

    Bedrock without a bearer token or key pair falls back to the AWS default
    credential chain, which only a network call could check, so its region
    stands in for it.
    """
    platform = settings.anthropic_platform
    if platform == "anthropic":
        return (
            None if settings.anthropic_api_key else "Anthropic API key not configured"
        )
    if platform == "bedrock" and settings.anthropic_bedrock_aws_region:
        try:
            bedrock_credentials()
        except ValueError as exc:
            return str(exc)
        ready = True
    else:
        ready = bool(
            {
                "foundry": settings.anthropic_foundry_api_key
                and settings.anthropic_foundry_resource,
                "vertex": settings.cloud_ml_region
                and settings.anthropic_vertex_project_id,
            }.get(platform)
        )
    return None if ready else f"Claude on {platform} not configured"


def anthropic_configured() -> bool:
    """Whether the selected Claude platform has the settings its client needs."""
    return anthropic_unconfigured_reason() is None


def builtin_providers_configured() -> dict[str, bool]:
    """Which built-in LLM providers have the credentials they need.

    Overlay providers are absent: the selected one counts as configured and the
    provider call surfaces any auth failure.
    """
    return {
        "anthropic": anthropic_configured(),
        "openai_compatible": bool(settings.openai_api_key),
    }
