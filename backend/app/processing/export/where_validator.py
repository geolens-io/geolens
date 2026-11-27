"""AST-based WHERE-clause validator.

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
from sqlglot.dialects.postgres import Postgres
from sqlglot.tokens import Token, TokenType

# Strict allowlist: every node type found during an AST walk of the WHERE
# subtree must be an instance of one of these.
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
    # exp.Neg is included only for negative literal values (WHERE col = -5).
    # Binary arithmetic operators (Add/Sub/Mul/Div) are excluded: allowing them
    # would permit expression injection into IN-list or comparison arguments
    # (e.g. WHERE 1+1=2 UNION ...).
    exp.Neg,
    # exp.Dot (table-qualified column, `tbl.col`) is excluded. sqlglot's
    # postgres dialect folds `tbl.col` into an exp.Column node's
    # .table/.db/.catalog args rather than a separate exp.Dot node, so
    # validate_where_ast rejects it by inspecting those args. Only unqualified
    # column names are accepted; qualified names would also need the
    # downstream identifier regex to split and validate each component.
    exp.Where,  # the top-level WHERE node itself
)


# The wrapper's own parts of the parsed SELECT. Any other populated part was
# parsed from text after the condition.
_WRAPPER_SELECT_ARGS = frozenset({"expressions", "from_", "where"})


_COMPARISONS: tuple[type, ...] = (exp.EQ, exp.NEQ, exp.LT, exp.LTE, exp.GT, exp.GTE)
_PLAIN_OPERANDS: tuple[type, ...] = (
    exp.Column,
    exp.Literal,
    exp.Boolean,
    exp.Null,
    exp.Paren,
    exp.Neg,
)
# Parents a NOT may sit under unparenthesized and keep its meaning when
# rendered. sqlglot prints a NOT inside anything else as a prefix that
# PostgreSQL binds more loosely: ``a NOT IN (1) <= b`` comes out as
# ``NOT a IN (1) <= b``, which PostgreSQL reads as ``NOT (a IN (1) <= b)``.
_NOT_KEEPS_MEANING_UNDER: tuple[type, ...] = (
    exp.And,
    exp.Or,
    exp.Not,
    exp.Paren,
    exp.Where,
)


# The filter language at the token level, checked before sqlglot normalizes
# anything: each operator in its standard spelling only. sqlglot reads some
# PostgreSQL spellings as something else (``~~`` as LIKE, ``!!`` as two NOTs,
# ``|>`` as pipe syntax) and drops others (unary ``+``), so only the spellings
# below are accepted.
_KEYWORD_TOKENS: dict[str, TokenType] = {
    "AND": TokenType.AND,
    "OR": TokenType.OR,
    "NOT": TokenType.NOT,
    "IN": TokenType.IN,
    "BETWEEN": TokenType.BETWEEN,
    "LIKE": TokenType.LIKE,
    "ILIKE": TokenType.ILIKE,
    "IS": TokenType.IS,
    "NULL": TokenType.NULL,
    "TRUE": TokenType.TRUE,
    "FALSE": TokenType.FALSE,
}
_OPERATOR_TOKENS: dict[TokenType, frozenset[str]] = {
    TokenType.EQ: frozenset({"="}),
    TokenType.NEQ: frozenset({"<>", "!="}),
    TokenType.LT: frozenset({"<"}),
    TokenType.LTE: frozenset({"<="}),
    TokenType.GT: frozenset({">"}),
    TokenType.GTE: frozenset({">="}),
    TokenType.DASH: frozenset({"-"}),
}
_WORD_RE = re.compile(r"[^\W\d][\w$]*\Z")
_NUMBER_RE = re.compile(r"\d+(\.\d+)?\Z")
_REFUSED = "Disallowed expression in WHERE clause: {}"
_SINGLE = "Only a single WHERE expression is allowed"


def _pg_operator_split(run: str) -> list[str]:
    """How PostgreSQL's lexer splits a run of adjacent operator characters.

    A run is one operator, except that a trailing ``+``/``-`` is split off
    when the run has none of ``~!@#^&|`?%`` before it.
    """
    operators = []
    while run:
        size = len(run)
        if size > 1 and run[-1] in "+-" and not set(run[:-1]) & set("~!@#^&|`?%"):
            while size > 1 and run[size - 1] in "+-":
                size -= 1
        operators.append(run[:size])
        run = run[size:]
    return operators


def _check_operator_runs(tokens: list[Token]) -> None:
    """Refuse adjacent operators PostgreSQL would lex as one (``!=-``, ``<>=``)."""
    index = 0
    while index < len(tokens):
        end = index
        while (
            end + 1 < len(tokens)
            and tokens[end].token_type in _OPERATOR_TOKENS
            and tokens[end + 1].token_type in _OPERATOR_TOKENS
            and tokens[end].end + 1 == tokens[end + 1].start
        ):
            end += 1
        if end > index:
            texts = [t.text for t in tokens[index : end + 1]]
            if _pg_operator_split("".join(texts)) != texts:
                raise ValueError(_REFUSED.format("operator " + "".join(texts)))
        index = end + 1


def _token_identifier(token: Token) -> str | None:
    """Check a token other than a bracket or comma; return it if it names a column."""
    kind, spelling = token.token_type, token.text
    if kind in _OPERATOR_TOKENS:
        if spelling not in _OPERATOR_TOKENS[kind]:
            raise ValueError(_REFUSED.format(f"operator {spelling}"))
        return None
    if kind == TokenType.STRING or (
        kind == TokenType.NUMBER and _NUMBER_RE.match(spelling)
    ):
        return None
    if kind == TokenType.IDENTIFIER:
        return spelling
    if _WORD_RE.match(spelling):
        keyword = _KEYWORD_TOKENS.get(spelling.upper())
        if keyword is None:
            return spelling
        if kind == keyword:
            return None
    if kind.name.endswith("STRING") or kind == TokenType.NUMBER:
        raise ValueError(_REFUSED.format(f"literal {spelling}"))
    if any(ch.isalpha() for ch in spelling):
        raise ValueError(_SINGLE)
    raise ValueError(_REFUSED.format(f"operator {spelling}"))


def _identifier_tokens(where: str) -> list[str]:
    """Check every token against the filter language; return the identifiers."""
    try:
        tokens = Postgres().tokenize(where)
    except sqlglot.errors.TokenError as exc:
        raise ValueError(f"Invalid WHERE syntax: {exc}") from exc
    identifiers: list[str] = []
    depth = 0
    for token in tokens:
        if token.comments:
            raise ValueError(_SINGLE)
        if token.token_type == TokenType.L_PAREN:
            depth += 1
        elif token.token_type == TokenType.R_PAREN:
            depth -= 1
            if depth < 0:
                raise ValueError(_REFUSED.format("unbalanced parenthesis"))
        elif token.token_type == TokenType.SEMICOLON:
            raise ValueError(_SINGLE)
        elif token.token_type == TokenType.COMMA:
            if depth == 0:
                raise ValueError(_SINGLE)
        elif (name := _token_identifier(token)) is not None:
            identifiers.append(name)
    _check_operator_runs(tokens)
    return identifiers


def _validated_condition(where: str) -> exp.Expression:
    """Parse and validate ``where``; return its condition node.

    Raises ValueError for everything ``validate_where_ast`` documents.
    """
    if not where or not where.strip():
        raise ValueError("Empty WHERE expression")
    identifiers = _identifier_tokens(where)

    wrapped = f"SELECT 1 FROM _t WHERE {where}"
    try:
        statements = sqlglot.parse(wrapped, dialect="postgres")
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError) as exc:
        raise ValueError(f"Invalid WHERE syntax: {exc}") from exc

    statements = [s for s in statements if s is not None]

    # Multi-statement injection produces len > 1; UNION produces a Union node
    # rather than Select.
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise ValueError("Only a single WHERE expression is allowed")
    if any(
        value and name not in _WRAPPER_SELECT_ARGS
        for name, value in statements[0].args.items()
    ):
        raise ValueError("Only a single WHERE expression is allowed")

    where_node = statements[0].args.get("where")
    if where_node is None:
        raise ValueError("Empty WHERE expression")

    for node in where_node.walk():
        if not isinstance(node, ALLOWED_EXPRESSIONS):
            raise ValueError(
                f"Disallowed expression in WHERE clause: {type(node).__name__}"
            )
        # PostgreSQL refuses an unparenthesized comparison as an operand of
        # another (``a < b = c``); sqlglot would accept and group it.
        if isinstance(node, _COMPARISONS) and isinstance(node.parent, _COMPARISONS):
            raise ValueError(
                "Disallowed expression in WHERE clause: chained comparison "
                "(parenthesize each comparison)"
            )
        # PostgreSQL's lower BETWEEN bound takes no unparenthesized predicate
        # (``a BETWEEN NOT b AND c`` is a syntax error there).
        if isinstance(node, exp.Between) and not isinstance(
            node.args.get("low"), _PLAIN_OPERANDS
        ):
            raise ValueError(
                "Disallowed expression in WHERE clause: condition as a BETWEEN "
                "bound (parenthesize it)"
            )
        # Table-qualified columns (`tbl.col`, `cat.tbl.col`) are rejected even
        # though `exp.Column` is allowed: sqlglot folds table/db/catalog into
        # the Column node's args rather than a separate exp.Dot.
        if isinstance(node, exp.Column) and (
            node.args.get("table") is not None
            or node.args.get("db") is not None
            or node.args.get("catalog") is not None
        ):
            raise ValueError(
                "Disallowed expression in WHERE clause: table-qualified "
                "column reference (only unqualified column names are accepted)"
            )
    # Every word that isn't an operator must be read as a column; a word
    # sqlglot turns into something else (``ISNULL``, ``UNKNOWN``) is refused.
    columns = [c.name for c in where_node.find_all(exp.Column)]
    if sorted(columns) != sorted(identifiers):
        raise ValueError(_REFUSED.format("unsupported keyword"))
    return where_node.this


def validate_where_ast(where: str) -> None:
    """Validate that ``where`` is a safe WHERE-clause fragment.

    Raises ValueError if empty/blank, unparseable, not a single SELECT
    (multi-statement injection or UNION), followed by anything after the
    condition (ORDER BY, LIMIT and the like), a chained comparison, a
    condition as the lower BETWEEN bound, or any WHERE-subtree node isn't in
    ALLOWED_EXPRESSIONS (subqueries, function calls, DDL, etc.).

    Args:
        where: SQL WHERE-clause fragment supplied by the caller.

    Raises:
        ValueError: Description of the disallowed construct.
    """
    _validated_condition(where)


def canonical_where(where: str) -> str:
    """Validate ``where`` and return its canonical sqlglot re-render.

    For callers that interpolate the fragment into SQL text: the re-emission
    of the validated AST, never raw bytes. PostgreSQL reads the render with
    the same grouping as the original.

    Raises ValueError via validate_where_ast on any disallowed construct.
    """
    rendered = _render(where)
    # The render is run in the caller's place, so it must itself be a valid
    # filter that renders to itself.
    if _render(rendered) != rendered:
        raise ValueError(_REFUSED.format("expression the server cannot re-render"))
    return rendered


def _render(where: str) -> str:
    condition = _validated_condition(where)
    # Deepest first, so an outer NOT wraps an inner one already grouped.
    for node in reversed(list(condition.find_all(exp.Not))):
        if not isinstance(node.parent, _NOT_KEEPS_MEANING_UNDER):
            node.replace(exp.Paren(this=node.copy()))
    return condition.sql(dialect="postgres")


# Both quote kinds are scanned in one pass, because a single quote inside a
# double-quoted identifier opens no literal in Postgres and must open none here.
_QUOTED_RUN_RE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")


def mask_quoted_literals(where: str) -> str:
    """Blank every single-quoted literal in ``where``, preserving its length.

    A caller scanning for code (identifier walk, token classifier) must not
    read values as code. A double-quoted identifier is code, so it's scanned
    but returned unchanged; consuming it in the same pass stops a quote inside
    it from opening a literal that blanks real code after it.
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
