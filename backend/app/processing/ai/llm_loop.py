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

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx
import structlog
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.core.config import reveal, settings
from app.core.persistent_config import LLM_MODEL, LLM_PROVIDER

# Timeout for individual LLM API calls (prevents indefinite hangs)
_LLM_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

logger = structlog.stdlib.get_logger(__name__)

# Module-level client singletons to avoid per-request connection overhead
_cached_anthropic_client: AsyncAnthropic | None = None
_cached_openai_clients: dict[str, AsyncOpenAI] = {}


def get_anthropic_client() -> AsyncAnthropic:
    global _cached_anthropic_client
    if _cached_anthropic_client is None:
        _cached_anthropic_client = AsyncAnthropic(
            api_key=reveal(settings.anthropic_api_key),
            timeout=_LLM_TIMEOUT,
            max_retries=2,
        )
    return _cached_anthropic_client


def get_openai_client(base_url: str) -> AsyncOpenAI:
    if base_url not in _cached_openai_clients:
        _cached_openai_clients[base_url] = AsyncOpenAI(
            api_key=reveal(settings.openai_api_key),
            base_url=base_url,
            timeout=_LLM_TIMEOUT,
            max_retries=2,
        )
    return _cached_openai_clients[base_url]


# Type aliases for callbacks
ToolExecutor = Callable[[str, dict], Awaitable[dict]]
ActionCollector = Callable[[str, dict, dict], dict | None]


class ToolLoopExhaustedError(Exception):
    """Raised when the tool-calling loop exceeds the maximum number of rounds."""


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
