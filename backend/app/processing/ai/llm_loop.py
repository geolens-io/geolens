"""LLM provider runtime helpers (Phase 226 surviving surface).

The tool-calling loop bodies (``_loop_anthropic`` / ``_loop_openai``) were moved
to ``DefaultAnthropicProvider.complete`` and ``DefaultOpenAICompatibleProvider.complete``
in ``app.platform.extensions.defaults`` (Phase 226 D-17/D-18). What remains here:

  - SDK client cache helpers (``get_anthropic_client``, ``get_openai_client``) —
    kept as module-level utilities so streaming.py / sql_generator.py /
    metadata_service.py can import them without going through the registry.
  - ``add_tool_cache_control`` — pure Anthropic-format helper used by streaming.py.
  - ``ToolLoopResult`` / ``ToolLoopExhaustedError`` / ``ToolExecutor`` / ``ActionCollector``
    — type machinery forward-referenced from ``platform/extensions/protocols.py``.
  - ``resolve_provider(db)`` — returns ``(name, model, runtime_config)`` tuple
    (Phase 226 D-21) by delegating ``runtime_config`` resolution to the named
    provider's ``resolve_runtime_config(db)`` method.
  - ``build_history_messages(history)`` — provider-agnostic role filter.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
import structlog

from app.core.config import reveal, settings
from app.core.persistent_config import LLM_MODEL, LLM_PROVIDER

if TYPE_CHECKING:
    # Provider SDK types referenced in annotations only.
    # Runtime imports are deferred to factory functions (open-core boundary —
    # SDK packages must not be loaded at module-import time within processing/).
    from anthropic import AsyncAnthropic
    from openai import AsyncOpenAI

# Timeout for individual LLM API calls (prevents indefinite hangs)
_LLM_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

logger = structlog.stdlib.get_logger(__name__)

# Phase 226 D-25: module-level _cached_anthropic_client / _cached_openai_clients
# singletons removed — cache state now lives on DefaultAnthropicProvider._client
# and DefaultOpenAICompatibleProvider._clients class attributes (Plan 01).
# These functions remain as module-level utilities so streaming.py /
# metadata_service.py keep their existing import path (RESEARCH.md Pitfall 4).


def get_anthropic_client() -> AsyncAnthropic:
    """Return the cached Anthropic SDK client.

    Cache lives on DefaultAnthropicProvider._client (Phase 226 D-25).
    Used by streaming.py and metadata_service.py, which import this function
    directly rather than going through the provider Protocol because their
    dispatch paths are deferred-scope (RESEARCH.md Open Questions 1 & 2).

    Surfaces the missing-key failure here (REVIEW.md WR-01) so callers see a
    clear ValueError instead of an opaque AuthenticationError on the first
    request. Mirrors the guard at DefaultAnthropicProvider.complete().
    """
    if not settings.anthropic_api_key:
        raise ValueError("Anthropic API key not configured")

    # Deferred imports:
    #   - DefaultAnthropicProvider — avoids module-import cycle
    #     (llm_loop -> defaults -> imports _LLM_TIMEOUT etc. from llm_loop)
    #   - AsyncAnthropic — keeps the SDK out of module-import scope so
    #     `processing/` carries zero top-level provider-SDK imports
    #     (oc-audit 2026-05-02 §5; lifts Phase 226 follow-up)
    from anthropic import AsyncAnthropic
    from app.platform.extensions.defaults import DefaultAnthropicProvider

    if DefaultAnthropicProvider._client is None:
        DefaultAnthropicProvider._client = AsyncAnthropic(
            api_key=reveal(settings.anthropic_api_key),
            timeout=_LLM_TIMEOUT,
            max_retries=2,
        )
    return DefaultAnthropicProvider._client


def get_openai_client(base_url: str) -> AsyncOpenAI:
    """Return the cached OpenAI-compatible SDK client for ``base_url``.

    Cache lives on DefaultOpenAICompatibleProvider._clients dict (Phase 226 D-25).
    Used by streaming.py, which imports this function directly (deferred-scope
    per RESEARCH.md Open Question 1).

    Surfaces the missing-key failure here (REVIEW.md WR-01) so callers see a
    clear ValueError instead of an opaque AuthenticationError on the first
    request. Mirrors the guard at DefaultOpenAICompatibleProvider.complete().
    """
    if not settings.openai_api_key:
        raise ValueError("OpenAI-compatible API key not configured")

    # Re-check at the SDK boundary.  Runtime config normally validates this
    # first, but direct callers and stale imported DB rows must fail before a
    # client can attach the environment credential to an untrusted URL.
    from app.core.ai_credentials import bind_openai_credential_base_url

    base_url = bind_openai_credential_base_url(base_url, purpose="chat")

    # Deferred imports — see get_anthropic_client() rationale.
    from openai import AsyncOpenAI
    from app.platform.extensions.defaults import DefaultOpenAICompatibleProvider

    if base_url not in DefaultOpenAICompatibleProvider._clients:
        DefaultOpenAICompatibleProvider._clients[base_url] = AsyncOpenAI(
            api_key=reveal(settings.openai_api_key),
            base_url=base_url,
            timeout=_LLM_TIMEOUT,
            max_retries=2,
        )
    return DefaultOpenAICompatibleProvider._clients[base_url]


# Type aliases for callbacks
ToolExecutor = Callable[[str, dict], Awaitable[dict]]
ActionCollector = Callable[[str, dict, dict], dict | None]


async def noop_tool_executor(name: str, args: dict) -> dict:
    """Shared ToolExecutor for no-tools calls (``tools=[]`` + ``max_rounds=1``).

    The tool loop only reaches a tool_use/tool_calls branch when the model was
    offered tools, so with ``tools=[]`` this is never actually invoked — it
    exists to satisfy AIProviderExtension.complete()/stream(), which requires
    a real callable. A registered provider (community default or overlay) is
    entitled to treat ``tool_executor`` as an always-callable value, so the
    no-tools call sites (sql_generator.generate_sql, the admin AI probe,
    service's map-spec retry/repair rounds) share this one definition instead
    of each constructing their own throwaway closure.
    """
    return {}


class ToolLoopExhaustedError(Exception):
    """Raised when the tool-calling loop exceeds the maximum number of rounds.

    fix(#1778): carries the tokens the loop had already spent. The blocking
    loop accumulated per-round counts and threw them away on every failure
    exit, so its most expensive requests -- the ones that ran all eight rounds,
    blew MAX_REQUEST_TOKEN_BUDGET, or hit the wall clock -- were billed by the
    provider and contributed nothing to ``catalog.ai_token_usage``.
    MAX_AI_TOKENS_PER_USER_PER_DAY is enforced by SUMming that table, so a
    caller who could reliably drive the loop to exhaustion kept a recorded
    balance of zero while spending real money. fix(#402) closed the same class
    for the streaming path by recording each round as it completed; the
    blocking loop took #448's budget guards and never the accounting.

    The counts ride here rather than on a new ``complete()`` parameter because
    that signature is an extension Protocol: adding a keyword to it forces an
    EXTENSION_API_VERSION bump on every overlay, which is a far larger change
    than the accounting it would carry.
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

    fix(#1778 round 1): the SSE generators used to pass every ``ValueError``
    through to the browser on the reasoning that this pipeline raises one for
    its own user-facing refusals. That is an open set, not a closed one:
    ``OpenAICredentialDestinationError`` is a ``ValueError`` too, and it names
    the configured provider endpoint. Only a message raised as THIS type
    reaches a viewer; every other ``ValueError`` gets the generic text and
    keeps its detail in the log.

    Subclassing ``ValueError`` keeps every existing ``except ValueError``
    handler on these paths working unchanged.
    """


def safe_stream_error_message(exc: BaseException) -> str:
    """The text an SSE ``error`` frame may carry for ``exc`` (fix(#1778))."""
    if isinstance(exc, UserFacingAIError):
        return str(exc)
    return "An unexpected error occurred. Please try again."


def attach_token_usage(
    exc: BaseException, input_tokens: int, output_tokens: int
) -> None:
    """Stamp the tokens a tool loop had already spent onto the error it raised.

    fix(#1778 round 1): attaching them only to ``ToolLoopExhaustedError`` left
    every other exit from the loop unaccounted. A provider that answers one
    round and then fails, or a tool executor that raises after a successful
    round, has already been billed for that round; without a stamp the caller's
    recorder no-ops and repeated induced failures spend real money while the
    daily quota stays where it was. This is the one place that decides, and
    every exit from both provider loops routes through it.

    Cancellation is stamped too. ``asyncio.wait_for`` raises ``TimeoutError``
    ``from`` the ``CancelledError`` it delivered to the coroutine, so the
    counts survive on ``__cause__`` (verified on the pinned CPython) and
    :func:`token_usage_from_error` walks that chain.

    Best-effort by design: an exception type with ``__slots__`` cannot take the
    attributes, and losing the accounting must never replace the real error.
    """
    try:
        exc.input_tokens = input_tokens  # type: ignore[attr-defined]
        exc.output_tokens = output_tokens  # type: ignore[attr-defined]
    except Exception:  # broad: accounting must never mask the original failure
        pass


# Depth bound on the __cause__/__context__ walk below. Three hops covers
# wait_for's TimeoutError -> CancelledError and one layer of re-raise; the
# bound exists so a self-referential or very deep chain cannot spin.
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


async def resolve_provider(db) -> tuple[str, str, dict[str, object]]:
    """Resolve (provider_name, model, runtime_config) from PersistentConfig.

    Phase 226 D-10/D-21: returns ``runtime_config`` dict (was ``base_url``).
    ``runtime_config["base_url"]`` is None for Anthropic, the OpenAI-compatible
    endpoint URL for ``"openai_compatible"``. Each provider class supplies its
    own ``resolve_runtime_config(db)`` so the if/elif on the provider name
    moves out of llm_loop and into the provider classes.

    Callers update tuple unpacking from ``(provider, model, base_url)`` to
    ``(provider, model, runtime_config)`` and read ``runtime_config["base_url"]``
    where needed (RESEARCH.md Pitfall 3 — closed-set: 4 callers in
    service.py:660,741, chat_service.py:934, streaming.py:509).
    """
    from app.platform.extensions import get_ai_provider

    name = await LLM_PROVIDER.get(db)
    provider_ext = get_ai_provider(name)
    runtime_config = await provider_ext.resolve_runtime_config(db)
    model = await LLM_MODEL.get(db) or runtime_config.get("default_model", "")
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
