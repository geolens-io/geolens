"""Live-provider AI evals for chat TOOL CHOICE (#1007, follow-up to #549).

``test_sql_generation_evals.py`` asserts what the model WRITES once a tool has
been chosen. These watch WHICH TOOL it chooses for a given user message, which
is the layer routing bugs actually live in. #549 was "show me X" landing on
``set_filter`` instead of ``query_data``; its fix is prompt and tool-description
prose whose entire risk is that a later edit quietly reverses it, with nothing
in CI or in ``make ai-evals`` to notice.

Every case drives the production routing inputs rather than a reconstruction:

* the tool set comes from ``select_chat_tools(can_edit, has_map)``, and
* the system prompt from the same builders the chat surfaces use,
  ``build_chat_system_prompt`` for map chat (streaming.py:773,
  chat_service.py:370) and ``build_dataset_chat_system_prompt`` for
  dataset-scoped chat (router.py:716),

so an edit to either is what the eval sees. Nothing here restates a tool
description or a verb-class rule. If it did, the eval would keep passing after
the prose it protects changed, which is the failure mode this file exists to
prevent.

## What is checked

The emitted tool NAME, and for the surface cases the ABSENCE of tools the
surface does not offer. Never the response prose: a routing eval that reads
prose fails on wording changes that broke nothing.

## Cost and gating

Live-provider, real tokens. SKIPPED unless ``RUN_AI_EVALS=1``; run with::

    make ai-evals
    # or, this file only:
    cd backend && set -a && source ../.env.test && set +a && \\
        RUN_AI_EVALS=1 uv run pytest tests/evals/test_tool_choice_evals.py -v

Each case costs exactly ONE provider round-trip: ``_route()`` passes
``max_rounds=1`` and never executes a tool, so the loop stops as soon as the
routing decision is visible. No database rows are seeded, because tool choice
is decided entirely by the prompt and the tool set; the layers are in-memory
``ChatMapLayer`` values.

## Flake policy

Inherited from the SQL evals, with one caveat worth stating plainly:
``temperature=0.0`` is passed, but ``DefaultAnthropicProvider.complete`` deletes
the argument (Claude 4.6+ rejects a non-default temperature), so on the
Anthropic path determinism comes from the provider default rather than from
this call. It is honoured on the OpenAI-compatible path.

Checks therefore leave the model freedom everywhere it legitimately has it: a
case names one tool, or an absence, never a tool ARGUMENT and never the
accompanying text.

## Read the case table before you trust a result

Every row asserts (``stable=True``) as of #1135: three consecutive nightly
live runs (2026-08-03 .. 2026-08-05) routed every case to a consistent,
correct outcome, so a wrong tool now fails the run. The block comment above
``_CASES`` records the evidence and keeps the procedure for promoting any
future row, which must land as ``stable=False`` and earn its assertion the
same way.
"""

import os
import warnings
from dataclasses import dataclass

import pytest

from app.platform.extensions import get_ai_provider
from app.processing.ai.chat_service import (
    _EDIT_TOOLS,
    build_chat_system_prompt,
    build_dataset_chat_system_prompt,
)
from app.processing.ai.llm_loop import ToolLoopExhaustedError, resolve_provider
from app.processing.ai.schemas import ChatMapLayer
from app.processing.ai.tools import select_chat_tools

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        os.environ.get("RUN_AI_EVALS") != "1",
        reason="live-provider AI evals; set RUN_AI_EVALS=1 to run",
    ),
]

# Fixed ids, not uuid4(): identical prompts across runs keep Anthropic's
# ephemeral prompt cache warm, which is most of the token cost of a rerun.
_STATIONS_LAYER = ChatMapLayer(
    id="11111111-1111-4111-8111-111111111111",
    name="Subway Stations",
    dataset_id="aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
    dataset_table_name="eval_subway_stations",
    geometry_type="Point",
    dataset_title="Subway Stations",
    feature_count=472,
    column_info=[
        {"name": "gid", "type": "integer"},
        {"name": "name", "type": "text"},
        {"name": "line", "type": "text"},
        {"name": "ada_accessible", "type": "boolean"},
    ],
    sample_values={
        "name": ["Hoyt St", "Nostrand Av", "Utica Av"],
        "line": ["A", "C", "E"],
        "ada_accessible": [True, False],
    },
)

