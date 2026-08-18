"""fix(#935) / fix(#1589): what the NL->SQL prompt teaches about metric buffers.

#935: the prompt used to hand-write ``ST_Buffer(geom::geography, N)::geometry``
in four places, so it inherited neither the antimeridian split (#883) nor the
per-projection pass (#891/#902) applied to the real analysis path — twice. The
fix embedded ``render_geodesic_buffer``'s own output at import time, which
removed the drift class by construction.

#1589: it also asked the model to reproduce 3 088 characters exactly, and the
light model could not. Six of nine nightly eval runs failed on a dropped
parenthesis or a paraphrase back to the bare geography-cast form. The prompt
now teaches a short marker, ``geolens_buffer(<geom>, <metres>)``, and
``app.processing.ai.buffer_marker`` renders the real expression server-side.

So the property has moved rather than gone away. The prompt must no longer
carry the expression at all, and the expansion of what it DOES teach must be
exactly what the sandbox admits — which is still ``render_geodesic_buffer``'s
output, still compared by re-render in ``_matches_canonical_buffer``.
"""

import re

from app.platform.analysis_sql import MAX_BUFFER_METERS, render_geodesic_buffer
from app.platform.sandbox.validator import validate_sql
from app.processing.ai.buffer_marker import expand_buffer_markers
from app.processing.ai.sql_generator import SQL_SYSTEM_PROMPT


def _is_negative_teaching(line: str) -> bool:
    """A line may name the bare buffer form only while calling it wrong."""
    stripped = line.strip()
    return (
        stripped.startswith("-- WRONG:")
        # The function reference declares the planar/degrees semantics.
        or stripped.startswith("ST_Buffer(geom, radius)")
        # The Metric Buffers prose names the bare form to warn against it.
        or "silently degrades" in line
    )


def test_prompt_teaches_the_marker():
    """The one thing the model is asked to write for a metric buffer."""
    assert "geolens_buffer(" in SQL_SYSTEM_PROMPT
    assert "## Metric Buffers" in SQL_SYSTEM_PROMPT


def test_prompt_no_longer_carries_the_rendered_expression():
    """fix(#1589): the 3 KB embed is gone, and nothing may quietly restore it.

    Checked by the scaffold's own fingerprints rather than by length: the
    renderer's internal alias and its dissolve are in every render it produces
    and in nothing a person would write by hand, so either one appearing in the
    prompt means the expression came back.
    """
    assert render_geodesic_buffer("<GEOM>", 99999) not in SQL_SYSTEM_PROMPT
    assert "ST_UnaryUnion" not in SQL_SYSTEM_PROMPT
    assert "_pb" not in SQL_SYSTEM_PROMPT
    assert "ST_DumpSegments" not in SQL_SYSTEM_PROMPT


def test_every_buffer_in_the_prompt_is_marked_wrong():
    """No ST_Buffer in the prompt teaches a form the model should emit. Every
    occurrence must sit on an explicit '-- WRONG' line or in the prose that
    warns against it."""
    for line in SQL_SYSTEM_PROMPT.splitlines():
        if "ST_Buffer(" not in line:
            continue
        assert _is_negative_teaching(line), (
            f"hand-written ST_Buffer teaching leaked into the prompt: {line!r}"
        )


def test_no_bare_geography_buffer_taught_positively():
    """The bare geography-cast buffer appears only as a negative example."""
    for line in SQL_SYSTEM_PROMPT.splitlines():
        if "::geography," in line and "ST_Buffer(" in line:
            assert _is_negative_teaching(line), line


def test_function_reference_line_declares_degrees():
    """sql_generator.py's ST_Buffer reference line must state the
    planar/degrees semantics explicitly so it stops contradicting the Metric
    Buffers section."""
    assert "DEGREES on geom_4326" in SQL_SYSTEM_PROMPT


