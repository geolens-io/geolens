"""One OpenAI-compatible chat, over Chat Completions or the Responses API.

The tool loop and streamed chat drive a conversation round by round. The two
APIs differ in how messages, tool calls, tool results, stream events and
usage are shaped; :func:`open_conversation` picks the API from
``OPENAI_API_STYLE`` and both classes expose the same rounds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.platform.ai_tool_payloads import tool_result_content
from app.processing.ai.llm_loop import build_history_messages
from app.processing.ai.openai_request import (
    create_chat_completion,
    create_response,
)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class Round:
    """What the model returned in one request."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # "tool_calls" when the model called tools, "stop" when it finished.
    finish_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class StreamDelta:
    """One streamed increment: text, a tool call starting, or usage."""

    text: str = ""
    tool_name: str = ""
    usage: tuple[int, int] | None = None


class ResponsesStreamError(RuntimeError):
    """The Responses stream failed or ended without a final response."""


def open_conversation(
    client: Any,
    *,
    base_url: str | None,
    model: str,
    system_prompt: str,
    history: list[dict] | None,
    user_message: str,
    tools: list[dict],
    max_tokens: int,
    temperature: float,
) -> ChatCompletionsConversation | ResponsesConversation:
    """Start a conversation on the API ``OPENAI_API_STYLE`` selects.

    ``tools`` are in the canonical Anthropic shape (``name``,
    ``description``, ``input_schema``).
    """
    style = (
        ResponsesConversation
        if settings.openai_api_style == "responses"
        else ChatCompletionsConversation
    )
    return style(
        client,
        base_url=base_url,
        model=model,
        system_prompt=system_prompt,
        history=history,
        user_message=user_message,
        tools=tools,
        max_tokens=max_tokens,
        temperature=temperature,
    )


async def structured_completion(
    client: Any,
    *,
    base_url: str | None,
    model: str,
    system_prompt: str,
    user_message: str,
    response_model: type,
    max_tokens: int,
    temperature: float,
) -> tuple[Any, int, int]:
    """Parse one reply into ``response_model``; returns it with token counts."""
    if settings.openai_api_style == "responses":
        response = await create_response(
            client.responses.parse,
            base_url=base_url,
            model=model,
            instructions=system_prompt,
            input=[{"role": "user", "content": user_message}],
            text_format=response_model,
            max_tokens=max_tokens,
            temperature=temperature,
            store=False,
        )
        parsed = response.output_parsed
        usage = response.usage
        input_tokens = usage.input_tokens if usage else 0
        output_tokens = usage.output_tokens if usage else 0
    else:
        response = await create_chat_completion(
            client.beta.chat.completions.parse,
            base_url=base_url,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format=response_model,
        )
        parsed = response.choices[0].message.parsed
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
    if parsed is None:
        raise ValueError("OpenAI returned no parsed response")
    return parsed, input_tokens, output_tokens


