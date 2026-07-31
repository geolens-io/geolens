"""fix(#549): exactly one site classifies user verbs for chat tool selection.

"Show the ADA accessible stations served by the A line" applied a persistent
layer filter while "Run a query selecting ..." returned a query result, so a
user could not predict which of two very different outcomes natural phrasing
would give them.

The guidance that should have caught it already existed in the system prompt,
but neither of its two buckets contained "show" — and the one place "show" WAS
classified pointed the other way, in ``run_analysis``'s tool description, which
cited "show the centre point of each parcel" as a transform request. So the
model read verb classes from two competing sites while ``set_filter``, the tool
that actually fired, carried no routing guidance at all.

These tests pin the resolution: the system prompt owns verb classification,
tool descriptions stay behavioural, and a later edit to one cannot silently
reverse the routing by contradicting the other.
"""

from __future__ import annotations

import pytest

from app.processing.ai.chat_service import build_chat_system_prompt
from app.processing.ai.schemas import ChatMapLayer
from app.processing.ai.tools import CHAT_TOOLS_ANTHROPIC


def _prompt() -> str:
    return build_chat_system_prompt(
        [
            ChatMapLayer(
                id="layer-1",
                name="Stations",
                dataset_id="ds-1",
                dataset_table_name="data.ds_stations",
                geometry_type="Point",
                visible=True,
            )
        ]
    )


def _description(name: str) -> str:
    for tool in CHAT_TOOLS_ANTHROPIC:
        if tool["name"] == name:
            return tool["description"]
    raise AssertionError(f"no tool named {name!r}")


# --- The prompt owns verb classification -----------------------------------


def test_prompt_declares_itself_the_owner():
    """A tool description that starts classifying phrasing again is the
    regression; the prompt says out loud that it decides."""
    prompt = _prompt()
    assert "Tool selection is decided HERE" in prompt


@pytest.mark.parametrize(
    "verb", ["show", "find", "list", "which", "what", "where", "how many"]
)
def test_prompt_classifies_the_question_verbs(verb):
    question_block = _prompt().split("QUESTION verbs")[1].split("CHANGE verbs")[0]
    assert verb in question_block


@pytest.mark.parametrize(
    "verb", ["filter", "style", "color", "label", "hide", "change", "set", "make"]
)
def test_prompt_classifies_the_change_verbs(verb):
    change_block = _prompt().split("CHANGE verbs")[1].split('"show" is a QUESTION')[0]
    assert verb in change_block


def test_prompt_reads_the_object_before_the_verb():
    """fix(#549 codex r1): verb alone is not enough. "find datasets about
    flood zones" is a QUESTION verb whose object is the CATALOG, and
    query_data can only reach layers already on the map, so routing on the
    verb turned a valid catalog lookup into a failed SQL question."""
    prompt = _prompt()
    assert "Read the OBJECT of the request first" in prompt
    assert "The object is the CATALOG" in prompt
    assert "find datasets about flood zones" in prompt
    assert "search_datasets" in prompt


def test_prompt_separates_label_visibility_from_layer_visibility():
    """fix(#549 codex r2): toggle_visibility's schema only shows or hides the
    whole layer, so routing "hide the labels" there removes the features too.
    Labels are turned off with set_label(column: null)."""
    prompt = _prompt()
    assert "The object is a layer's LABELS" in prompt
    assert "column null to turn" in prompt
    assert "would hide the layer's features too" in prompt


def test_prompt_keeps_layer_narrowing_on_the_visibility_tool():
    """fix(#549 codex r1): "show only @Parks" among several layers means hide
    the others. set_filter cannot do that — it only filters features inside
    one layer — so the two narrowing cases have to be told apart."""
    prompt = _prompt()
    assert '"show only @Parks" when @Parks is a LAYER' in prompt
    assert "cannot hide a sibling layer" in prompt
    assert "NARROWING to a feature PREDICATE" in prompt


def test_prompt_carries_both_acceptance_phrasings():
    """The reported pair, so the split is anchored to the observed misroute
    rather than to an abstract rule."""
    prompt = _prompt()
    assert "Show me the ADA accessible stations served by the A line" in prompt
    assert "Filter to ADA accessible stations on the A line" in prompt


def test_prompt_settles_bare_show():
    """Bare "show" is the whole defect: it read as plausible under both
    buckets and was listed in neither."""
    prompt = _prompt()
    assert '"show" is a QUESTION verb by default' in prompt


