"""Expand the NL->SQL prompt's ``geolens_buffer`` marker (fix(#1589)).

Asking the model to write ``render_geodesic_buffer``'s SQL by hand (#1001)
failed unreliably: a dropped parenthesis or a paraphrase back to the bare
``ST_Buffer(geom::geography, N)::geometry`` form. The model now writes
``geolens_buffer(<geom>, <metres>)`` and this module substitutes the
canonical render before anything else sees the SQL.

Not a new privilege: it produces exactly the text a model was previously
asked to type, and ``_matches_canonical_buffer`` in
``platform/sandbox/validator.py`` still re-renders the template, compares
ASTs, and validates the geometry argument under the full allowlist. This
module decides SYNTAX only — a plain in-range distance number; whether the
geometry argument is ACCEPTABLE stays the sandbox's decision (#1002).

Deliberately NOT applied to the raw ``POST /api/query/`` endpoint, which
takes SQL a person wrote — there the marker is an unknown function and
stays one. ``tests/test_ai_buffer_marker_1589.py`` pins the call site as a
closed list.
"""

from __future__ import annotations

import math
import re

import sqlglot
import structlog
from sqlglot import exp

from app.platform.analysis_sql import MAX_BUFFER_METERS, render_geodesic_buffer
from app.platform.sandbox import SandboxError

logger = structlog.stdlib.get_logger(__name__)

_MARKER = "geolens_buffer"

# Characters PostgreSQL admits inside an unquoted identifier after the first.
# ``$`` is one of them, which is why the token boundary cannot be ``\w``.
_IDENT_CHARS = re.compile(r"[A-Za-z0-9_$]")

# A plain decimal number and nothing else: no sign, no cast, no arithmetic, no
# ``_`` digit separators (``float("1_000")`` accepts those, so the regex has to
# be the gate rather than the float call), no ``NaN``/``Infinity`` spelling.
# The distance is interpolated straight into SQL text by
# ``render_geodesic_buffer``, so this is that argument's injection boundary and
# it is an allowlist.
_DISTANCE = re.compile(r"\A(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")

# A dollar-quote opener: ``$$`` or ``$tag$``. Distinguishes one from a
# positional parameter (``$1``), which is not a quote at all.
_DOLLAR_OPEN = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")

# How many markers one statement may carry — not arbitrary: it's the
# validator's ``_MAX_BUFFER_MATCH_ATTEMPTS``, which bounds how many
# buffer-shaped subtrees the sandbox re-renders and verifies. Past it no
# exemption is granted, so a ninth expansion would only cost the parse to
# buy a worse error.
# ``test_the_marker_cap_matches_the_validators_verification_budget`` fails
# if either number moves alone.
MAX_BUFFER_MARKERS = 8


def _fail(message: str) -> SandboxError:
    """A marker problem, in the sandbox's own vocabulary.

    ``invalid_query`` is the existing category for "this SQL cannot run",
    already mapped by ``chat_actions._execute_chat_tool``.

    fix(#1589): ``message`` is server-only. ``_execute_chat_tool`` replaces
    it with the generic ``ERROR_MESSAGES["invalid_query"]`` line, so neither
    user nor model ever sees the specific text — it's logged here for that
    reason, read by this log line and by pytest when an eval trips one.

    Surfacing it to the MODEL instead (so it could self-correct) is
    deliberately out of scope here: it means widening which sandbox
    messages are safe to echo into a chat turn, a shared-path change that
    belongs with the repair-pass work, not smuggled in beside it.
    """
    logger.info("sql.buffer_marker_rejected", reason=message)
    return SandboxError("invalid_query", message)


def _skip_comment(sql: str, i: int) -> int | None:
    """Index just past the comment starting at ``i``; None when none does."""
    if sql.startswith("--", i):
        end = sql.find("\n", i)
        return len(sql) if end == -1 else end + 1
    if sql.startswith("/*", i):
        # PostgreSQL block comments nest, so a naive find("*/") would end this
        # one early and read the rest of an inner comment as code.
        depth, j = 1, i + 2
        while j < len(sql):
            if sql.startswith("/*", j):
                depth += 1
                j += 2
            elif sql.startswith("*/", j):
                depth -= 1
                j += 2
                if depth == 0:
                    return j
            else:
                j += 1
        raise _fail("Query has an unterminated comment")
    return None


