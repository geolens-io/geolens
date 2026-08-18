"""fix(#1589): the NL->SQL prompt asks for a marker; the server expands it.

Before this, the prompt embedded ``render_geodesic_buffer``'s rendered output
twice — a 3 017-character template and a 3 073-character worked example, 6 090
of the prompt's 16 786 characters — and told the model to reproduce it
character for character. The light model managed that about half the time. The
nightly buffer evals
failed on six of nine runs between 08-12 and 08-18, every failure a sandbox
refusal of a dropped parenthesis or a paraphrase back to the bare
``ST_Buffer(::geography)`` form, never a wrong answer that ran.

So the model now writes ``geolens_buffer(<geom>, <metres>)`` and
``app.processing.ai.buffer_marker`` substitutes the canonical render before
anything sees the SQL. The shape can no longer be wrong, because the model no
longer writes it.

What these tests hold down:

- the scanner reads the arguments the way PostgreSQL would — balanced parens,
  string literals, comments — and never by regex;
- a malformed marker fails as ``invalid_query`` rather than being passed
  through to produce a confusing sandbox error later;
- expansion happens on MODEL output only. The raw ``POST /api/query/``
  endpoint takes user-written SQL and must keep refusing ``geolens_buffer``
  as the unknown function it is;
- the geometry argument stays fully under the sandbox's authority. The
  expander decides syntax, never policy — #1002 is the record of what
  happens when two layers both try to decide whether a buffer's argument is
  safe.
"""

import pytest
import sqlglot

from app.platform.analysis_sql import MAX_BUFFER_METERS, render_geodesic_buffer
from app.platform.sandbox import SandboxError
from app.platform.sandbox.validator import validate_sql
from app.processing.ai.buffer_marker import (
    MAX_BUFFER_MARKERS,
    expand_buffer_markers,
)
from app.processing.ai.schemas import ChatMapLayer


def _wrap(expr: str, table: str = "data.stations s") -> str:
    return f"SELECT ST_AsGeoJSON({expr}) AS geometry FROM {table} LIMIT 100"


# ---------------------------------------------------------------------------
# The happy path: what the model is now asked to write
# ---------------------------------------------------------------------------


def test_a_simple_marker_becomes_the_canonical_render():
    sql = _wrap("geolens_buffer(s.geom_4326, 500)")
    assert expand_buffer_markers(sql) == _wrap(
        render_geodesic_buffer("s.geom_4326", 500.0)
    )


def test_the_prompts_worked_example_expands_and_the_sandbox_admits_it():
    """The Denver example the prompt teaches, end to end.

    This is the counterfactual for every refusal test below: the machinery
    that rejects a hostile argument has to let the taught shape through, or
    the rejections prove nothing.
    """
    denver = "(SELECT geom_4326 FROM data.us_state_capitals WHERE name = 'Denver')"
    expanded = expand_buffer_markers(
        "SELECT p.name AS park_name\n"
        "FROM data.national_parks p\n"
        f"WHERE ST_Intersects(p.geom_4326, geolens_buffer({denver}, 50000))\n"
        "LIMIT 100"
    )
    assert "geolens_buffer" not in expanded
    result = validate_sql(expanded)
    assert result.tables == {
        ("data", "national_parks"),
        ("data", "us_state_capitals"),
    }


def test_a_nested_call_in_the_geometry_argument_survives_intact():
    geom = "ST_Transform(ST_SetSRID(ST_MakePoint(-105.0, 39.7), 4326), 4326)"
    expanded = expand_buffer_markers(_wrap(f"geolens_buffer({geom}, 1000)"))
    assert expanded == _wrap(render_geodesic_buffer(geom, 1000.0))


def test_a_string_literal_holding_parens_and_commas_does_not_split_the_arguments():
    """The argument split cannot be a regex: this literal contains both the
    separator and the terminator the scanner is looking for."""
    geom = "(SELECT geom_4326 FROM data.parks WHERE name = 'Elm (North), Ward 2')"
    expanded = expand_buffer_markers(_wrap(f"geolens_buffer({geom}, 250)"))
    assert expanded == _wrap(render_geodesic_buffer(geom, 250.0))


def test_a_doubled_quote_inside_a_literal_does_not_end_it():
    geom = "(SELECT geom_4326 FROM data.parks WHERE name = 'O''Hare, gate (3)')"
    expanded = expand_buffer_markers(_wrap(f"geolens_buffer({geom}, 250)"))
    assert expanded == _wrap(render_geodesic_buffer(geom, 250.0))


