"""The export ``where`` filter language: a strict lexer, parser and render.

The language is one condition over a dataset's columns::

    or        := and (OR and)*
    and       := not (AND not)*
    not       := NOT not | predicate
    predicate := compared [IS [NOT] (NULL | TRUE | FALSE)]
    compared  := ranged [cmp ranged]
    ranged    := primary [ [NOT] IN ( or {, or} )
                         | [NOT] BETWEEN primary AND primary
                         | [NOT] (LIKE | ILIKE) primary ]
    primary   := ( or ) | operand
    operand   := column | 'string' | [+ | -] number | [+ | -] ( number )
               | TRUE | FALSE | NULL

with cmp one of ``= <> != < <= > >=``. Anything else, and any input the
grammar doesn't consume whole, is refused. The render is built from the parse
tree, fully parenthesized and with every column double-quoted, so PostgreSQL
reads it with exactly the grouping and names the parser saw. The levels are
PostgreSQL's precedence: ``IN``, ``BETWEEN`` and ``LIKE`` bind tighter than a
comparison, and ``IS`` applies to the whole comparison before it. Rendering a
render returns it unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

_REFUSED = "Disallowed expression in WHERE clause: {}"
_SINGLE = "Only a single WHERE expression is allowed"
_SYNTAX = "Invalid WHERE syntax: {}"
_TOO_DEEP = _REFUSED.format("nesting too deep")

# PostgreSQL's scanner: these are its only whitespace characters, and an
# identifier starts with an ASCII letter, ``_`` or any non-ASCII character and
# continues with those, ASCII digits and ``$``. So a no-break space or a
# combining mark is part of the name, as PostgreSQL reads it.
_WHITESPACE = frozenset(" \t\n\r\f\v")


def _ident_start(ch: str) -> bool:
    return not ch.isascii() or ch.isalpha() or ch == "_"


def _ident_char(ch: str) -> bool:
    return _ident_start(ch) or ("0" <= ch <= "9") or ch == "$"


# PostgreSQL's operator characters; a run of them is lexed as one operator.
_OPERATOR_CHARS = frozenset("~!@#^&|`?+-*/%<>=")
# With one of these in a run, PostgreSQL keeps a trailing ``+`` or ``-``.
_KEEPS_TRAILING_SIGN = frozenset("~!@#^&|`?%")
# Each comparison spelling and the operator the render writes for it.
_COMPARISONS = {
    "=": "=",
    "<>": "<>",
    "!=": "<>",
    "<": "<",
    "<=": "<=",
    ">": ">",
    ">=": ">=",
}
# How deep a render's parentheses may nest. The render is parsed a second time
# by sqlglot, which runs out of Python stack between 20 and 30 nested
# negations, depending on the caller's own depth.
MAX_RENDER_DEPTH = 16
# How deep the input's parentheses and negations may nest together. A render
# has at most one negation per parenthesis, so every render fits.
_MAX_INPUT_NESTING = 2 * MAX_RENDER_DEPTH
# The longest run of operator characters that can be valid: ``<>-``.
_MAX_OPERATOR_RUN = 3
# Enough for any double precision value, and far inside what numeric holds.
_MAX_EXPONENT_DIGITS = 3

# The tests NOT may precede.
_NEGATABLE = ("IN", "BETWEEN", "LIKE", "ILIKE")

# PostgreSQL 18's reserved and type/function-name keywords
# (pg_get_keywords() catcode R and T). Unquoted, PostgreSQL refuses each as a
# column reference or reads it as something else (``user`` is the current
# role), so only the quoted form names a column. Its other keywords work as
# column names.
_RESERVED_WORDS = frozenset(
    """
    all analyse analyze and any array as asc asymmetric both case cast check
    collate column constraint create current_catalog current_date current_role
    current_time current_timestamp current_user default deferrable desc
    distinct do else end except false fetch for foreign from grant group having
    in initially intersect into lateral leading limit localtime localtimestamp
    not null offset on only or order placing primary references returning
    select session_user some symmetric system_user table then to trailing true
    union unique user using variadic when where window with
    authorization binary collation concurrently cross current_schema freeze
    full ilike inner is isnull join left like natural notnull outer overlaps
    right similar tablesample verbose
    """.split()
)


@dataclass(frozen=True)
class _Token:
    kind: str  # word, ident, string, number, op, (, ), ","
    text: str


def pg_operator_split(run: str) -> list[str]:
    """How PostgreSQL's lexer splits a run of operator characters.

    A run is one operator, except that trailing ``+``/``-`` characters are
    each split off when the run has none of ``~!@#^&|`?%``.
    """
    if _KEEPS_TRAILING_SIGN.intersection(run):
        return [run]
    head = run.rstrip("+-") or run[0]
    return [head, *run[len(head) :]]


def _read_quoted(text: str, start: int, quote: str) -> tuple[str, int]:
    """The unescaped content of a quoted run at ``start``; doubling escapes."""
    value: list[str] = []
    i = start + 1
    while i < len(text):
        if text[i] == quote:
            if i + 1 < len(text) and text[i + 1] == quote:
                value.append(quote)
                i += 2
                continue
            return "".join(value), i + 1
        value.append(text[i])
        i += 1
    raise ValueError(_SYNTAX.format("unterminated quote"))


def _read_number(text: str, start: int) -> tuple[str, int]:
    """A number as PostgreSQL reads it, rendered with a digit before any point.

    A bare trailing point becomes ``.0`` so the value stays numeric, except
    before an exponent, where the point goes: the value is numeric either way
    and keeps its scale.
    """
    i = start
    while i < len(text) and text[i].isascii() and text[i].isdigit():
        i += 1
    whole = text[start:i]
    fraction = None
    if i < len(text) and text[i] == ".":
        j = i + 1
        while j < len(text) and text[j].isascii() and text[j].isdigit():
            j += 1
        fraction, i = text[i + 1 : j], j
    exponent = ""
    if i < len(text) and text[i] in "eE":
        j = i + 2 if text[i + 1 : i + 2] in ("+", "-") else i + 1
        k = j
        while k < len(text) and text[k].isascii() and text[k].isdigit():
            k += 1
        if k - j > _MAX_EXPONENT_DIGITS:
            raise ValueError(_REFUSED.format("number with an exponent too large"))
        if k > j:
            exponent, i = "e" + text[i + 1 : k], k
    if i < len(text) and (_ident_char(text[i]) or text[i] == "."):
        raise ValueError(_REFUSED.format(f"number {text[start : i + 1]}"))
    if fraction is None or (exponent and not fraction):
        return whole + exponent, i
    return f"{whole or '0'}.{fraction or '0'}{exponent}", i


def _read_operators(text: str, start: int) -> tuple[list[_Token], int]:
    """The supported operators in the run of operator characters at ``start``."""
    end = start
    while end < len(text) and text[end] in _OPERATOR_CHARS:
        end += 1
    if end - start > _MAX_OPERATOR_RUN:
        run = text[start : start + _MAX_OPERATOR_RUN]
        raise ValueError(_REFUSED.format(f"operator {run}..."))
    operators = pg_operator_split(text[start:end])
    for op in operators:
        if op not in _COMPARISONS and op not in ("+", "-"):
            raise ValueError(_REFUSED.format(f"operator {op}"))
    return [_Token("op", op) for op in operators], end


def _lex(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in _WHITESPACE:
            i += 1
        elif ch in "(),":
            tokens.append(_Token(ch, ch))
            i += 1
        elif ch == "'":
            value, i = _read_quoted(text, i, "'")
            tokens.append(_Token("string", value))
        elif ch == '"':
            value, i = _read_quoted(text, i, '"')
            if not value:
                raise ValueError(_SYNTAX.format("empty quoted identifier"))
            tokens.append(_Token("ident", value))
        elif (ch.isascii() and ch.isdigit()) or (
            ch == "." and text[i + 1 : i + 2].isdigit()
        ):
            value, i = _read_number(text, i)
            tokens.append(_Token("number", value))
        elif _ident_start(ch):
            j = i + 1
            while j < len(text) and _ident_char(text[j]):
                j += 1
            tokens.append(_Token("word", text[i:j]))
            i = j
        elif ch in _OPERATOR_CHARS:
            operators, i = _read_operators(text, i)
            tokens.extend(operators)
        elif ch == ";":
            raise ValueError(_SINGLE)
        else:
            raise ValueError(_REFUSED.format(f"character {ch!r}"))
    return tokens


def _fold(word: str) -> str:
    """An unquoted identifier as PostgreSQL folds it: ASCII letters lowered."""
    return "".join(c.lower() if "A" <= c <= "Z" else c for c in word)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class _Parser:
    def __init__(self, tokens: list[_Token], columns: Sequence[str] | None):
        self.tokens = tokens
        self.pos = 0
        self.depth = 0
        self.columns = None if columns is None else frozenset(columns)

    def peek(self, offset: int = 0) -> _Token | None:
        index = self.pos + offset
        return self.tokens[index] if index < len(self.tokens) else None

    def keyword(self, word: str, offset: int = 0) -> bool:
        token = self.peek(offset)
        # Folded as PostgreSQL folds it: ``ıs`` upper-cases to IS in Unicode,
        # but PostgreSQL reads it as a name.
        return (
            token is not None
            and token.kind == "word"
            and _fold(token.text) == word.lower()
        )

    def take(self) -> _Token:
        token = self.peek()
        if token is None:
            raise ValueError(_SYNTAX.format("unexpected end of condition"))
        self.pos += 1
        return token

    def expect_keyword(self, word: str) -> None:
        if not self.keyword(word):
            raise ValueError(_SYNTAX.format(f"expected {word}"))
        self.pos += 1

    def expect(self, kind: str) -> None:
        token = self.take()
        if token.kind != kind:
            raise ValueError(_SYNTAX.format(f"expected {kind!r}"))

    def nest(self) -> None:
        self.depth += 1
        if self.depth > _MAX_INPUT_NESTING:
            raise ValueError(_TOO_DEEP)

    def parse(self) -> str:
        if not self.tokens:
            raise ValueError("Empty WHERE expression")
        rendered = self.disjunction()
        if self.peek() is not None:
            raise ValueError(_SINGLE)
        return rendered

    def disjunction(self) -> str:
        parts = [self.conjunction()]
        while self.keyword("OR"):
            self.pos += 1
            parts.append(self.conjunction())
        return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"

    def conjunction(self) -> str:
        parts = [self.negation()]
        while self.keyword("AND"):
            self.pos += 1
            parts.append(self.negation())
        return parts[0] if len(parts) == 1 else "(" + " AND ".join(parts) + ")"

    def negation(self) -> str:
        if self.keyword("NOT"):
            self.pos += 1
            self.nest()
            inner = self.negation()
            self.depth -= 1
            return f"(NOT {inner})"
        tested = self.compared()
        if not self.keyword("IS"):
            return tested
        self.pos += 1
        negated = "NOT " if self.keyword("NOT") else ""
        self.pos += bool(negated)
        for target in ("NULL", "TRUE", "FALSE"):
            if self.keyword(target):
                self.pos += 1
                return f"({tested} IS {negated}{target})"
        raise ValueError(_SYNTAX.format("expected NULL, TRUE or FALSE after IS"))

    def primary(self) -> str:
        """An operand, or a whole condition in parentheses.

        A condition's render carries its own parentheses, so it stays one
        operand wherever it is used.
        """
        token = self.peek()
        if token is None or token.kind != "(":
            return self.operand()
        self.pos += 1
        self.nest()
        inner = self.disjunction()
        self.depth -= 1
        self.expect(")")
        return inner

    def compared(self) -> str:
        left = self.ranged()
        token = self.peek()
        if token is None or token.kind != "op" or token.text not in _COMPARISONS:
            return left
        self.pos += 1
        return f"({left} {_COMPARISONS[token.text]} {self.ranged()})"

    def ranged(self) -> str:
        left = self.primary()
        negated = "NOT " if self.keyword("NOT") else ""
        if negated and not any(self.keyword(w, 1) for w in _NEGATABLE):
            raise ValueError(_SYNTAX.format("expected IN, BETWEEN or LIKE after NOT"))
        self.pos += bool(negated)
        if self.keyword("IN"):
            self.pos += 1
            self.expect("(")
            self.nest()
            items = [self.disjunction()]
            while (token := self.peek()) is not None and token.kind == ",":
                self.pos += 1
                items.append(self.disjunction())
            self.depth -= 1
            self.expect(")")
            return f"({left} {negated}IN ({', '.join(items)}))"
        if self.keyword("BETWEEN"):
            self.pos += 1
            low = self.primary()
            self.expect_keyword("AND")
            return f"({left} {negated}BETWEEN {low} AND {self.primary()})"
        for pattern in ("LIKE", "ILIKE"):
            if self.keyword(pattern):
                self.pos += 1
                return f"({left} {negated}{pattern} {self.primary()})"
        return left

    def operand(self) -> str:
        token = self.take()
        if token.kind == "string":
            return "'" + token.text.replace("'", "''") + "'"
        if token.kind == "number":
            return token.text
        if token.kind == "op" and token.text in ("+", "-"):
            sign = "-" if token.text == "-" else ""
            return sign + self.signed_number()
        if token.kind == "ident":
            return _quote(self.resolve(token.text, quoted=True))
        if token.kind == "word":
            folded = _fold(token.text)
            if folded in ("true", "false", "null"):
                return folded.upper()
            following = self.peek()
            if following is not None and following.kind == "(":
                raise ValueError(_REFUSED.format("function call"))
            if folded in _RESERVED_WORDS:
                raise ValueError(_REFUSED.format(token.text))
            return _quote(self.resolve(token.text, quoted=False))
        raise ValueError(_SYNTAX.format(f"unexpected {token.text!r}"))

    def signed_number(self) -> str:
        """The number after a sign, in any number of parentheses."""
        token = self.take()
        if token.kind == "number":
            return token.text
        if token.kind != "(":
            raise ValueError(_REFUSED.format("sign before a non-number"))
        self.nest()
        number = self.signed_number()
        self.depth -= 1
        self.expect(")")
        return number

    def resolve(self, name: str, *, quoted: bool) -> str:
        """The dataset column ``name`` refers to, as PostgreSQL resolves it:
        an unquoted name folded to lower case, a quoted one as written."""
        target = name if quoted else _fold(name)
        if self.columns is None or target in self.columns:
            return target
        raise ValueError(f"Unknown column: {name}")


def _paren_depth(tokens: list[_Token]) -> int:
    depth = deepest = 0
    for token in tokens:
        if token.kind == "(":
            depth += 1
            deepest = max(deepest, depth)
        elif token.kind == ")":
            depth -= 1
    return deepest


def render_filter(where: str, columns: Sequence[str] | None = None) -> str:
    """Parse ``where`` strictly and return its fully parenthesized render.

    ``columns`` are the dataset's column names; every name must resolve to
    one of them. Without them, names are kept as PostgreSQL would read them.
    The render's parentheses nest at most ``MAX_RENDER_DEPTH`` deep.

    Raises:
        ValueError: ``where`` is outside the filter language.
    """
    if not where or not where.strip():
        raise ValueError("Empty WHERE expression")
    # PostgreSQL takes no NUL in a query, quoted or not.
    if "\x00" in where:
        raise ValueError(_REFUSED.format("NUL character"))
    rendered = _Parser(_lex(where), columns).parse()
    if _paren_depth(_lex(rendered)) > MAX_RENDER_DEPTH:
        raise ValueError(_TOO_DEEP)
    return rendered