def _is_ident_at(sql: str, i: int) -> bool:
    """Whether ``sql[i]`` is an identifier character (out of range: no)."""
    return 0 <= i < len(sql) and _IDENT_CHARS.match(sql[i]) is not None


def _skip_quoted(sql: str, i: int) -> int | None:
    """Index just past the literal starting at ``i``; None when none does.

    Handles single-quoted strings (``''`` escapes), ``E''`` escape strings
    (backslash escapes), quoted identifiers and dollar-quoted strings. Not
    handled: ``U&'...'``, whose ``UESCAPE`` clause can redefine the escape
    character. Nothing teaches the model that form, and the failure direction
    is safe — a mis-read produces either a refusal here or SQL the sandbox
    parses and validates in full.
    """
    ch = sql[i]
    if ch in ("'", '"'):
        # An E-string prefix changes the escaping rules, so it is read here
        # rather than passing as an ordinary identifier character.
        escaped = (
            ch == "'" and i > 0 and sql[i - 1] in "Ee" and not _is_ident_at(sql, i - 2)
        )
        j = i + 1
        while j < len(sql):
            if escaped and sql[j] == "\\":
                j += 2
                continue
            if sql[j] == ch:
                if j + 1 < len(sql) and sql[j + 1] == ch:
                    j += 2
                    continue
                return j + 1
            j += 1
        raise _fail("Query has an unterminated string literal")
    if ch == "$":
        opener = _DOLLAR_OPEN.match(sql, i)
        if opener is None:
            return None
        end = sql.find(opener.group(0), opener.end())
        if end == -1:
            raise _fail("Query has an unterminated string literal")
        return end + len(opener.group(0))
    return None


def _skip_non_code(sql: str, i: int) -> int | None:
    """Index just past the literal or comment at ``i``; None when neither.

    The argument split has to see the SQL the way PostgreSQL does, because
    every character this skips is one that would otherwise read as structure:
    ``'Elm (North), Ward 2'`` carries both the separator and the terminator the
    scanner looks for, and a comment can carry an unbalanced parenthesis.
    """
    comment = _skip_comment(sql, i)
    if comment is not None:
        return comment
    return _skip_quoted(sql, i)


def _marker_starts_at(sql: str, i: int, previous: str) -> bool:
    """Whether a bare ``geolens_buffer`` token begins at ``i``.

    Case-insensitive, whole-token, and unqualified: ``geolens_buffer_x`` is
    a different name, and ``public.geolens_buffer`` names some other
    schema's function.

    ``previous`` is the last non-whitespace, non-comment character before
    ``i``, tracked by callers as they scan. fix(#1589): reading
    ``sql[i - 1]`` directly instead broke on ``public./**/geolens_buffer(…)``
    and ``public. geolens_buffer(…)`` — both qualified names in PostgreSQL,
    but the raw lookback saw ``/`` or a space, not the dot. ADJACENCY stays
    positional (``xgeolens_buffer`` is one identifier, ``x geolens_buffer``
    is two); only the QUALIFIER check needed to skip comments/whitespace.
    """
    if sql[i : i + len(_MARKER)].lower() != _MARKER:
        return False
    if _is_ident_at(sql, i - 1) or previous == ".":
        return False
    return not _is_ident_at(sql, i + len(_MARKER))


def _next_code_char(sql: str, i: int) -> int | None:
    """Index of the next character that is neither whitespace nor a comment."""
    while i < len(sql):
        if sql[i].isspace():
            i += 1
            continue
        past = _skip_comment(sql, i)
        if past is None:
            return i
        i = past
    return None


