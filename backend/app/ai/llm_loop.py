"""Generic async LLM tool-calling loop for Anthropic and OpenAI providers.

Consolidates the tool-calling orchestration that was previously duplicated
across service.py (generate-map) and chat_service.py (chat editing).
Both paths now call `run_tool_loop()` with their respective tool executors.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx
import structlog
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.ai.constants import MAX_TOOL_ROUNDS
from app.ai.tool_call_parser import parse_xml_tool_calls
from app.config import settings
from app.persistent_config import LLM_MODEL, LLM_PROVIDER, OPENAI_BASE_URL

# Timeout for individual LLM API calls (prevents indefinite hangs)
_LLM_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

logger = structlog.stdlib.get_logger(__name__)

# Module-level client singletons to avoid per-request connection overhead
_cached_anthropic_client: AsyncAnthropic | None = None
_cached_openai_clients: dict[str, AsyncOpenAI] = {}


def get_anthropic_client() -> AsyncAnthropic:
    global _cached_anthropic_client
    if _cached_anthropic_client is None:
        api_key = (
            settings.anthropic_api_key.get_secret_value()
            if settings.anthropic_api_key
            else None
        )
        _cached_anthropic_client = AsyncAnthropic(
            api_key=api_key, timeout=_LLM_TIMEOUT, max_retries=2
        )
    return _cached_anthropic_client


def get_openai_client(base_url: str) -> AsyncOpenAI:
    if base_url not in _cached_openai_clients:
        api_key = (
            settings.openai_api_key.get_secret_value()
            if settings.openai_api_key
            else None
        )
        _cached_openai_clients[base_url] = AsyncOpenAI(
            api_key=api_key,
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


async def run_tool_loop(
    *,
    provider: str,
    model: str,
    system_prompt: str,
    user_message: str,
    tools_anthropic: list[dict],
    tools_openai: list[dict],
    tool_executor: ToolExecutor,
    action_collector: ActionCollector | None = None,
    history: list[dict] | None = None,
    max_rounds: int = MAX_TOOL_ROUNDS,
    max_tokens: int = 4096,
    base_url: str | None = None,
    temperature: float = 0.5,
) -> ToolLoopResult:
    """Run an async LLM tool-calling loop with either provider.

    Args:
        provider: "anthropic" or "openai_compatible"
        model: Model identifier string
        system_prompt: System instructions
        user_message: The user's current message
        tools_anthropic: Tool definitions in Anthropic format
        tools_openai: Tool definitions in OpenAI format
        tool_executor: Async callback(tool_name, tool_input) -> result dict
        action_collector: Optional callback(tool_name, tool_input, result) -> action dict or None
        history: Optional prior conversation messages (provider-agnostic dicts with role/content)
        max_rounds: Maximum tool-calling rounds
        max_tokens: Max output tokens per LLM call
        base_url: OpenAI-compatible base URL (from PersistentConfig)

    Returns:
        ToolLoopResult with final text, collected actions, and token usage.
    """
    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("Anthropic API key not configured")
        return await _loop_anthropic(
            model=model,
            system_prompt=system_prompt,
            user_message=user_message,
            tools=tools_anthropic,
            tool_executor=tool_executor,
            action_collector=action_collector,
            history=history,
            max_rounds=max_rounds,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    elif provider == "openai_compatible":
        if not settings.openai_api_key:
            raise ValueError("OpenAI-compatible API key not configured")
        return await _loop_openai(
            model=model,
            system_prompt=system_prompt,
            user_message=user_message,
            tools=tools_openai,
            tool_executor=tool_executor,
            action_collector=action_collector,
            history=history,
            max_rounds=max_rounds,
            max_tokens=max_tokens,
            base_url=base_url,
            temperature=temperature,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


async def resolve_provider(db) -> tuple[str, str, str | None]:
    """Resolve provider, model, and base_url from persistent config.

    Returns (provider, model, openai_base_url).
    """
    provider = await LLM_PROVIDER.get(db)
    model = await LLM_MODEL.get(db)
    base_url = None
    if provider == "openai_compatible":
        base_url = await OPENAI_BASE_URL.get(db) or "https://api.openai.com/v1"
    return provider, model, base_url


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


async def _loop_anthropic(
    *,
    model: str,
    system_prompt: str,
    user_message: str,
    tools: list[dict],
    tool_executor: ToolExecutor,
    action_collector: ActionCollector | None,
    history: list[dict] | None,
    max_rounds: int,
    max_tokens: int,
    temperature: float = 0.5,
) -> ToolLoopResult:
    """Async Anthropic tool-calling loop."""
    client = get_anthropic_client()

    messages = build_history_messages(history)
    messages.append({"role": "user", "content": user_message})

    # Enable prompt caching for system prompt and tools
    cached_system = [
        {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
    ]
    cached_tools = add_tool_cache_control(tools)

    collected_actions: list[dict] = []
    total_input = 0
    total_output = 0

    for round_num in range(max_rounds):
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=cached_system,
            tools=cached_tools,
            messages=messages,
        )

        # Track token usage
        if hasattr(response, "usage") and response.usage:
            total_input += response.usage.input_tokens
            total_output += response.usage.output_tokens

        logger.info(
            "LLM round",
            provider="anthropic",
            round=round_num + 1,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens if response.usage else 0,
            output_tokens=response.usage.output_tokens if response.usage else 0,
        )

        if response.stop_reason == "end_turn":
            text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            return ToolLoopResult(
                text=text,
                actions=collected_actions,
                input_tokens=total_input,
                output_tokens=total_output,
            )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info("Tool call", tool=block.name, input=block.input)

                    result = await tool_executor(block.name, block.input)

                    if action_collector:
                        action = action_collector(block.name, block.input, result)
                        if action:
                            collected_actions.append(action)

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        }
                    )

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason — return whatever text we have
        text = "".join(block.text for block in response.content if block.type == "text")
        return ToolLoopResult(
            text=text,
            actions=collected_actions,
            input_tokens=total_input,
            output_tokens=total_output,
        )

    raise ToolLoopExhaustedError("Max tool rounds exceeded without final response")


async def _loop_openai(
    *,
    model: str,
    system_prompt: str,
    user_message: str,
    tools: list[dict],
    tool_executor: ToolExecutor,
    action_collector: ActionCollector | None,
    history: list[dict] | None,
    max_rounds: int,
    max_tokens: int,
    base_url: str | None = None,
    temperature: float = 0.5,
) -> ToolLoopResult:
    """Async OpenAI-compatible tool-calling loop."""
    base_url_val = base_url or settings.openai_base_url or "https://api.openai.com/v1"
    client = get_openai_client(base_url_val)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(build_history_messages(history))
    messages.append({"role": "user", "content": user_message})

    collected_actions: list[dict] = []
    total_input = 0
    total_output = 0

    for round_num in range(max_rounds):
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            messages=messages,
        )

        choice = response.choices[0]

        # Track token usage
        if response.usage:
            total_input += response.usage.prompt_tokens
            total_output += response.usage.completion_tokens

        logger.info(
            "LLM round",
            provider="openai",
            round=round_num + 1,
            finish_reason=choice.finish_reason,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
        )

        if choice.finish_reason == "stop":
            text = choice.message.content or ""
            parsed_calls, cleaned_text = parse_xml_tool_calls(text)

            if parsed_calls:
                # Execute parsed XML tool calls
                for fn_name, fn_args in parsed_calls:
                    logger.info("Parsed XML tool call", tool=fn_name, input=fn_args)
                    result = await tool_executor(fn_name, fn_args)
                    if action_collector:
                        action = action_collector(fn_name, fn_args, result)
                        if action:
                            collected_actions.append(action)

                return ToolLoopResult(
                    text=cleaned_text,
                    actions=collected_actions,
                    input_tokens=total_input,
                    output_tokens=total_output,
                )

            return ToolLoopResult(
                text=text,
                actions=collected_actions,
                input_tokens=total_input,
                output_tokens=total_output,
            )

        if choice.finish_reason == "tool_calls":
            messages.append(choice.message)

            for tool_call in choice.message.tool_calls:
                fn_name = tool_call.function.name
                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    try:
                        fn_args, _ = json.JSONDecoder().raw_decode(
                            tool_call.function.arguments
                        )
                    except (json.JSONDecodeError, ValueError):
                        logger.warning(
                            "Unparseable tool arguments",
                            tool=fn_name,
                            args=tool_call.function.arguments,
                        )
                        continue
                logger.info("Tool call", tool=fn_name, input=fn_args)

                result = await tool_executor(fn_name, fn_args)

                if action_collector:
                    action = action_collector(fn_name, fn_args, result)
                    if action:
                        collected_actions.append(action)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    }
                )
            continue

        # Unexpected finish reason
        return ToolLoopResult(
            text=choice.message.content or "",
            actions=collected_actions,
            input_tokens=total_input,
            output_tokens=total_output,
        )

    raise ToolLoopExhaustedError("Max tool rounds exceeded without final response")