_PARCELS_LAYER = ChatMapLayer(
    id="22222222-2222-4222-8222-222222222222",
    name="Parcels",
    dataset_id="bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb",
    dataset_table_name="eval_parcels",
    geometry_type="Polygon",
    dataset_title="Tax Parcels",
    feature_count=18340,
    column_info=[
        {"name": "gid", "type": "integer"},
        {"name": "parcel_id", "type": "text"},
        {"name": "zoning", "type": "text"},
        {"name": "area_sqm", "type": "double precision"},
    ],
    sample_values={"zoning": ["R6", "C4-3", "M1-1"]},
)

_SCHOOLS_LAYER = ChatMapLayer(
    id="33333333-3333-4333-8333-333333333333",
    name="Schools",
    dataset_id="cccccccc-3333-4333-8333-cccccccccccc",
    dataset_table_name="eval_schools",
    geometry_type="Point",
    dataset_title="Public Schools",
    feature_count=1621,
    column_info=[
        {"name": "gid", "type": "integer"},
        {"name": "name", "type": "text"},
        {"name": "grade_span", "type": "text"},
    ],
)

_MAP_LAYERS = [_STATIONS_LAYER, _PARCELS_LAYER, _SCHOOLS_LAYER]

# The basemap string reaches the prompt's colour-guidance line. Pin it so the
# prompt is byte-identical run to run.
_BASEMAP = "light"


@dataclass(frozen=True)
class ToolChoiceCase:
    """One routing expectation.

    ``expects`` names the tool that should be emitted, alone. ``forbids`` names
    tools that must not appear at all. A case sets one or the other: the
    routing pairs name a tool, the surface cases check an absence because the
    model is legitimately free to answer those in prose instead.

    ``stable`` is the promotion flag. False means observe and report; True
    means fail the run on the wrong tool. Flipping it is the entire promotion
    procedure, see the block comment below.
    """

    name: str
    message: str
    expects: str | None = None
    forbids: frozenset[str] = frozenset()
    can_edit: bool = True
    has_map: bool = True
    stable: bool = False
    note: str = ""


# ---------------------------------------------------------------------------
# THE CASE TABLE. Validated live and promoted to asserting in #1135.
#
# Evidence: three consecutive scheduled nightlies, tabulated in
# https://github.com/geolens-io/geolens/issues/1135 (runs 30807039095,
# 30897410217, 30994238038 — 2026-08-03/04/05, 16 passed each). The four
# `expects` rows emitted the identical correct tool in all three runs. The two
# `forbids` rows held their forbidden-tool absence in all three runs; that
# absence is the only thing their assertion checks, so the observed variance
# on readonly_surface_no_edit_tool (query_data on 08-03, prose on 08-04/05 —
# both legitimate per its note) cannot fail a run.
#
# A NEW row must ship stable=False and earn stable=True via the procedure
# below. Do not add a row born asserting: an assertion nobody has executed
# against a live provider can redden the nightly for a reason nobody has seen.
#
# PROMOTION PROCEDURE for future rows:
#   1. Run the file live THREE times:
#        cd backend && set -a && source ../.env.test && set +a && \
#          RUN_AI_EVALS=1 uv run pytest tests/evals/test_tool_choice_evals.py -v
#      Each case emits a warning carrying the tool it actually routed to, so
#      the warnings summary at the end of the run IS the report. Add -s to see
#      the same line inline as each case finishes.
#   2. Record the emitted tool per case per run.
#   3. Same correct tool all three times, set stable=True on that row. One
#      line, no test-code changes.
#   4. Varied across runs, leave stable=False and replace `note` with what you
#      saw. A flaky case must never assert.
#   5. Consistently WRONG is a live routing bug, not a bad case. Fix the
#      prompt, then promote.
#
# Until step 3 happens for a row, its `note` is a prior about why the routing
# ought to hold, not evidence that it does.
# ---------------------------------------------------------------------------