def test_every_marker_in_a_statement_is_expanded():
    sql = (
        "SELECT ST_Intersects("
        "geolens_buffer(a.geom_4326, 100), geolens_buffer(b.geom_4326, 200))\n"
        "FROM data.a a, data.b b"
    )
    expanded = expand_buffer_markers(sql)
    assert render_geodesic_buffer("a.geom_4326", 100.0) in expanded
    assert render_geodesic_buffer("b.geom_4326", 200.0) in expanded
    assert "geolens_buffer" not in expanded


def test_the_marker_name_and_its_spacing_are_read_loosely():
    """Case and whitespace are the model's freedom; the call is not."""
    expanded = expand_buffer_markers(
        _wrap("GeoLens_Buffer\n  (  s.geom_4326 ,  500  )")
    )
    assert expanded == _wrap(render_geodesic_buffer("s.geom_4326", 500.0))


def test_sql_without_a_marker_is_returned_unchanged():
    sql = "SELECT s.name, ST_Area(s.geom_4326::geography) FROM data.stations s"
    assert expand_buffer_markers(sql) is sql


def test_an_error_comment_from_the_model_passes_through():
    sql = "-- ERROR: Cannot answer this question with the available data."
    assert expand_buffer_markers(sql) is sql


# ---------------------------------------------------------------------------
# Where the marker is NOT a call
# ---------------------------------------------------------------------------


def test_a_marker_inside_a_string_literal_is_not_a_call():
    sql = "SELECT 'geolens_buffer(s.geom_4326, 500)' AS note FROM data.stations s"
    assert expand_buffer_markers(sql) is sql


def test_a_marker_inside_a_line_comment_is_not_a_call():
    sql = (
        "SELECT s.name FROM data.stations s\n"
        "-- geolens_buffer(s.geom_4326, 500) would go here"
    )
    assert expand_buffer_markers(sql) is sql


def test_a_marker_inside_a_block_comment_is_not_a_call():
    sql = "SELECT s.name /* geolens_buffer(s.geom_4326, 500 */ FROM data.stations s"
    assert expand_buffer_markers(sql) is sql


def test_a_longer_identifier_that_merely_starts_with_the_marker_is_not_a_call():
    sql = "SELECT geolens_buffer_x(s.geom_4326, 500) FROM data.stations s"
    assert expand_buffer_markers(sql) is sql


def test_a_qualified_name_ending_in_the_marker_is_not_a_call():
    """``public.geolens_buffer(...)`` names some other schema's function, and
    substituting our expression for it would answer a different question."""
    sql = "SELECT public.geolens_buffer(s.geom_4326, 500) FROM data.stations s"
    assert expand_buffer_markers(sql) is sql


def test_a_comment_between_the_name_and_its_parenthesis_still_reads_as_a_call():
    expanded = expand_buffer_markers(
        _wrap("geolens_buffer /* metric */ (s.geom_4326, 500)")
    )
    assert expanded == _wrap(render_geodesic_buffer("s.geom_4326", 500.0))


# ---------------------------------------------------------------------------
# Comments inside the call (fix(#1589) review r1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "geom",
    [
        pytest.param("s.geom_4326 /* the stop */", id="block-comment-after"),
        pytest.param("/* the stop */ s.geom_4326", id="block-comment-before"),
        pytest.param("s.geom_4326 -- the stop\n", id="line-comment"),
        pytest.param(
            "(SELECT geom_4326 /* managed */ FROM data.parks WHERE gid = 1)",
            id="comment-inside-a-subquery",
        ),
    ],
)
def test_a_comment_inside_the_call_does_not_ride_into_the_expression(geom):
    """The scanner skips comments to SPLIT the arguments; it must also drop
    them from the slice it hands to the renderer.

    Passing one through breaks the query in a way the model cannot see. A
    block comment perturbs the text ``_matches_canonical_buffer`` re-renders,
    so the exemption is refused and the scaffold's own functions are rejected.
    A line comment comments out the rest of the rendered expression. Both are
    the failure class this change exists to remove, so both have to survive
    validation now, not merely fail closed.
    """
    expanded = expand_buffer_markers(_wrap(f"geolens_buffer({geom}, 500)"))
    assert "/*" not in expanded and "--" not in expanded
    result = validate_sql(expanded)
    assert result.tables