class ChatCompletionsConversation:
    def __init__(
        self,
        client: Any,
        *,
        base_url: str | None,
        model: str,
        system_prompt: str,
        history: list[dict] | None,
        user_message: str,
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> None:
        self._client = client
        self._base_url = base_url
        self._request: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # Servers reject `tools=[]`; omit it for no-tools calls.
        if tools:
            self._request["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]
        self._messages: list[Any] = [{"role": "system", "content": system_prompt}]
        self._messages.extend(build_history_messages(history))
        self._messages.append({"role": "user", "content": user_message})

    async def complete(self) -> Round:
        response = await create_chat_completion(
            self._client.chat.completions.create,
            base_url=self._base_url,
            messages=self._messages,
            **self._request,
        )
        choice = response.choices[0]
        usage = response.usage
        return Round(
            text=choice.message.content or "",
            tool_calls=[
                ToolCall(tc.id, tc.function.name, tc.function.arguments)
                for tc in choice.message.tool_calls or []
            ],
            finish_reason=choice.finish_reason,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    async def stream(self) -> AsyncIterator[StreamDelta | Round]:
        """Yield the round's deltas, then the finished :class:`Round`."""
        response_stream = await create_chat_completion(
            self._client.chat.completions.create,
            base_url=self._base_url,
            messages=self._messages,
            stream=True,
            # Usage arrives only on request, on the final chunk.
            stream_options={"include_usage": True},
            **self._request,
        )
        result = Round()
        text_parts: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        async for chunk in response_stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                round_in = getattr(usage, "prompt_tokens", 0) or 0
                round_out = getattr(usage, "completion_tokens", 0) or 0
                result.input_tokens += round_in
                result.output_tokens += round_out
                yield StreamDelta(usage=(round_in, round_out))
            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue
            delta = choice.delta
            if delta and delta.content:
                text_parts.append(delta.content)
                yield StreamDelta(text=delta.content)
            for tc in (delta.tool_calls if delta else None) or []:
                entry = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                announced = bool(entry["name"])
                if tc.id:
                    entry["id"] = tc.id
                if tc.function and tc.function.name:
                    entry["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    entry["args"] += tc.function.arguments
                if entry["name"] and not announced:
                    yield StreamDelta(tool_name=entry["name"])
            if choice.finish_reason:
                result.finish_reason = choice.finish_reason
        result.text = "".join(text_parts)
        result.tool_calls = [
            ToolCall(c["id"], c["name"], c["args"]) for _, c in sorted(calls.items())
        ]
        yield result

    def add_tool_results(
        self, round_: Round, results: list[tuple[ToolCall, dict]]
    ) -> None:
        """Append the model's tool calls and the results that answer them."""
        self._messages.append(
            {
                "role": "assistant",
                "content": round_.text or None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in round_.tool_calls
                ],
            }
        )
        for call, result in results:
            self._messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    # Fenced, not bare JSON: results carry dataset content.
                    "content": tool_result_content(result),
                }
            )


class ResponsesConversation:
    def __init__(
        self,
        client: Any,
        *,
        base_url: str | None,
        model: str,
        system_prompt: str,
        history: list[dict] | None,
        user_message: str,
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> None:
        self._client = client
        self._base_url = base_url
        self._request: dict[str, Any] = {
            "model": model,
            "instructions": system_prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            # Chat Completions keeps nothing server-side; neither does this.
            # Without stored state, reasoning carries over between rounds
            # only as encrypted content.
            "store": False,
            "include": ["reasoning.encrypted_content"],
        }
        if tools:
            self._request["tools"] = [
                {
                    "type": "function",
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                }
                for t in tools
            ]
        self._input: list[dict] = build_history_messages(history)
        self._input.append({"role": "user", "content": user_message})
        self._output: list[dict] = []

    def _round(self, response: Any) -> Round:
        self._output = [item.model_dump(exclude_none=True) for item in response.output]
        calls = [
            ToolCall(item.call_id, item.name, item.arguments)
            for item in response.output
            if item.type == "function_call"
        ]
        text = "".join(
            part.text
            for item in response.output
            if item.type == "message"
            for part in item.content
            if part.type == "output_text"
        )
        if calls:
            finish_reason = "tool_calls"
        elif response.status == "completed":
            finish_reason = "stop"
        else:
            details = getattr(response, "incomplete_details", None)
            finish_reason = getattr(details, "reason", None) or response.status
        usage = response.usage
        return Round(
            text=text,
            tool_calls=calls,
            finish_reason=finish_reason,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
        )

    async def complete(self) -> Round:
        response = await create_response(
            self._client.responses.create,
            base_url=self._base_url,
            input=self._input,
            **self._request,
        )
        return self._round(response)

    async def stream(self) -> AsyncIterator[StreamDelta | Round]:
        """Yield the round's deltas, then the finished :class:`Round`."""
        events = await create_response(
            self._client.responses.create,
            base_url=self._base_url,
            input=self._input,
            stream=True,
            **self._request,
        )
        final = None
        async for event in events:
            if event.type == "response.output_text.delta":
                yield StreamDelta(text=event.delta)
            elif (
                event.type == "response.output_item.added"
                and event.item.type == "function_call"
            ):
                yield StreamDelta(tool_name=event.item.name)
            elif event.type in (
                "response.completed",
                "response.incomplete",
                "response.failed",
            ):
                final = event.response
                usage = final.usage
                if usage is not None:
                    yield StreamDelta(usage=(usage.input_tokens, usage.output_tokens))
                if event.type == "response.failed":
                    raise ResponsesStreamError("OpenAI Responses stream failed")
            elif event.type == "error":
                raise ResponsesStreamError("OpenAI Responses stream failed")
        if final is None:
            raise ResponsesStreamError("OpenAI Responses stream ended early")
        yield self._round(final)

    def add_tool_results(
        self, round_: Round, results: list[tuple[ToolCall, dict]]
    ) -> None:
        """Append the round's output items and the results that answer them."""
        self._input.extend(self._output)
        self._input.extend(
            {
                "type": "function_call_output",
                "call_id": call.id,
                # Fenced, not bare JSON: results carry dataset content.
                "output": tool_result_content(result),
            }
            for call, result in results
        )