_CASES = (
    # -- Pair 1 (#549): the QUESTION / CHANGE split on the same subject. Both
    # directions, because a prompt edit that fixes one commonly breaks the
    # other. That is how #549 happened.
    ToolChoiceCase(
        name="show_ada_stations",
        message="Show the ADA accessible stations served by the A line",
        expects="query_data",
        stable=True,  # fix(#1135): query_data in all three validation runs
        note=(
            "The #549 regression itself: this landed on set_filter, leaving a "
            "persistent filter on the layer instead of answering. The prompt's "
            "worked QUESTION example is the same sentence plus one word "
            '("Show me the ..."), so the case also checks that the rule '
            "generalises one word past the example instead of being memorised "
            "from it."
        ),
    ),
    ToolChoiceCase(
        name="filter_ada_stations",
        message="Filter to ADA accessible stations on the A line",
        expects="set_filter",
        stable=True,  # fix(#1135): set_filter in all three validation runs
        note=(
            "The over-correction guard: a prompt edit pushing 'show' towards "
            "query_data must not drag 'filter to' along with it. The prompt "
            "carries this sentence verbatim as its worked CHANGE example."
        ),
    ),
    # -- Pair 2: run_analysis vs query_data, settled in prompt prose only and
    # with the same unprotected shape as pair 1.
    ToolChoiceCase(
        name="centroid_of_parcels",
        message="Show the centre point of each parcel",
        expects="run_analysis",
        stable=True,  # fix(#1135): run_analysis in all three validation runs
        note=(
            "'Show' is a QUESTION verb, so this only routes correctly if the "
            "TRANSFORM rule outranks the verb, the exact ordering the prompt "
            "states and the exact thing an edit to that section disturbs. The "
            "prompt cites 'the centre point of each parcel' verbatim."
        ),
    ),
    ToolChoiceCase(
        name="count_near_schools",
        message="How many parcels are within 500 meters of a school?",
        expects="query_data",
        stable=True,  # fix(#1135): query_data in all three validation runs
        note=(
            "The adversarial direction of pair 2: reuses the buffer phrasing "
            "the prompt cites for run_analysis ('within 500 m of the schools') "
            "but asks for a COUNT, which no buffer/centroid/clip preview can "
            "produce. Ground truth is two prompt rules read against each other "
            "rather than a worked example, which is the shape most likely to "
            "vary between runs."
        ),
    ),
    # -- Surface variations. Each constructs its own restricted surface rather
    # than borrowing the map-chat one, so the absence checked is real.
    ToolChoiceCase(
        name="readonly_surface_no_edit_tool",
        message="Filter to ADA accessible stations on the A line",
        forbids=frozenset(_EDIT_TOOLS),
        can_edit=False,
        stable=True,  # fix(#1135): no edit tool emitted in any validation run
        note=(
            "can_edit=False builds BOTH restricted inputs from production "
            "code, CHAT_TOOLS_READONLY and the prompt's read-only directive, "
            "then sends the request that routes to set_filter on the editable "
            "surface. Native tool-calling cannot name an unadvertised tool, "
            "but the OpenAI-compatible path also parses XML tool calls out of "
            "plain text (parse_xml_tool_calls), which can, and that is why "
            "chat_service keeps a name check at execution and collection. The "
            "model stays free to answer with query_data or with prose, and the "
            "#1135 validation runs saw both (query_data on 08-03, prose on "
            "08-04/05); only an emitted edit tool can fail this row."
        ),
    ),
    ToolChoiceCase(
        name="mapless_surface_no_run_analysis",
        message="Show the centre point of each parcel",
        forbids=frozenset({"run_analysis"}),
        can_edit=False,
        has_map=False,
        stable=True,  # fix(#1135): query_data (never run_analysis) in all three runs
        note=(
            "run_analysis's whole output is a map overlay, so offering it on "
            "dataset-scoped chat would let the model promise a preview the "
            "surface cannot render. Sends the message that routes to "
            "run_analysis on a map surface, under the map-less tool set and "
            "the dataset-chat prompt."
        ),
    ),
)


