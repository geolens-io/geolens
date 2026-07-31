"""fix(#935): the NL->SQL prompt and analysis_sql must agree on the buffer shape.

The prompt used to hand-write ``ST_Buffer(geom::geography, N)::geometry`` in
four places, so it inherited neither the antimeridian split (#883) nor the
per-projection pass (#891/#902) applied to the real analysis path — twice.
The prompt now embeds ``render_geodesic_buffer``'s own output at import time,
which removes the drift class by construction; these tests pin the wiring so
a rewrite of the prompt cannot quietly reintroduce a hand-written copy.
"""

import pytest

from app.platform.analysis_sql import render_geodesic_buffer
from app.processing.ai.sql_generator import SQL_SYSTEM_PROMPT


def _expected_template() -> str:
    return render_geodesic_buffer("<GEOM>", 99999).replace("99999", "<METERS>")


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


def test_prompt_embeds_the_generated_buffer_template():
    """The canonical <GEOM>/<METERS> template in the Metric Buffers section is
    render_geodesic_buffer's output, freshly rendered — if analysis_sql
    changes shape and the prompt module stops re-rendering it, this fails."""
    assert _expected_template() in SQL_SYSTEM_PROMPT


def test_prompt_embeds_a_generated_worked_example():
    """The Buffer + intersect example is a real rendered expression, not a
    hand-typed restatement."""
    denver = render_geodesic_buffer(
        "(SELECT geom_4326 FROM data.us_state_capitals WHERE name = 'Denver')",
        50000,
    )
    assert denver in SQL_SYSTEM_PROMPT


def test_every_buffer_in_the_prompt_is_generated_or_marked_wrong():
    """No ST_Buffer in the prompt teaches a form render_geodesic_buffer would
    not produce. Every occurrence must come from a rendered embed or sit on an
    explicit '-- WRONG' line; a fifth hand-written copy fails here."""
    embeds = [
        _expected_template(),
        render_geodesic_buffer(
            "(SELECT geom_4326 FROM data.us_state_capitals WHERE name = 'Denver')",
            50000,
        ),
    ]
    remainder = SQL_SYSTEM_PROMPT
    for embed in embeds:
        assert embed in remainder
        remainder = remainder.replace(embed, "")
    for line in remainder.splitlines():
        if "ST_Buffer(" not in line:
            continue
        assert _is_negative_teaching(line), (
            f"hand-written ST_Buffer teaching leaked into the prompt: {line!r}"
        )


def test_rendered_buffer_expression_is_refused_until_1001_lands():
    """fix(#1001): INVERTED, deliberately, and it must go back to asserting
    admission when #1001 lands.

    #935 codex r1 admitted the buffer's functions and bounded them with cost
    guards. #990 then rebuilt the renderer, and those guards — written against
    the older shape — rejected the very expression the prompt mandates. Three
    attempts to recalibrate them each drew a real P1 (see #1002), because
    proving a target's units and admitting the canonical buffer are
    contradictory under any target-inspection scheme: the buffer segmentizes
    an alias, `_pb_d0.c0`, several derived levels from its input.

    So the allowlist entries and the guards both came out. That leaves the
    prompt still teaching the SAFE banded expression, which the sandbox now
    refuses outright. The refusal is the point: the alternative was reverting
    the prompt too, and `st_buffer` is allowlisted independently, so the model
    would have emitted the bare `ST_Buffer(geom::geography, N)::geometry` form
    and it would have EXECUTED — returning the world-spanning polygon across
    ±180° that #883/#900/#990 fixed. A refused buffer question beats a
    silently wrong overlay and bbox.
    """
    from app.platform.sandbox.schemas import SandboxError
    from app.platform.sandbox.validator import validate_sql

    denver = render_geodesic_buffer(
        "(SELECT geom_4326 FROM data.us_state_capitals WHERE name = 'Denver')",
        50000,
    )
    # The prompt's worked example, as the model would emit it.
    with pytest.raises(SandboxError):
        validate_sql(
            "SELECT p.name AS park_name\n"
            "FROM data.national_parks p\n"
            f"WHERE ST_Intersects(p.geom_4326, {denver})\n"
            "LIMIT 100"
        )
    # A direct buffer-geometry request, the chat_geojson-shaped form.
    buffered = render_geodesic_buffer("s.geom_4326", 10000)
    with pytest.raises(SandboxError):
        validate_sql(
            f"SELECT s.name, ST_AsGeoJSON({buffered}) AS geometry\n"
            "FROM data.stations s\nLIMIT 100"
        )


def test_function_reference_line_declares_degrees():
    """sql_generator.py:194's old form taught a unitless buffer; the reference
    line must state the planar/degrees semantics explicitly so it stops
    contradicting the Metric Buffers section."""
    assert "DEGREES on geom_4326" in SQL_SYSTEM_PROMPT


def test_no_bare_geography_buffer_taught_positively():
    """The three original cheat-sheet/example sites are gone: outside the
    rendered embeds, the bare geography-cast buffer appears only as a negative
    (WRONG) example."""
    remainder = SQL_SYSTEM_PROMPT
    for embed in (
        _expected_template(),
        render_geodesic_buffer(
            "(SELECT geom_4326 FROM data.us_state_capitals WHERE name = 'Denver')",
            50000,
        ),
    ):
        remainder = remainder.replace(embed, "")
    for line in remainder.splitlines():
        if "::geography," in line and "ST_Buffer(" in line:
            assert _is_negative_teaching(line), line
