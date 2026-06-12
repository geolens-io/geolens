"""PERF-009 regression — AI tool loop must stop on a cumulative token budget.

The streaming chat tool loop in ``app/processing/ai/streaming.py`` was bounded
only by round count (``MAX_TOOL_ROUNDS``), wall clock
(``MAX_STREAMING_WALL_CLOCK_SECONDS``), and the 10/min rate limit — none of which
cap cumulative provider token spend. A runaway/looping model could drive ~8
rounds x 4096 output tokens plus a growing input history per request.

The fix adds ``MAX_REQUEST_TOKEN_BUDGET`` and breaks the loop gracefully (the same
way it stops on max rounds) once ``total_input + total_output`` exceeds it.

This test drives ``_stream_anthropic_chat`` with a stub client whose per-round
usage is large enough that the cumulative total crosses the budget after the first
round. With ``MAX_TOOL_ROUNDS == 8`` the loop must instead stop after far fewer
rounds, with the "token budget exceeded" reason logged. ``_execute_and_yield_tools``
and ``record_token_usage`` are patched out so the test isolates the loop's
budget-control logic (no DB / no real tool execution).

Verify fail-before: remove the ``total_input + total_output > MAX_REQUEST_TOKEN_BUDGET``
guard from ``_stream_anthropic_chat`` and this test FAILS — the loop runs the full
MAX_TOOL_ROUNDS instead of stopping early.
"""

from __future__ import annotations

import uuid as _uuid
from types import SimpleNamespace

import pytest

import app.processing.ai.streaming as streaming
from app.processing.ai.constants import MAX_REQUEST_TOKEN_BUDGET, MAX_TOOL_ROUNDS


class _FakeStream:
    """Minimal async-context stream mimicking anthropic client.messages.stream()."""

    def __init__(self, final_message):
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def _gen():
            # No content_block events needed — the loop only inspects the final
            # message for stop_reason / usage / content.
            if False:
                yield None

        return _gen()

    async def get_final_message(self):
        return self._final_message


class _FakeToolUseBlock:
    type = "tool_use"
    id = "toolu_perf009"
    name = "search_datasets"
    input: dict = {}


class _FakeMessages:
    def __init__(self, per_round_input: int, per_round_output: int, rounds_seen: list):
        self._per_round_input = per_round_input
        self._per_round_output = per_round_output
        self._rounds_seen = rounds_seen

    def stream(self, **kwargs):
        self._rounds_seen.append(1)
        final_message = SimpleNamespace(
            stop_reason="tool_use",  # keep the loop going round after round
            usage=SimpleNamespace(
                input_tokens=self._per_round_input,
                output_tokens=self._per_round_output,
            ),
            content=[_FakeToolUseBlock()],
        )
        return _FakeStream(final_message)


class _FakeAnthropicClient:
    def __init__(self, per_round_input: int, per_round_output: int):
        self.rounds_seen: list = []
        self.messages = _FakeMessages(
            per_round_input, per_round_output, self.rounds_seen
        )


async def _noop_tools(*args, **kwargs):
    """Stub _execute_and_yield_tools — yield nothing so the loop just advances."""
    if False:
        yield None


@pytest.mark.anyio
async def test_anthropic_loop_stops_when_token_budget_exceeded(monkeypatch):
    """The Anthropic tool loop must break early once cumulative tokens exceed budget."""
    # Per-round usage large enough that cumulative crosses the budget after the
    # FIRST round's accounting — so the loop should stop on round 2's top check,
    # well before MAX_TOOL_ROUNDS.
    per_round = MAX_REQUEST_TOKEN_BUDGET  # one full round = the whole budget
    client = _FakeAnthropicClient(per_round_input=per_round, per_round_output=0)

    # Isolate the loop control: no real tool execution, no DB token write.
    monkeypatch.setattr(streaming, "_execute_and_yield_tools", _noop_tools)

    async def _noop_record(*args, **kwargs):
        return None

    monkeypatch.setattr(streaming, "record_token_usage", _noop_record)

    events = []
    gen = streaming._stream_anthropic_chat(
        message="hello",
        system_prompt="sys",
        session=SimpleNamespace(),  # only forwarded to patched-out callees
        user=SimpleNamespace(id=_uuid.uuid4()),
        user_roles=set(),
        layers=[],
        model="claude-test",
        history=None,
        client=client,
        port=SimpleNamespace(),
        map_id=None,
    )
    async for evt in gen:
        events.append(evt)

    # The loop must have stopped on the budget guard, NOT run all 8 rounds.
    rounds_run = len(client.rounds_seen)
    assert rounds_run < MAX_TOOL_ROUNDS, (
        f"loop ran {rounds_run} rounds — token budget guard did not fire "
        f"(PERF-009 regression; expected < {MAX_TOOL_ROUNDS})"
    )
    # With per-round == full budget, round 1 runs then round 2's top check trips.
    assert rounds_run == 2, (
        f"expected the loop to stop after 2 rounds (round 1 spends the budget, "
        f"round 2's top check breaks), got {rounds_run}"
    )


@pytest.mark.anyio
async def test_anthropic_loop_does_not_stop_below_budget(monkeypatch):
    """Sanity: small per-round usage must NOT trip the budget — loop ends on its own.

    Guards against an over-aggressive budget that would break legitimate
    multi-round chats. Here ``stop_reason='end_turn'`` ends the loop after one
    round; the budget guard must not be the thing that stops it.
    """

    class _EndTurnMessages(_FakeMessages):
        def stream(self, **kwargs):
            self._rounds_seen.append(1)
            final_message = SimpleNamespace(
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=10, output_tokens=10),
                content=[],
            )
            return _FakeStream(final_message)

    client = _FakeAnthropicClient(per_round_input=10, per_round_output=10)
    client.messages = _EndTurnMessages(10, 10, client.rounds_seen)

    monkeypatch.setattr(streaming, "_execute_and_yield_tools", _noop_tools)

    async def _noop_record(*args, **kwargs):
        return None

    monkeypatch.setattr(streaming, "record_token_usage", _noop_record)

    gen = streaming._stream_anthropic_chat(
        message="hello",
        system_prompt="sys",
        session=SimpleNamespace(),
        user=SimpleNamespace(id=_uuid.uuid4()),
        user_roles=set(),
        layers=[],
        model="claude-test",
        history=None,
        client=client,
        port=SimpleNamespace(),
        map_id=None,
    )
    async for _evt in gen:
        pass

    # Ended on end_turn after exactly one round — budget never involved.
    assert len(client.rounds_seen) == 1