def test_a_comment_that_looks_like_one_inside_a_literal_is_kept():
    """The counterfactual for the stripper: ``--`` and ``/*`` inside a string
    are data. Removing them would change which rows the query matches."""
    geom = "(SELECT geom_4326 FROM data.parks WHERE code = 'A--B/*C*/')"
    expanded = expand_buffer_markers(_wrap(f"geolens_buffer({geom}, 500)"))
    assert expanded == _wrap(render_geodesic_buffer(geom, 500.0))


# ---------------------------------------------------------------------------
# Malformed markers
# ---------------------------------------------------------------------------


def _refusal(sql: str) -> SandboxError:
    with pytest.raises(SandboxError) as excinfo:
        expand_buffer_markers(sql)
    assert excinfo.value.category == "invalid_query"
    return excinfo.value


@pytest.mark.parametrize(
    "call",
    [
        pytest.param("geolens_buffer(s.geom_4326)", id="one-argument"),
        pytest.param("geolens_buffer(s.geom_4326, 100, 8)", id="three-arguments"),
        pytest.param("geolens_buffer()", id="no-arguments"),
    ],
)
def test_wrong_arity_is_refused(call):
    _refusal(_wrap(call))


@pytest.mark.parametrize(
    "call",
    [
        pytest.param("geolens_buffer(, 100)", id="nothing"),
        pytest.param("geolens_buffer(   , 100)", id="whitespace"),
        pytest.param("geolens_buffer(/* gone */, 100)", id="only-a-comment"),
    ],
)
def test_an_empty_geometry_argument_is_refused(call):
    """Two arguments, so this is not an arity failure; the geometry slot is
    the one that is empty, and the message has to say so."""
    err = _refusal(_wrap(call))
    assert "needs a geometry expression" in str(err)


def test_an_unterminated_marker_is_refused():
    _refusal("SELECT ST_AsGeoJSON(geolens_buffer(s.geom_4326, 500 FROM data.stations s")


def test_an_unterminated_string_literal_in_the_argument_is_refused():
    _refusal("SELECT geolens_buffer((SELECT geom_4326 FROM data.t WHERE n = 'x), 500)")


@pytest.mark.parametrize(
    "distance",
    [
        pytest.param("", id="empty"),
        pytest.param("0", id="zero"),
        pytest.param("-100", id="negative"),
        pytest.param("1e400", id="overflows-to-inf"),
        pytest.param("'500'", id="quoted"),
        pytest.param("500 + 1", id="expression"),
        pytest.param("s.radius", id="column"),
        pytest.param("NaN", id="nan"),
        pytest.param("Infinity", id="infinity"),
        pytest.param("500::numeric", id="cast"),
        pytest.param("0x1F", id="hex"),
        pytest.param("1_000", id="underscore-separated"),
        pytest.param(f"{MAX_BUFFER_METERS + 1:g}", id="over-the-cap"),
    ],
)
def test_a_distance_that_is_not_a_plain_in_range_number_is_refused(distance):
    _refusal(_wrap(f"geolens_buffer(s.geom_4326, {distance})"))


@pytest.mark.parametrize(
    ("distance", "expected"),
    [
        ("1", 1.0),
        ("1500.5", 1500.5),
        ("1e4", 10000.0),
        ("1E4", 10000.0),
        (".5", 0.5),
        ("100000", MAX_BUFFER_METERS),
        ("100000.0", MAX_BUFFER_METERS),
    ],
)
def test_an_in_range_numeric_literal_is_accepted_however_it_is_spelled(
    distance, expected
):
    expanded = expand_buffer_markers(_wrap(f"geolens_buffer(s.geom_4326, {distance})"))
    assert expanded == _wrap(render_geodesic_buffer("s.geom_4326", expected))


def test_a_geometry_argument_that_is_not_one_expression_is_refused():
    """Syntax only. Whether the expression is an ACCEPTABLE geometry is the
    sandbox's call, and deliberately not re-decided here."""
    _refusal(_wrap("geolens_buffer(SELECT geom_4326 FROM data.t, 500)"))
    _refusal(_wrap("geolens_buffer(s.geom_4326 OFFSET 0, 500)"))


# ---------------------------------------------------------------------------
# Nesting and volume
# ---------------------------------------------------------------------------


