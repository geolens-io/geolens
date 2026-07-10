"""Bind environment-provided AI credentials to operator-approved endpoints.

The OpenAI-compatible API key is intentionally environment-only.  A base URL
loaded from ``app_settings`` therefore must not be allowed to redirect that
credential: only the operator-controlled environment may choose its network
destination.  This module keeps the invariant in the lowest shared layer so
both settings validation and every SDK client boundary can enforce it.
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
        # Destination binding protects the environment credential.  Retain the
        # existing ability to stage an endpoint before an operator supplies a
        # key; once a key appears, this same persisted row is checked below.
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
    # Always hand the SDK the operator-owned value, not a merely equivalent DB
    # representation.  This keeps the credential/destination tuple atomic.
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

    # Blank remains the historical "use fallback" representation.  Validate
    # the effective operator fallback when a credential is present, but keep
    # the blank value so persistent configuration continues to inherit it.
    if settings.openai_api_key:
        if not stripped:
            operator_openai_base_url(purpose=purpose)
            return ""
        return bind_openai_credential_base_url(stripped, purpose=purpose)
    if not stripped:
        return ""
    return canonicalize_openai_base_url(stripped)
