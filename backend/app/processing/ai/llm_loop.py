"""LLM provider runtime helpers.

The tool-calling loops live in ``DefaultAnthropicProvider.complete`` and
``DefaultOpenAICompatibleProvider.complete`` (``app.platform.extensions``).
What remains here:

  - SDK client cache helpers (``get_anthropic_client``, ``get_openai_client``).
  - ``add_tool_cache_control``, a pure Anthropic-format helper.
  - ``ToolLoopResult`` / ``ToolLoopExhaustedError`` / ``ToolExecutor`` /
    ``ActionCollector``, forward-referenced from
    ``platform/extensions/protocols.py``.
  - ``resolve_provider(db)``, which returns ``(name, model, runtime_config)``
    with ``runtime_config`` supplied by the named provider's
    ``resolve_runtime_config(db)``.
  - ``build_history_messages(history)``, a provider-agnostic role filter.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel

from app.core.config import reveal, settings
from app.core.persistent_config import LLM_MODEL, LLM_PROVIDER

if TYPE_CHECKING:
    # Annotations only: SDK packages are imported inside the factory functions,
    # not at module import time within processing/.
    from anthropic import AsyncAnthropic
    from openai import AsyncOpenAI

# Timeout for individual LLM API calls (prevents indefinite hangs). Callers
# build the SDK's own Timeout from these: the SDKs reject an httpx.Timeout.
_LLM_TIMEOUT_SECONDS = 120.0
_LLM_CONNECT_TIMEOUT_SECONDS = 10.0

logger = structlog.stdlib.get_logger(__name__)

# Cache state lives on DefaultAnthropicProvider._client and
# DefaultOpenAICompatibleProvider._clients class attributes.


def get_anthropic_client() -> AsyncAnthropic:
    """Return the cached Claude SDK client for ``ANTHROPIC_PLATFORM``.

    The one construction site for every Claude call: the tool loop, streamed
    chat and structured output. Cache lives on DefaultAnthropicProvider._client.
    Missing settings raise a clear ValueError rather than an opaque
    AuthenticationError on the first request.
    """
    from app.core.ai_credentials import anthropic_unconfigured_reason

    if reason := anthropic_unconfigured_reason():
        raise ValueError(reason)

    # Deferred import: the provider module imports _LLM_TIMEOUT_SECONDS etc.
    # from here, so a top-level import would be a cycle.
    from app.platform.extensions.defaults import DefaultAnthropicProvider

    if DefaultAnthropicProvider._client is None:
        DefaultAnthropicProvider._client = _build_anthropic_client()
    return DefaultAnthropicProvider._client


def _build_anthropic_client() -> AsyncAnthropic:
    # SDK classes are imported here so `processing/` carries no top-level
    # provider-SDK imports. The platform clients aren't all AsyncAnthropic
    # subclasses, but they serve the same messages API.
    import anthropic

    from app.core.ai_credentials import bedrock_credentials

    # No redirects: an endpoint that answers a Messages call with a 3xx could
    # otherwise carry the credential header to another origin. Operators may
    # point a gateway at a private host, so the SSRF-guarded client won't do.
    common: dict[str, Any] = {
        "timeout": anthropic.Timeout(
            _LLM_TIMEOUT_SECONDS, connect=_LLM_CONNECT_TIMEOUT_SECONDS
        ),
        "max_retries": 2,
        "http_client": anthropic.DefaultAsyncHttpxClient(follow_redirects=False),
    }
    platform = settings.anthropic_platform
    if platform == "foundry":
        return anthropic.AsyncAnthropicFoundry(
            api_key=reveal(settings.anthropic_foundry_api_key),
            resource=settings.anthropic_foundry_resource,
            **common,
        )
    if platform == "bedrock":
        return anthropic.AsyncAnthropicBedrock(
            aws_region=settings.anthropic_bedrock_aws_region,
            **bedrock_credentials(),
            **common,
        )
    if platform == "vertex":
        return anthropic.AsyncAnthropicVertex(
            region=settings.cloud_ml_region,
            project_id=settings.anthropic_vertex_project_id,
            **common,
        )
    # Explicit even when unset: Compose passes a blank ANTHROPIC_BASE_URL,
    # which the SDK would otherwise read as the URL.
    return anthropic.AsyncAnthropic(
        api_key=reveal(settings.anthropic_api_key),
        base_url=settings.anthropic_base_url or "https://api.anthropic.com",
        **common,
    )


def get_openai_client(base_url: str) -> AsyncOpenAI:
    """Return the cached OpenAI-compatible SDK client for ``base_url``.

    Cache lives on DefaultOpenAICompatibleProvider._clients. A missing key
    raises a clear ValueError rather than an opaque AuthenticationError,
    mirroring the guard in DefaultOpenAICompatibleProvider.complete().
    """
    if not settings.openai_api_key:
        raise ValueError("OpenAI-compatible API key not configured")

    # Re-check at the SDK boundary: runtime config normally validates this
    # first, but direct callers and stale imported DB rows must fail before a
    # client can attach the environment credential to an untrusted URL.
    from app.core.ai_credentials import bind_openai_credential_base_url

    base_url = bind_openai_credential_base_url(base_url, purpose="chat")

    # Deferred imports, as in get_anthropic_client().
    from openai import AsyncOpenAI, Timeout
    from app.platform.extensions.defaults import DefaultOpenAICompatibleProvider

    if base_url not in DefaultOpenAICompatibleProvider._clients:
        DefaultOpenAICompatibleProvider._clients[base_url] = AsyncOpenAI(
            api_key=reveal(settings.openai_api_key),
            base_url=base_url,
            timeout=Timeout(_LLM_TIMEOUT_SECONDS, connect=_LLM_CONNECT_TIMEOUT_SECONDS),
            max_retries=2,
        )
    return DefaultOpenAICompatibleProvider._clients[base_url]


ToolExecutor = Callable[[str, dict], Awaitable[dict]]
ActionCollector = Callable[[str, dict, dict], dict | None]


async def noop_tool_executor(name: str, args: dict) -> dict:
    """Shared ToolExecutor for no-tools calls (``tools=[]`` + ``max_rounds=1``).

    Never invoked (``tools=[]`` means the loop never reaches a tool_use
    branch), but AIProviderExtension.complete()/stream() requires a real
    callable. Used by sql_generator.generate_sql, the admin AI probe and
    service's map-spec retry/repair rounds.
    """
    return {}


class ToolLoopExhaustedError(Exception):
    """Raised when the tool-calling loop exceeds the maximum number of rounds.

    Carries the tokens the loop had already spent. The provider bills them
    even when the loop exhausts its rounds, budget or wall clock, and
    MAX_AI_TOKENS_PER_USER_PER_DAY sums ``catalog.ai_token_usage``, so they
    must be recorded or a caller who reliably exhausts the loop spends real
    money at a recorded balance of zero.

    The counts ride here rather than on a new ``complete()`` parameter
    because that signature is an extension Protocol: a new keyword forces an
    EXTENSION_API_VERSION bump on every overlay.
    """

    def __init__(
        self,
        message: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class UserFacingAIError(ValueError):
    """A message deliberately written for the end user.

    Passing every ValueError through would be an open set:
    ``OpenAICredentialDestinationError`` is a ValueError too, and names the
    configured provider endpoint. Only a message raised as THIS type reaches a
    viewer; every other ValueError gets generic text and keeps its detail in
    the log.

    Subclasses ``ValueError`` so existing ``except ValueError`` handlers
    keep working unchanged. ``code``, when set, is a stable identifier the
    client localizes instead of showing the English message.
    """

    code: str | None = None


def safe_stream_error_message(exc: BaseException) -> str:
    """The text an SSE ``error`` frame may carry for ``exc``."""
    if isinstance(exc, UserFacingAIError):
        return str(exc)
    return "An unexpected error occurred. Please try again."


def stream_error_event(exc: BaseException) -> dict[str, str]:
    """The SSE ``error`` frame for an exception raised inside a stream."""
    event = {"type": "error", "message": safe_stream_error_message(exc)}
    if isinstance(exc, UserFacingAIError) and exc.code:
        event["code"] = exc.code
    return event


def attach_token_usage(
    exc: BaseException, input_tokens: int, output_tokens: int
) -> None:
    """Stamp the tokens a tool loop had already spent onto the error it raised.

    Every exit from both provider loops routes through here, not only
    ``ToolLoopExhaustedError``: a provider that fails after one billed round,
    or a tool executor that raises after one, otherwise spends real money with
    the daily quota unchanged.

    Cancellation is stamped too: ``asyncio.wait_for`` raises ``TimeoutError``
    ``from`` the ``CancelledError``, so counts survive on ``__cause__`` and
    :func:`token_usage_from_error` walks that chain.

    Best-effort: an exception with ``__slots__`` can't take the attributes,
    and losing the accounting must never replace the real error.
    """
    try:
        exc.input_tokens = input_tokens  # type: ignore[attr-defined]
        exc.output_tokens = output_tokens  # type: ignore[attr-defined]
    except Exception:  # broad: accounting must never mask the original failure
        pass


def parse_structured_reply(
    response_model: type[BaseModel],
    text: str,
    *,
    stopped_early: str | None,
    input_tokens: int,
    output_tokens: int,
) -> BaseModel:
    """Validate a structured reply the provider billed.

    Raises when ``stopped_early`` names why the reply is partial, or when
    ``text`` does not validate; either error carries the reply's usage.
    """
    try:
        if stopped_early:
            raise ValueError(stopped_early)
        return response_model.model_validate_json(text)
    except Exception as exc:  # broad: a stop or parse failure still billed
        attach_token_usage(exc, input_tokens, output_tokens)
        raise


# Depth bound on the __cause__/__context__ walk below. wait_for's
# TimeoutError -> CancelledError plus a re-raise or two fit well inside it; the
# bound keeps a very deep chain from spinning.
_TOKEN_USAGE_CHAIN_DEPTH = 5


def token_usage_from_error(exc: BaseException) -> tuple[int, int]:
    """Read the stamped counts off ``exc`` or the exception that caused it."""
    seen: set[int] = set()
    current: BaseException | None = exc
    for _ in range(_TOKEN_USAGE_CHAIN_DEPTH):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        input_tokens = int(getattr(current, "input_tokens", 0) or 0)
        output_tokens = int(getattr(current, "output_tokens", 0) or 0)
        if input_tokens or output_tokens:
            return input_tokens, output_tokens
        current = current.__cause__ or current.__context__
    return 0, 0


def add_tool_cache_control(tools: list[dict]) -> list[dict]:
    """Add cache_control to the last tool definition for Anthropic prompt caching."""
    if not tools:
        return tools
    cached = [dict(t) for t in tools]
    cached[-1] = {**cached[-1], "cache_control": {"type": "ephemeral"}}
    return cached


@dataclass
class ToolLoopResult:
    """Result from a tool-calling loop."""

    text: str
    actions: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    # The final reply stopped early (token limit or content filter), so its
    # text is partial and nothing in it should be acted on.
    truncated: bool = False


async def resolve_provider(db) -> tuple[str, str, dict[str, object]]:
    """Resolve (provider_name, model, runtime_config) from PersistentConfig.

    Returns a ``runtime_config`` dict, not just ``base_url``:
    ``runtime_config["base_url"]`` is None for Anthropic, the endpoint URL
    for ``"openai_compatible"``. Each provider class supplies its own
    ``resolve_runtime_config(db)``, so the provider if/elif lives in the
    provider classes, not here.
    """
    from app.platform.extensions import get_ai_provider

    name = await LLM_PROVIDER.get(db)
    provider_ext = get_ai_provider(name)
    runtime_config = await provider_ext.resolve_runtime_config(db)
    model = await LLM_MODEL.for_provider(db, name, runtime_config)
    return name, model, runtime_config


def build_history_messages(history: list[dict] | None) -> list[dict]:
    """Convert generic history dicts to provider message format.

    Filters to user/assistant roles only. Works for both Anthropic and OpenAI.
    """
    if not history:
        return []
    return [
        {"role": msg["role"], "content": msg["content"]}
        for msg in history
        if msg["role"] in ("user", "assistant")
    ]
