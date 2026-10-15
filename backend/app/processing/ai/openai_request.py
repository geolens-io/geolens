"""Chat Completions request shaping for OpenAI-compatible servers.

Servers disagree on request parameters: current OpenAI models reject
``max_tokens`` and non-default temperatures, older models and other servers
reject ``reasoning_effort``, and some reasoning models call function tools
only with ``reasoning_effort="none"``. Ollama and OpenRouter document
``max_tokens``, so the first request keeps the caller's shape and a
rejection naming one of these parameters adjusts it and retries. A rejected
request generates no tokens, so token accounting is unaffected.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, TypeVar

import structlog

from app.core.config import settings
from app.processing.ai.llm_loop import UserFacingAIError

if TYPE_CHECKING:
    from openai import BadRequestError

logger = structlog.stdlib.get_logger(__name__)

_T = TypeVar("_T")


class ResponsesAPIRequiredError(UserFacingAIError):
    """The model calls function tools only through the Responses API."""

    def __init__(self) -> None:
        super().__init__(
            "The configured AI model only calls tools through the OpenAI "
            "Responses API, which GeoLens does not support yet. Choose a "
            "different model."
        )


@dataclass(frozen=True)
class _Shape:
    token_param: str = "max_tokens"
    temperature: bool = True
    reasoning_effort: str | None = None


# Process-local: a restart re-learns each shape with at most one rejected
# request per parameter.
_shapes: dict[tuple[str | None, str], _Shape] = {}


def _apply(request: dict[str, Any], shape: _Shape) -> dict[str, Any]:
    kwargs = dict(request)
    if shape.token_param != "max_tokens" and "max_tokens" in kwargs:
        kwargs[shape.token_param] = kwargs.pop("max_tokens")
    if not shape.temperature:
        kwargs.pop("temperature", None)
    if shape.reasoning_effort is not None:
        kwargs["reasoning_effort"] = shape.reasoning_effort
    return kwargs


def _message(exc: BadRequestError) -> str:
    body = exc.body if isinstance(exc.body, dict) else {}
    return str(body.get("message") or "")


def _unsupported(exc: BadRequestError, param: str) -> bool:
    message = _message(exc)
    return (
        exc.param == param
        and exc.code in ("unsupported_parameter", "unsupported_value")
    ) or (
        f"Unsupported parameter: '{param}'" in message
        or f"Unsupported value: '{param}'" in message
    )


def _adjust(exc: BadRequestError, shape: _Shape) -> tuple[str, _Shape] | None:
    """The parameter a rejection names and the shape that avoids it."""
    message = _message(exc)
    if _unsupported(exc, shape.token_param):
        other = (
            "max_completion_tokens"
            if shape.token_param == "max_tokens"
            else "max_tokens"
        )
        return "tokens", replace(shape, token_param=other)
    if shape.temperature and _unsupported(exc, "temperature"):
        return "temperature", replace(shape, temperature=False)
    if (
        shape.reasoning_effort is not None
        and "Unrecognized request argument supplied: reasoning_effort" in message
    ):
        return "reasoning_effort", replace(shape, reasoning_effort=None)
    if shape.reasoning_effort != "none" and message.startswith(
        "Function tools with reasoning_effort are not supported"
    ):
        return "reasoning_effort", replace(shape, reasoning_effort="none")
    return None


async def create_chat_completion(
    create: Callable[..., Awaitable[_T]],
    *,
    base_url: str | None,
    **request: Any,
) -> _T:
    """Await ``create(**request)``, adapting rejected parameters.

    ``request`` carries ``model``, ``max_tokens`` and optionally
    ``temperature``; ``OPENAI_REASONING_EFFORT`` is added when set. Each
    parameter is adjusted at most once per call and only ``create()`` is
    retried. The working shape is remembered per ``(base_url, model)``.
    Raises :class:`ResponsesAPIRequiredError` when the model rejects
    ``reasoning_effort="none"`` for a request with tools, and re-raises any
    other rejection unchanged.
    """
    from openai import BadRequestError

    key = (base_url, request["model"])
    # Compose passes an unset variable through as "".
    shape = _shapes.get(key) or _Shape(
        reasoning_effort=settings.openai_reasoning_effort or None
    )
    adjusted: set[str] = set()
    while True:
        kwargs = _apply(request, shape)
        try:
            response = await create(**kwargs)
        except BadRequestError as exc:
            if (
                kwargs.get("tools")
                and kwargs.get("reasoning_effort") == "none"
                and _unsupported(exc, "reasoning_effort")
            ):
                raise ResponsesAPIRequiredError() from exc
            adjustment = _adjust(exc, shape)
            if adjustment is None or adjustment[0] in adjusted:
                raise
            param, shape = adjustment
            adjusted.add(param)
            logger.info(
                "Adjusted OpenAI-compatible request",
                model=request["model"],
                parameter=param,
            )
            continue
        _shapes[key] = shape
        return response