def test_prompt_states_the_bounded_input_rule():
    """fix(#1001): the sandbox admits the rendered buffer only around a stored
    geometry, because the expression's cost scales with its input's extent.

    The model has to be told, or it emits a shape that is silently refused —
    the same prompt-vs-validator disagreement this whole chain is about. The
    marker changed who writes the expression, not which inputs it accepts.
    """
    assert "must be the managed geom_4326 column" in SQL_SYSTEM_PROMPT
    # fix(#1001 codex r4): the scaffold interposes its own scope, so a bare
    # top-level column is undecidable and refused. The prompt has to say so.
    assert "it must be QUALIFIED" in SQL_SYSTEM_PROMPT
    assert "s.geom_4326" in SQL_SYSTEM_PROMPT
    assert "A reprojection, a nested buffer, a constructed geometry" in (
        SQL_SYSTEM_PROMPT
    )
    # fix(#1001 codex r3): a dataset's original projected geom column is the
    # non-obvious one, so the prompt has to name it.
    assert "original geom column in another CRS" in SQL_SYSTEM_PROMPT


def test_prompt_states_the_distance_rule():
    """fix(#1589): the expander takes a plain number and caps it, so a model
    writing `500 * 2` or `200000` gets a refusal. Say so up front."""
    assert f"{MAX_BUFFER_METERS:.0f}" in SQL_SYSTEM_PROMPT


def test_the_worked_example_expands_and_the_sandbox_admits_it():
    """The prompt's Buffer + intersect example, taken from the prompt itself
    and run through the real expansion and the real validator.

    Pinning the example by its text alone would pass for an example that no
    longer works; this fails if the marker syntax, the expander, or the
    sandbox's canonical-buffer match drift apart.
    """
    match = re.search(
        r"^SELECT p\.name AS park_name$.*?;$",
        SQL_SYSTEM_PROMPT,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "the Buffer + intersect example is no longer in the prompt"
    example = match.group(0).rstrip(";")
    assert "geolens_buffer(" in example

    expanded = expand_buffer_markers(example)
    assert "geolens_buffer" not in expanded
    result = validate_sql(expanded)
    assert result.tables == {
        ("data", "national_parks"),
        ("data", "us_state_capitals"),
    }


def test_rendered_buffer_expression_validates():
    """fix(#1001): the sandbox has to admit what the expander produces.

    This test spent one release inverted. #935 codex r1 admitted the buffer's
    functions and bounded them with per-call cost guards; #990 then rebuilt the
    renderer and those guards, written against the older shape, rejected the
    very expression the prompt mandates. Three attempts to recalibrate them
    each drew a real P1 (#1002), because proving a call's argument is safe and
    admitting the canonical buffer are contradictory under any
    argument-inspection scheme — the buffer segmentizes an alias, `_pb_d0.c0`,
    several derived levels from its input. #1003 took the guards and the
    allowlist entries back out, which left the prompt teaching an expression
    the sandbox refused, and this test asserting that refusal.

    #1001 admits it a different way: nothing is allowlisted per call, and a
    subtree is exempted only when it is exactly what the renderer emits around
    its own input. fix(#1589) moved the rendering from the model to the server
    and left that rule untouched, which is why this still reads the same.
    """
    denver = render_geodesic_buffer(
        "(SELECT geom_4326 FROM data.us_state_capitals WHERE name = 'Denver')",
        50000,
    )
    result = validate_sql(
        "SELECT p.name AS park_name\n"
        "FROM data.national_parks p\n"
        f"WHERE ST_Intersects(p.geom_4326, {denver})\n"
        "LIMIT 100"
    )
    # The buffer's scaffold contributes no table of its own; the two tables are
    # the ones the model actually asked for.
    assert result.tables == {
        ("data", "national_parks"),
        ("data", "us_state_capitals"),
    }

    # A direct buffer-geometry request, the chat_geojson-shaped form.
    buffered = render_geodesic_buffer("s.geom_4326", 10000)
    result = validate_sql(
        f"SELECT s.name, ST_AsGeoJSON({buffered}) AS geometry\n"
        "FROM data.stations s\nLIMIT 100"
    )
    assert result.tables == {("data", "stations")}