def test_a_nested_marker_is_refused_rather_than_expanded_inside_out():
    """Decision, recorded here and in the module: reject.

    An inner buffer is not a stored geometry, so ``_is_bounded_geometry_source``
    in the validator refuses the outer one no matter what we render — the
    prompt says as much ("a nested buffer ... is refused"). Refusing here
    rather than rendering ~6 KB that cannot pass is the benefit.

    The message asserted below is DEVELOPER-facing, and that is the whole of
    its audience: ``_execute_chat_tool`` replaces every ``invalid_query``
    message with the generic ERROR_MESSAGES line, so the model and the user
    see that instead. What this pins is the reason reaching the log line in
    ``_fail`` and pytest, which is where a malformed marker gets diagnosed.
    """
    err = _refusal(_wrap("geolens_buffer(geolens_buffer(s.geom_4326, 10), 20)"))
    assert "nested" in str(err).lower()


def test_the_marker_count_is_capped():
    calls = ", ".join(
        f"geolens_buffer(s.geom_4326, {i + 1}00)" for i in range(MAX_BUFFER_MARKERS)
    )
    at_cap = f"SELECT {calls} FROM data.stations s"
    assert "geolens_buffer" not in expand_buffer_markers(at_cap)

    over = f"SELECT {calls}, geolens_buffer(s.geom_4326, 900) FROM data.stations s"
    _refusal(over)


def test_the_marker_cap_matches_the_validators_verification_budget():
    """One over the validator's budget is one the sandbox would refuse anyway.

    ``_MAX_BUFFER_MATCH_ATTEMPTS`` bounds how many buffer-shaped subtrees the
    validator will re-render and verify; past it no exemption is granted. So
    expanding a ninth marker can only produce SQL that is rejected after
    ~25 KB of rendering. Keeping the two numbers equal is the point, not a
    coincidence — this fails if either moves alone.
    """
    from app.platform.sandbox.validator import _MAX_BUFFER_MATCH_ATTEMPTS

    assert MAX_BUFFER_MARKERS == _MAX_BUFFER_MATCH_ATTEMPTS


# ---------------------------------------------------------------------------
# The geometry argument keeps every check the sandbox applies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "geom",
    [
        pytest.param("pg_sleep(5)", id="pg_sleep"),
        pytest.param("pg_read_file('/etc/passwd')", id="pg_read_file"),
        pytest.param("lo_import('/etc/passwd')", id="lo_import"),
        pytest.param("dblink('host=evil', 'SELECT 1')", id="dblink"),
        pytest.param("ST_AsEWKB(s.geom_4326) || 'x'", id="concat"),
        pytest.param(
            "(SELECT pg_sleep(5) FROM data.other)", id="subquery-hiding-a-call"
        ),
        pytest.param("ST_Transform(s.geom_4326, 3857)", id="reprojection"),
        pytest.param(
            "ST_Buffer(ST_SetSRID(ST_MakePoint(0, 0), 4326), 1000000000)",
            id="planar-buffer-in-degrees",
        ),
    ],
)
def test_expansion_grants_the_geometry_argument_nothing(geom):
    """The exemption covers the scaffold the renderer produced, never the
    argument. A marker is therefore not a way in: whatever the model puts in
    the geometry slot is validated as ordinary SQL, exactly as it would be if
    the model had written the whole expression itself."""
    expanded = expand_buffer_markers(_wrap(f"geolens_buffer({geom}, 100)"))
    with pytest.raises(SandboxError) as excinfo:
        validate_sql(expanded)
    assert excinfo.value.category == "invalid_query"


def test_a_comment_cannot_smuggle_sql_through_the_argument_split():
    """A comment that carries the separator, the terminator and a payload.

    The scanner reads it as a comment when it splits the arguments, so neither
    the ``,`` nor the ``)`` inside it moves the split, and ``_without_comments``
    then drops it before anything is rendered. So ``pg_sleep`` never becomes a
    call and ``data.t`` never becomes a table.

    What is left is ``s.geom_4326``, and the statement VALIDATES. That is the
    right outcome rather than a lucky one: the attempt failed as an attempt,
    and the query that remains is the ordinary buffer the model asked for.
    Before fix(#1589 review r1) this was refused instead, which looked like
    security and was really the comment breaking the canonical re-render — the
    same collateral damage a plain ``/* the stop */`` took.
    """
    smuggle = "s.geom_4326 /*, 1) AS g, pg_sleep(9) FROM data.t --*/"
    expanded = expand_buffer_markers(_wrap(f"geolens_buffer({smuggle}, 100)"))

    stmt = sqlglot.parse_one(expanded, dialect="postgres")
    called = {fn.name.lower() for fn in stmt.find_all(sqlglot.exp.Anonymous)}
    assert "pg_sleep" not in called
    assert not [tbl for tbl in stmt.find_all(sqlglot.exp.Table) if tbl.name == "t"]

    assert expanded == _wrap(render_geodesic_buffer("s.geom_4326", 100.0))
    assert validate_sql(expanded).tables == {("data", "stations")}