@pytest.mark.parametrize(
    ("shape", "phrase"),
    [
        # fix(#549 codex r1): "show the layer" is the phrase the builder
        # contract already uses for toggle_visibility
        # (frontend ChatPanel.test.tsx). Routing it to query_data would query a
        # hidden layer instead of making it visible.
        ("visibility", '"show the layer"'),
        ("feature narrowing", '"show only the accessible ones"'),
        # fix(#549 codex r1): with a filter already applied, "show all features
        # again" asks to CLEAR it. Answering it as a question returns a
        # temporary result and leaves the persistent filter in place.
        ("broadening", '"show all"'),
    ],
)
def test_prompt_carves_the_map_shaped_uses_of_show_back_out(shape, phrase):
    prompt = _prompt()
    assert phrase in prompt, shape


def test_prompt_names_the_tool_for_each_show_exception():
    prompt = _prompt()
    assert "toggle_visibility" in prompt
    assert "null expression to" in prompt


def test_prompt_keeps_transform_outranking_the_verb_lists():
    """Asking to "show the centre point of each parcel" still has to reach
    run_analysis, and it is a QUESTION verb over a geometry operation."""
    prompt = _prompt()
    assert "names a geometry OPERATION is a TRANSFORM" in prompt
    assert "run_analysis, NOT query_data" in prompt


# --- Tool descriptions stay behavioural ------------------------------------


# The two tools on the QUESTION/TRANSFORM side of the split. A description
# that names one of these is choosing between the question path and the
# map-edit path — the choice the system prompt owns.
#
# Deliberately narrower than "no description may name any sibling". Two
# existing cross-references are not verb classification and stay: set_style
# points at set_data_driven_style (a CAPABILITY difference — both are CHANGE
# tools), and add_layer points at search_datasets (a SEQUENCING step — you
# need a dataset_id first). Neither says anything about which user phrasing
# wins, which is the thing that was being decided in two places.
_ROUTING_SIDE_TOOLS = ("query_data", "run_analysis")

# fix(#549 codex r1): naming a sibling is not the only way to classify
# phrasing. query_data's own description said "use this when the user asks a
# question about their data ... do NOT use this for map styling", which
# competes with the prompt's verb classes from a second site while naming no
# tool at all. These are the prose shapes that do it.
#
# Heuristics, and they are worth being honest about: no assertion over free
# text can prove a description says nothing about routing. What they cover is
# the shape the incident actually took — a description telling the model which
# KIND OF REQUEST belongs to it. A reviewer is still the backstop.
_ROUTING_PROSE_MARKERS = (
    "when the user asks",
    "use the other tools",
    "for requests that",
    "instead for",
    "do not use this for",
)


def test_no_tool_description_routes_across_the_split():
    """The single-owner rule, enforced structurally."""
    offenders = {
        tool["name"]: sorted(
            other
            for other in _ROUTING_SIDE_TOOLS
            if other != tool["name"] and other in tool["description"]
        )
        for tool in CHAT_TOOLS_ANTHROPIC
    }
    offenders = {name: hits for name, hits in offenders.items() if hits}
    assert not offenders, (
        "tool descriptions must not decide which phrasing reaches the question "
        f"path; move it to the system prompt's verb classes: {offenders}"
    )


def test_no_tool_description_classifies_requests_for_itself():
    """A description does not have to name a sibling to compete with the rule.

    Catches the self-classification form: telling the model which kind of
    request belongs to this tool is the same claim, made from the same second
    site.
    """
    offenders = {
        tool["name"]: sorted(
            marker
            for marker in _ROUTING_PROSE_MARKERS
            if marker in tool["description"].lower()
        )
        for tool in CHAT_TOOLS_ANTHROPIC
    }
    offenders = {name: hits for name, hits in offenders.items() if hits}
    assert not offenders, (
        "tool descriptions must describe behaviour, not classify user "
        f"phrasing; move it to the system prompt's verb classes: {offenders}"
    )


def test_run_analysis_no_longer_teaches_show_as_a_transform_verb():
    description = _description("run_analysis")
    assert "show the centre point" not in description
    # It still has to say what the operations do.
    assert "buffer" in description
    assert "centroid" in description


def test_set_filter_points_at_the_prompt():
    """The tool that actually fired on the misroute carried no guidance at all;
    it now cross-references the rule instead of restating it."""
    description = _description("set_filter")
    assert "map-edit path" in description
    assert "system prompt's verb classes" in description
    # A pointer, not a second copy: no verb list of its own.
    assert "QUESTION" not in description