async def _route(session, case: ToolChoiceCase) -> tuple[list[str], set[str]]:
    """Ask the live provider to route ``case`` and return (emitted, offered).

    Drives the production tool set and prompt builder, executes nothing, and
    costs exactly one provider round-trip:

    * ``max_rounds=1``. A tool-calling turn appends its tool results and
      ``continue``s, so the loop falls out of ``range(1)`` and raises
      ``ToolLoopExhaustedError`` before it can bill a second round. That
      exception IS the tool-use outcome here, not a failure.
    * A plain text answer returns normally from ``complete()`` with nothing
      recorded, which is a legitimate outcome for the surface cases.

    Returns every tool name in the first assistant turn, in order, not just the
    first, so an "and also emitted an editing tool" regression is visible.
    Provider errors (a missing key above all) propagate: those are not routing
    verdicts and must stay loud.
    """
    tools = select_chat_tools(case.can_edit, case.has_map)
    if case.has_map:
        system_prompt = build_chat_system_prompt(
            _MAP_LAYERS, basemap_style=_BASEMAP, can_edit=case.can_edit
        )
    else:
        # The map-less surface is dataset-scoped chat, which overrides the
        # map-framed prompt entirely (router.py:716 -> system_prompt_override).
        system_prompt = build_dataset_chat_system_prompt(_PARCELS_LAYER)

    provider, model, runtime_config = await resolve_provider(session)
    provider_ext = get_ai_provider(provider)

    emitted: list[str] = []

    async def record_only(tool_name: str, tool_input: dict) -> dict:
        emitted.append(tool_name)
        return {"error": "tool-choice eval: tool not executed"}

    try:
        await provider_ext.complete(
            model=model,
            system_prompt=system_prompt,
            user_message=case.message,
            tools=tools,
            tool_executor=record_only,
            base_url=runtime_config.get("base_url"),
            temperature=0.0,
            max_rounds=1,
        )
    except ToolLoopExhaustedError:
        pass

    return emitted, {t["name"] for t in tools}


def _misroute(
    case: ToolChoiceCase, emitted: list[str], offered: set[str]
) -> str | None:
    """Describe how ``emitted`` violates ``case``, or None if it is correct.

    ``expects`` demands the tool ALONE, deliberately. The prompt does invite a
    second tool for compound requests ("both a question and a map change"), but
    none of these messages are compound, and emitting query_data *plus*
    set_filter for a question still leaves the persistent filter #549 was
    about. A case that genuinely needs a compound expectation should grow a set
    field rather than loosen this to a membership test.
    """
    if case.expects is not None and emitted != [case.expects]:
        return f"expected exactly [{case.expects!r}]"
    forbidden = case.forbids & set(emitted)
    if forbidden:
        return f"emitted forbidden tool(s) {sorted(forbidden)}"
    outside = set(emitted) - offered
    if outside:
        return f"emitted {sorted(outside)} outside the offered set {sorted(offered)}"
    return None


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c.name)
async def test_tool_choice(client, test_db_session, case: ToolChoiceCase):
    """Route one case, then assert it (stable) or report it (not yet).

    The only hard assertion that runs today is a table-consistency check: a
    case expecting a tool its own surface does not offer is a bug in the table
    rather than a model outcome, and it is deterministic, with no live
    behaviour involved.
    """
    emitted, offered = await _route(test_db_session, case)

    if case.expects is not None:
        assert case.expects in offered, (
            f"[{case.name}] case table bug: {case.expects!r} is not offered on "
            f"this surface ({sorted(offered)}), so the case can never pass"
        )

    problem = _misroute(case, emitted, offered)
    observed = f"[{case.name}] {case.message!r} -> {emitted or 'no tool (text answer)'}"
    print(observed + (f"  MISROUTED: {problem}" if problem else "  ok"))

    if case.stable:
        assert problem is None, f"{observed}; {problem}"
    else:
        # Reported, not asserted: this row has never been validated live. The
        # warnings summary of the run is the report the promotion procedure
        # above _CASES asks you to record.
        warnings.warn(
            f"{observed}; {problem or 'matches expectation'} "
            "[reported only, never validated live; see the promotion "
            "procedure above _CASES]",
            stacklevel=2,
        )