def test_a_benign_marker_in_the_same_shape_validates():
    """The counterfactual for the refusals above: same statement, same
    expansion, an ordinary column in the geometry slot."""
    result = validate_sql(
        expand_buffer_markers(_wrap("geolens_buffer(s.geom_4326, 500)"))
    )
    assert result.tables == {("data", "stations")}


def test_a_cast_around_the_call_does_not_break_the_exemption():
    """``geolens_buffer(...)::geometry`` is a shape the model may reach for,
    and the exemption is matched on the subquery inside the cast, so it still
    lands."""
    result = validate_sql(
        expand_buffer_markers(
            "SELECT geolens_buffer(s.geom_4326, 500)::geometry AS g "
            "FROM data.stations s LIMIT 10"
        )
    )
    assert result.tables == {("data", "stations")}


def test_the_expansion_is_what_the_validator_recognises_as_canonical():
    """Not merely 'the statement validates' — the buffer's own machinery is
    admitted through the fix(#1001) exemption, which is only granted to an
    exact re-render."""
    from app.platform.sandbox.validator import _canonical_buffer_exempt_ids

    expanded = expand_buffer_markers(_wrap("geolens_buffer(s.geom_4326, 500)"))
    stmt = sqlglot.parse_one(expanded, dialect="postgres")
    assert _canonical_buffer_exempt_ids(stmt), (
        "the expansion was not recognised as the canonical buffer, so the "
        "sandbox is admitting it for some other reason"
    )


# ---------------------------------------------------------------------------
# Placement: model output expands, user-written SQL does not
# ---------------------------------------------------------------------------


async def test_generate_sql_expands_before_it_returns(monkeypatch):
    """The marker never leaves ``generate_sql``.

    Every NL consumer goes through this one function (``chat_actions``'s
    ``query_data`` is the only production caller, the evals are the other),
    so expanding at its tail is what makes the marker a private protocol
    between the prompt and the server rather than a new SQL dialect.
    """
    from app.processing.ai import sql_generator as sg
    from app.processing.ai.llm_loop import ToolLoopResult

    class _Setting:
        def __init__(self, value):
            self._value = value

        async def get(self, _db):
            return self._value

    class _FakeProvider:
        async def resolve_runtime_config(self, _db):
            return {"base_url": None}

        async def complete(self, **_kw):
            return ToolLoopResult(
                text=(
                    "```sql\n"
                    "SELECT ST_AsGeoJSON(geolens_buffer(s.geom_4326, 500)) AS geometry\n"
                    "FROM data.stations s LIMIT 100;\n"
                    "```"
                )
            )

    monkeypatch.setattr(sg, "LLM_PROVIDER", _Setting("anthropic"))
    monkeypatch.setattr(sg, "LLM_MODEL_LIGHT", _Setting("test-model"))
    monkeypatch.setattr(sg, "get_ai_provider", lambda _name: _FakeProvider())

    sql = await sg.generate_sql(None, "buffer the stations by 500 m", "-- ddl")

    assert "geolens_buffer" not in sql
    assert sql == (
        f"SELECT ST_AsGeoJSON({render_geodesic_buffer('s.geom_4326', 500.0)}) "
        "AS geometry\nFROM data.stations s LIMIT 100"
    )