def _split_call_args(sql: str, open_paren: int) -> tuple[list[str], int]:
    """Arguments of the call whose ``(`` is at ``open_paren``, and its end.

    Balanced-parenthesis scanning over code positions only. Returns the raw
    argument slices (unstripped) and the index just past the closing ``)``.
    """
    depth = 1
    start = open_paren + 1
    args: list[str] = []
    i = start
    while i < len(sql):
        past = _skip_non_code(sql, i)
        if past is not None:
            i = past
            continue
        ch = sql[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                args.append(sql[start:i])
                return args, i + 1
        elif ch == "," and depth == 1:
            args.append(sql[start:i])
            start = i + 1
        i += 1
    raise _fail(f"Query has an unclosed {_MARKER}() call")


def _contains_marker(text: str) -> bool:
    """Whether ``text`` holds a ``geolens_buffer`` token at a code position.

    Tracks ``previous`` exactly as ``expand_buffer_markers`` does, so the two
    agree on what counts as a marker. They disagreeing is how a string could be
    expanded at the top level and rejected as nesting inside an argument.
    """
    i = 0
    previous = ""
    while i < len(text):
        past = _skip_comment(text, i)
        if past is not None:
            i = past  # a comment is transparent; `previous` carries across it
            continue
        past = _skip_quoted(text, i)
        if past is not None:
            previous = text[past - 1]
            i = past
            continue
        if _marker_starts_at(text, i, previous):
            return True
        if not text[i].isspace():
            previous = text[i]
        i += 1
    return False


def _without_comments(text: str) -> str:
    """``text`` with its comments replaced by a space, literals untouched.

    fix(#1589): the scanner skips comments when splitting arguments, but
    the slice it returns still contains them, and
    ``render_geodesic_buffer`` interpolates that slice into a larger
    expression. A block comment rides into the scaffold and perturbs the
    text ``_matches_canonical_buffer`` re-renders and compares, so the
    exemption is refused ("disallowed spatial function"). A line comment
    comments out the rest of a single-line render ("invalid SQL syntax").
    Both fail closed on a model call that was correct. PostgreSQL treats a
    comment as whitespace, so dropping one is semantics-preserving; the
    replacement is a SPACE, not nothing, so ``a/*x*/b`` can't fuse into one
    identifier.
    """
    if "--" not in text and "/*" not in text:
        return text
    kept: list[str] = []
    i = 0
    while i < len(text):
        past = _skip_comment(text, i)
        if past is not None:
            kept.append(" ")
            i = past
            continue
        # A literal is opaque: a `--` inside 'a--b' is data, not a comment.
        past = _skip_quoted(text, i)
        if past is not None:
            kept.append(text[i:past])
            i = past
            continue
        kept.append(text[i])
        i += 1
    return "".join(kept)


def _single_expression(text: str) -> exp.Expression | None:
    """The one expression ``text`` parses to, or None when it is not one.

    None covers three cases the caller treats alike: sqlglot cannot parse it,
    it is more than one statement, or it is a bare statement rather than an
    expression. A parenthesised ``(SELECT …)`` is an ``exp.Subquery`` and so
    an expression, which is the shape the prompt teaches for a scalar input.
    """
    try:
        parsed = [stmt for stmt in sqlglot.parse(text, dialect="postgres") if stmt]
    except Exception:  # broad: any sqlglot failure is a refusal
        return None
    if len(parsed) != 1:
        return None
    root = parsed[0]
    if isinstance(root, exp.Query) and not isinstance(root, exp.Subquery):
        return None
    return root


def _matching_paren(text: str, opening: int) -> int | None:
    """Index of the ``)`` closing the ``(`` at ``opening``; None if unbalanced.

    Scans code positions only, so a ``)`` inside a string literal does not
    close anything.
    """
    depth = 0
    i = opening
    while i < len(text):
        past = _skip_non_code(text, i)
        if past is not None:
            i = past
            continue
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _without_redundant_parens(text: str) -> str:
    """``text`` with wrapping parentheses removed, one layer at a time.

    fix(#1589): ``geolens_buffer((s.geom_4326), 500)`` is a correct call —
    the parentheses are the model's formatting, not the validator's
    contract — but ``_is_bounded_geometry_source`` recognises only a bare
    column or a scalar subquery, so the wrapped form was refused as
    "disallowed spatial function".

    Two conditions stop the peel: the opening paren must be closed by the
    LAST character (else ``(a) + (b)`` loses its grouping, or
    ``(s.geom_4326)::geometry`` loses a cast's operand), and the inside
    must still be an expression afterwards (else ``((SELECT …))`` peels
    twice into a bare ``SELECT``, not the scalar the renderer needs — it
    peels once, to ``(SELECT …)``, which the validator accepts).
    """
    while text.startswith("("):
        close = _matching_paren(text, 0)
        if close is None or text[close + 1 :].strip():
            break
        inner = text[1:close].strip()
        if not inner or _single_expression(inner) is None:
            break
        text = inner
    return text


def _checked_geometry(raw: str) -> str:
    """The geometry argument, checked for SYNTAX and nothing else.

    One expression, not a bare statement — a structurally broken argument
    fails here rather than as a confusing sandbox error two layers later.
    Whether the expression is an acceptable buffer INPUT stays with
    ``_is_bounded_geometry_source`` and the function allowlist (#1002).

    Comments are dropped and redundant wrapping parens peeled (see
    ``_without_comments``/``_without_redundant_parens``): both are
    formatting the model chose that would otherwise cost it the exemption.
    """
    geom = _without_comments(raw).strip()
    if not geom:
        raise _fail(f"{_MARKER}() needs a geometry expression")
    if _contains_marker(geom):
        # Innermost-first expansion would render fine and then be refused:
        # only a stored geometry gets the exemption, and a buffer isn't one.
        # Checked BEFORE the peel so a parenthesised nested marker is
        # refused, not unwrapped.
        raise _fail(f"{_MARKER}() cannot be nested inside another {_MARKER}()")
    geom = _without_redundant_parens(geom)
    if _single_expression(geom) is None:
        raise _fail(f"{_MARKER}()'s geometry argument is not a single expression")
    return geom


def _checked_distance(raw: str) -> float:
    """The distance argument as a float, or a refusal.

    A literal only. ``render_geodesic_buffer`` interpolates this value into
    SQL and does NOT bound it — ``render_buffer_expr`` does, and it's not
    on this path — so the range check happens here: greater than zero, at
    most ``MAX_BUFFER_METERS``. A zero-metre buffer is refused rather than
    rendered empty, matching the analysis surface.

    Comments are dropped first (fix(#1589)) so
    ``geolens_buffer(s.geom_4326, 500 /* metres */)`` still parses.
    """
    text = _without_comments(raw).strip()
    if not _DISTANCE.match(text):
        raise _fail(f"{_MARKER}()'s distance must be a plain number of metres")
    distance = float(text)
    if not math.isfinite(distance) or not 0 < distance <= MAX_BUFFER_METERS:
        raise _fail(
            f"{_MARKER}()'s distance must be between 0 and {MAX_BUFFER_METERS:g} metres"
        )
    return distance


def expand_buffer_markers(sql: str) -> str:
    """Replace every ``geolens_buffer(geom, metres)`` with the real expression.

    Returns ``sql`` itself when it carries no marker, so the far more common
    no-buffer path costs one substring search and changes nothing.

    Raises:
        SandboxError: category ``invalid_query``, for a malformed marker — bad
            arity, a distance that is not a plain in-range number, an unclosed
            call, a nested marker, or more markers than the sandbox will
            verify.
    """
    if _MARKER not in sql.lower():
        return sql

    pieces: list[str] = []
    consumed = 0
    markers = 0
    i = 0
    # The last character that was neither whitespace nor part of a comment.
    # Only the qualifier rule reads it; see _marker_starts_at.
    previous = ""
    while i < len(sql):
        past = _skip_comment(sql, i)
        if past is not None:
            i = past  # a comment is transparent; `previous` carries across it
            continue
        past = _skip_quoted(sql, i)
        if past is not None:
            previous = sql[past - 1]
            i = past
            continue
        if not _marker_starts_at(sql, i, previous):
            if not sql[i].isspace():
                previous = sql[i]
            i += 1
            continue

        # A bare ``geolens_buffer`` that is not a call is left alone: it is a
        # name the sandbox refuses on its own terms, and guessing at what the
        # model meant is not this module's job.
        after = _next_code_char(sql, i + len(_MARKER))
        if after is None or sql[after] != "(":
            previous = _MARKER[-1]
            i += len(_MARKER)
            continue

        markers += 1
        if markers > MAX_BUFFER_MARKERS:
            raise _fail(f"Query uses more than {MAX_BUFFER_MARKERS} {_MARKER}() calls")

        args, end = _split_call_args(sql, after)
        if len(args) != 2:
            raise _fail(
                f"{_MARKER}() takes exactly two arguments: a geometry and a "
                "distance in metres"
            )
        geom = _checked_geometry(args[0])
        distance = _checked_distance(args[1])

        pieces.append(sql[consumed:i])
        pieces.append(render_geodesic_buffer(geom, distance))
        consumed = end
        previous = ")"
        i = end

    if not pieces:
        return sql
    pieces.append(sql[consumed:])
    expanded = "".join(pieces)
    # Nightly eval triage is the reason this line exists: when a buffer
    # question fails, the first thing worth knowing is whether the model asked
    # for a buffer at all, and after expansion the SQL no longer says.
    logger.info(
        "sql.buffer_markers_expanded", markers=markers, sql_length=len(expanded)
    )
    return expanded
