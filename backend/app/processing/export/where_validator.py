"""AST-based WHERE-clause validator (SEC-S09).

Wraps the user-supplied ``where`` fragment in ``SELECT 1 FROM _t WHERE <fragment>``
and parses with sqlglot postgres dialect.  Walks the resulting WHERE node and
raises ValueError if any expression type outside the strict allowlist appears.

This is a peer-companion to ``app.platform.sandbox.validator.validate_sql`` —
same parser, same dialect, but allowlist-based (statement-level validator is
blocklist-based because the input shape is broader).  The two share no code
paths; cross-cutting refactor not justified for SEC-S09 scope.

Allowed WHERE expression types (deny-by-default — anything not in this tuple raises):
  - Column, Identifier   — column references
  - Literal, Boolean, Null  — scalar values
  - EQ, NEQ, LT, LTE, GT, GTE  — comparison operators
  - And, Or, Not         — logical operators
  - In, Is, Like, ILike  — containment / null-test / pattern
  - Between              — range check
  - Paren                — parenthesised sub-expression
  - Neg                  — unary minus (e.g. -5)
  - Where                — the top-level WHERE node itself
"""

from __future__ import annotations

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
    exp.Neg,
    exp.Where,  # the top-level WHERE node itself
)


def validate_where_ast(where: str) -> None:
    """Validate that ``where`` is a safe WHERE-clause fragment.

    Parses ``SELECT 1 FROM _t WHERE <where>`` with the sqlglot postgres
    dialect and walks the resulting WHERE node.  Raises ValueError if:

    - ``where`` is empty or blank.
    - sqlglot cannot parse the fragment (invalid SQL syntax).
    - The wrapped statement is not a single SELECT (indicates multi-statement
      injection or UNION grammar).
    - Any node in the WHERE subtree is not in ALLOWED_EXPRESSIONS (catches
      subqueries, function calls, DDL fragments, etc.).

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