async def test_the_raw_query_endpoint_does_not_expand_a_marker(
    client, admin_auth_header, test_db_session
):
    """``POST /api/query/`` takes SQL a person wrote, so the marker has no
    meaning there and must stay the unknown function it is.

    This is the counterfactual for "model-only": if expansion ever moved down
    into the sandbox, this request would start succeeding.
    """
    import uuid as _uuid

    from sqlalchemy import text as _text

    from tests.factories import create_dataset

    me = (await client.get("/auth/me/", headers=admin_auth_header)).json()["id"]
    tbl = f"m1589_{_uuid.uuid4().hex[:10]}"
    await test_db_session.execute(
        _text(f"CREATE TABLE data.{tbl} (gid int, geom_4326 geometry(Point, 4326))")
    )
    await test_db_session.execute(
        _text(
            f"INSERT INTO data.{tbl} VALUES "
            "(1, ST_SetSRID(ST_MakePoint(-73.9, 40.7), 4326))"
        )
    )
    await test_db_session.commit()
    await create_dataset(test_db_session, created_by=_uuid.UUID(me), table_name=tbl)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT ST_AsGeoJSON(geolens_buffer(t.geom_4326, 500)) "
                f"FROM data.{tbl} t"
            ),
            "restrict_tables": [tbl],
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Query uses a disallowed function"

    # And the same statement without the marker runs, so the refusal above is
    # about the marker and not about the fixture.
    ok = await client.post(
        "/query/",
        json={
            "sql": f"SELECT ST_AsGeoJSON(t.geom_4326) FROM data.{tbl} t",
            "restrict_tables": [tbl],
        },
        headers=admin_auth_header,
    )
    assert ok.status_code == 200, ok.text


def test_the_chat_path_rewrites_that_follow_expansion_keep_the_buffer_valid():
    """fix(#1589 review r1): the two rewrites ``query_data`` applies AFTER
    ``generate_sql`` returns, run over the expanded 3 KB scaffold.

    ``ensure_geometry_selected`` parses the statement with sqlglot and prints
    it back, and the truncation-recovery COUNT wraps it in another SELECT.
    Both are full round-trips of the rendered buffer, and
    ``_matches_canonical_buffer`` compares by re-render, so a sqlglot upgrade
    that changed how any scaffold node prints would break metric buffers in
    production while every eval stayed green — the evals call
    ``validate_and_execute`` on ``generate_sql``'s output directly and never
    see either rewrite. No DB needed to pin it.
    """
    from app.processing.ai.chat_geojson import ensure_geometry_selected

    layers = [
        ChatMapLayer(
            id="layer-1",
            name="Stations",
            dataset_id="11111111-1111-1111-1111-111111111111",
            dataset_table_name="stations",
            geometry_type="Point",
        )
    ]
    # Attribute-only projection, which is the shape that makes
    # ensure_geometry_selected actually append a column.
    expanded = expand_buffer_markers(
        "SELECT s.name FROM data.stations s "
        "WHERE ST_Intersects(s.geom_4326, geolens_buffer(s.geom_4326, 500)) "
        "LIMIT 100"
    )
    with_geometry = ensure_geometry_selected(expanded, layers)
    assert with_geometry != expanded, (
        "the fixture no longer exercises the append, so this test proves "
        "nothing about the rewrite"
    )
    assert validate_sql(with_geometry).tables == {("data", "stations")}

    # chat_actions builds this one when the row cap truncated the result.
    counted = f"SELECT COUNT(*) AS n FROM ({with_geometry}) AS _geolens_total"
    assert validate_sql(counted).tables == {("data", "stations")}


def test_expansion_has_exactly_one_call_site():
    """A closed list, not a convention.

    The property "user-written SQL is never expanded" is a statement about
    which modules call the expander, so it is checked that way. Adding the
    call to ``query_router.py`` — or to the sandbox — fails here.
    """
    import ast
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[1] / "app"
    callers: set[str] = set()
    for candidate in sorted(app_root.rglob("*.py")):
        rel = candidate.relative_to(app_root.parent).as_posix()
        if rel == "app/processing/ai/buffer_marker.py":
            continue
        tree = ast.parse(candidate.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            named = (
                isinstance(node, ast.ImportFrom)
                and any(a.name == "expand_buffer_markers" for a in node.names)
            ) or (isinstance(node, ast.Name) and node.id == "expand_buffer_markers")
            if named or (
                isinstance(node, ast.Attribute) and node.attr == "expand_buffer_markers"
            ):
                callers.add(rel)

    assert callers == {"app/processing/ai/sql_generator.py"}, (
        "the buffer-marker expander reached a module outside the NL->SQL "
        f"generation path: {sorted(callers)}"
    )
