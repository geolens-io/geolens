"""AST-based WHERE-clause validator (SEC-S09).

Wraps ``where`` in ``SELECT 1 FROM _t WHERE <fragment>``, parses with
sqlglot postgres dialect, and walks the WHERE node — anything outside the
strict allowlist raises ValueError.

Peer-companion to ``app.platform.sandbox.validator.validate_sql`` — same
parser/dialect, but allowlist-based (that one is blocklist-based). No code
paths shared.

Allowed types (deny-by-default): Column/Identifier (columns), Literal/
Boolean/Null (scalars), EQ/NEQ/LT/LTE/GT/GTE (comparisons), And/Or/Not
(logic), In/Is/Like/ILike/Between (containment/pattern/range), Paren, Neg
(unary minus), Where (top-level node).
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

# Strict allowlist — every node type found during an AST walk of the WHERE
# subtree must be an instance of one of these.  New types require explicit
# review before being added.
ALLOWED_EXPRESSIONS: tuple[type, ...] = (
    # Column references
    exp.Column,
    exp.Identifier,
    # Scalar literals
    exp.Literal,
    exp.Boolean,
    exp.Null,
    # Comparison operators
    exp.EQ,
    exp.NEQ,
    exp.LT,
    exp.LTE,
    exp.GT,
    exp.GTE,
    # Logical operators
    exp.And,
    exp.Or,
    exp.Not,
    # Containment / null-test / pattern
    exp.In,
    exp.Is,
    exp.Like,
    exp.ILike,
    exp.Between,
    # Structural
    exp.Paren,
    # exp.Neg is included ONLY for negative literal values (WHERE col = -5).
    # Binary arithmetic operators (Add/Sub/Mul/Div) are intentionally
    # EXCLUDED — allowing them would permit expression injection into
    # IN-list or comparison arguments (e.g. WHERE 1+1=2 UNION ...). Do NOT
    # add exp.Add by analogy with exp.Neg.
    exp.Neg,
    # exp.Dot (table-qualified column, `tbl.col`) is intentionally EXCLUDED.
    # sqlglot's postgres dialect folds `tbl.col` into an exp.Column node's
    # .table/.db/.catalog args rather than a separate exp.Dot node, so the
    # rejection is enforced inside validate_where_ast by inspecting those
    # args (see KNOWN-10 block below). Only unqualified column names are
    # accepted; enabling qualified names would need a security review AND an
    # update to the downstream identifier regex to split and validate each
    # component.
    exp.Where,  # the top-level WHERE node itself
)


def validate_where_ast(where: str) -> None:
    """Validate that ``where`` is a safe WHERE-clause fragment.

    Raises ValueError if empty/blank, unparseable, not a single SELECT
    (multi-statement injection or UNION), or any WHERE-subtree node isn't
    in ALLOWED_EXPRESSIONS (subqueries, function calls, DDL, etc.).

    Args:
        where: SQL WHERE-clause fragment supplied by the caller.

    Raises:
        ValueError: Description of the disallowed construct.
    """
    if not where or not where.strip():
        raise ValueError("Empty WHERE expression")

    wrapped = f"SELECT 1 FROM _t WHERE {where}"
    try:
        statements = sqlglot.parse(wrapped, dialect="postgres")
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError) as exc:
        raise ValueError(f"Invalid WHERE syntax: {exc}") from exc

    statements = [s for s in statements if s is not None]

    # Multi-statement injection produces len > 1.
    # UNION grammar produces a Union node rather than Select.
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise ValueError("Only a single WHERE expression is allowed")

    where_node = statements[0].args.get("where")
    if where_node is None:
        raise ValueError("Empty WHERE expression")

    # Walk every node in the WHERE subtree; reject anything outside allowlist.
    for node in where_node.walk():
        if not isinstance(node, ALLOWED_EXPRESSIONS):
            raise ValueError(
                f"Disallowed expression in WHERE clause: {type(node).__name__}"
            )
        # Table-qualified columns (`tbl.col`, `cat.tbl.col`) are rejected
        # even though `exp.Column` is allowed: sqlglot folds table/db/
        # catalog into the Column node's args rather than a separate
        # exp.Dot, so the check must inspect Column.table/.db here to match
        # the module docstring's claim (Phase 1071 KNOWN-10).
        if isinstance(node, exp.Column) and (
            node.args.get("table") is not None
            or node.args.get("db") is not None
            or node.args.get("catalog") is not None
        ):
            raise ValueError(
                "Disallowed expression in WHERE clause: table-qualified "
                "column reference (only unqualified column names are accepted)"
            )


def canonical_where(where: str) -> str:
    """Validate ``where`` and return its canonical sqlglot re-render.

    fix(#430): for callers that interpolate the fragment into SQL
    text, the re-emission of the validated AST is used, never raw bytes.

    Raises ValueError via validate_where_ast on any disallowed construct.
    """
    validate_where_ast(where)
    wrapped = f"SELECT 1 FROM _t WHERE {where}"
    statements = sqlglot.parse(wrapped, dialect="postgres")
    return statements[0].args["where"].this.sql(dialect="postgres")


# fix(#1870): BOTH quote kinds are scanned in one pass, because a
# single quote inside a double-quoted identifier opens no literal in Postgres
# and must open none here either.
_QUOTED_RUN_RE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")


def mask_quoted_literals(where: str) -> str:
    """Blank every single-quoted literal in ``where``, preserving its length.

    A caller scanning for code (identifier walk, token classifier) must not
    read values as code. A double-quoted identifier IS code, so it's scanned
    but returned unchanged — consuming it in the same pass stops a quote
    inside it from opening a literal that blanks real code after it.
    Dollar-quoting and E'' are rejected by the AST gate, not modelled here.

    Args:
        where: SQL WHERE-clause fragment.

    Returns:
        The fragment with string-literal contents replaced by spaces.
        Trailing text after an unterminated quote is unchanged; callers
        reject an unbalanced clause before masking.
    """

    def _blank_literals_only(match: re.Match[str]) -> str:
        run = match.group(0)
        return run if run.startswith('"') else " " * len(run)

    return _QUOTED_RUN_RE.sub(_blank_literals_only, where)
