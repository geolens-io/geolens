"""Structured JSON replies from Claude, through whichever request the model takes.

Structured outputs (``output_config.format``) is the only way to get JSON from
models that reject a forced ``tool_choice`` (Sonnet 5.5, Opus 5.5, Fable 5.1).
Some models and platforms reject structured outputs instead, and those still
answer a forced tool call. The first request uses structured outputs; a
rejection naming the other parameter switches to the other request once, and
the working choice is remembered per platform and model for the process.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel

from app.core.config import settings
from app.processing.ai.llm_loop import parse_structured_reply

if TYPE_CHECKING:
    from anthropic import BadRequestError

logger = structlog.stdlib.get_logger(__name__)

_STRUCTURED = "structured"
_FORCED_TOOL = "forced_tool"
_TOOL_NAME = "output"

# Process-local: a restart re-learns each choice with one rejected request.
_requests: dict[tuple[str, str], str] = {}


def _message(exc: BadRequestError) -> str:
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error") if isinstance(body.get("error"), dict) else body
    return str(error.get("message") or "")


def _rejects_structured_outputs(exc: BadRequestError) -> bool:
    message = _message(exc).lower()
    names_parameter = any(
        name in message
        for name in ("output_config", "output_format", "structured output")
    )
    refuses = any(
        word in message
        for word in ("not supported", "unsupported", "not permitted", "extraneous key")
    )
    return names_parameter and refuses


def _rejects_forced_tool(exc: BadRequestError) -> bool:
    message = _message(exc)
    return message.startswith("tool_choice:") and "not supported" in message


def _request(choice: str, response_model: type[BaseModel]) -> dict[str, Any]:
    from anthropic import transform_schema

    schema = transform_schema(response_model)
    if choice == _STRUCTURED:
        return {"output_config": {"format": {"type": "json_schema", "schema": schema}}}
    return {
        "tools": [
            {
                "name": _TOOL_NAME,
                "description": "Output the structured result",
                "input_schema": schema,
            }
        ],
        "tool_choice": {"type": "tool", "name": _TOOL_NAME},
    }


def _parse(choice: str, response: Any, response_model: type[BaseModel]) -> BaseModel:
    if choice == _STRUCTURED:
        finished = response.stop_reason == "end_turn"
        text = "".join(b.text for b in response.content if b.type == "text")
    else:
        finished = response.stop_reason == "tool_use"
        text = next(
            (json.dumps(b.input) for b in response.content if b.type == "tool_use"),
            "",
        )
    return parse_structured_reply(
        response_model,
        text,
        stopped_early=None
        if finished
        else f"Claude stopped with {response.stop_reason}",
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


async def claude_structured_reply(
    client: Any,
    *,
    model: str,
    system_prompt: str,
    user_message: str,
    response_model: type[BaseModel],
    max_tokens: int,
) -> tuple[BaseModel, int, int]:
    """Ask Claude for one ``response_model`` reply; returns it with token counts.

    A reply that stops early or does not validate raises with its billed usage
    attached. Any rejection other than the two request shapes is re-raised.
    """
    from anthropic import BadRequestError

    key = (settings.anthropic_platform, model)
    choice = _requests.get(key, _STRUCTURED)
    switched = False
    while True:
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                **_request(choice, response_model),
            )
        except BadRequestError as exc:
            rejected = (
                _rejects_structured_outputs(exc)
                if choice == _STRUCTURED
                else _rejects_forced_tool(exc)
            )
            if switched or not rejected:
                raise
            choice = _FORCED_TOOL if choice == _STRUCTURED else _STRUCTURED
            switched = True
            logger.info(
                "Switched Claude structured request", model=model, request=choice
            )
            continue
        _requests[key] = choice
        parsed = _parse(choice, response, response_model)
        return parsed, response.usage.input_tokens, response.usage.output_tokens
