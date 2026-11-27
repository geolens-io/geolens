"""The export ``where`` filter language: a strict lexer, parser and render.

The language is one condition over a dataset's columns::

    or        := and (OR and)*
    and       := not (AND not)*
    not       := NOT not | predicate
    predicate := ( or ) | scalar [test]
    test      := cmp scalar | [NOT] IN ( scalar {, scalar} )
               | [NOT] BETWEEN scalar AND scalar | [NOT] LIKE scalar
               | IS [NOT] (NULL | TRUE | FALSE)
    scalar    := ( scalar ) | operand
    operand   := column | 'string' | number | -number | TRUE | FALSE | NULL

with cmp one of ``= <> != < <= > >=``. Anything else, and any input the
grammar doesn't consume whole, is refused. The render is built from the parse
tree, fully parenthesized and with every column double-quoted, so PostgreSQL
reads it with exactly the grouping and names the parser saw.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

_REFUSED = "Disallowed expression in WHERE clause: {}"
_SINGLE = "Only a single WHERE expression is allowed"
_SYNTAX = "Invalid WHERE syntax: {}"

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
# The render is parsed a second time by sqlglot, which runs out of Python
# stack between 20 and 30 nested negations, depending on the caller's own
# depth. Deeper nesting than this is refused.
MAX_DEPTH = 16
# A render nests at most this deep: each negation gains a parenthesis, and a
# comparison inside a conjunction gains two.
RENDER_MAX_DEPTH = 2 * MAX_DEPTH + 2

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
    """A number as PostgreSQL reads it, rendered with digits on both sides."""
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
    if i < len(text) and (_ident_char(text[i]) or text[i] == "."):
        raise ValueError(_REFUSED.format(f"number {text[start : i + 1]}"))
    if fraction is None:
        return whole, i
    return f"{whole or '0'}.{fraction or '0'}", i


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
            j = i
            while j < len(text) and text[j] in _OPERATOR_CHARS:
                j += 1
            for op in pg_operator_split(text[i:j]):
                if op not in _COMPARISONS and op != "-":
                    raise ValueError(_REFUSED.format(f"operator {op}"))
                tokens.append(_Token("op", op))
            i = j
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
    def __init__(
        self, tokens: list[_Token], columns: Sequence[str] | None, max_depth: int
    ):
        self.tokens = tokens
        self.pos = 0
        self.depth = 0
        self.max_depth = max_depth
        self.columns = columns
        # Whether the condition just parsed was a lone operand, which a
        # parenthesis may wrap on the left of a test: ``(pop) > 10``.
        self.bare = False

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
        if self.depth > self.max_depth:
            raise ValueError(_REFUSED.format("nesting too deep"))

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
        if len(parts) == 1:
            return parts[0]
        self.bare = False
        return "(" + " OR ".join(parts) + ")"

    def conjunction(self) -> str:
        parts = [self.negation()]
        while self.keyword("AND"):
            self.pos += 1
            parts.append(self.negation())
        if len(parts) == 1:
            return parts[0]
        self.bare = False
        return "(" + " AND ".join(parts) + ")"

    def negation(self) -> str:
        if self.keyword("NOT"):
            self.pos += 1
            self.nest()
            inner = self.negation()
            self.depth -= 1
            self.bare = False
            return f"(NOT {inner})"
        return self.predicate()

    def predicate(self) -> str:
        token = self.peek()
        if token is not None and token.kind == "(":
            self.pos += 1
            self.nest()
            inner = self.disjunction()
            self.depth -= 1
            self.expect(")")
            return self.test(inner) if self.bare else inner
        return self.test(self.operand())

    def scalar(self) -> str:
        """An operand, in any number of parentheses."""
        token = self.peek()
        if token is None or token.kind != "(":
            return self.operand()
        self.pos += 1
        self.nest()
        inner = self.scalar()
        self.depth -= 1
        self.expect(")")
        return inner

    def test(self, left: str) -> str:
        self.bare = False
        token = self.peek()
        if token is not None and token.kind == "op" and token.text in _COMPARISONS:
            self.pos += 1
            return f"({left} {_COMPARISONS[token.text]} {self.scalar()})"
        if self.keyword("IS"):
            self.pos += 1
            negated = "NOT " if self.keyword("NOT") else ""
            self.pos += bool(negated)
            for target in ("NULL", "TRUE", "FALSE"):
                if self.keyword(target):
                    self.pos += 1
                    return f"({left} IS {negated}{target})"
            raise ValueError(_SYNTAX.format("expected NULL, TRUE or FALSE after IS"))
        negated = "NOT " if self.keyword("NOT") else ""
        if negated and not any(self.keyword(w, 1) for w in ("IN", "BETWEEN", "LIKE")):
            raise ValueError(_SYNTAX.format("expected IN, BETWEEN or LIKE after NOT"))
        self.pos += bool(negated)
        if self.keyword("IN"):
            self.pos += 1
            self.expect("(")
            items = [self.scalar()]
            while (token := self.peek()) is not None and token.kind == ",":
                self.pos += 1
                items.append(self.scalar())
            self.expect(")")
            return f"({left} {negated}IN ({', '.join(items)}))"
        if self.keyword("BETWEEN"):
            self.pos += 1
            low = self.scalar()
            self.expect_keyword("AND")
            return f"({left} {negated}BETWEEN {low} AND {self.scalar()})"
        if self.keyword("LIKE"):
            self.pos += 1
            return f"({left} {negated}LIKE {self.scalar()})"
        self.bare = True
        return left

    def operand(self) -> str:
        token = self.take()
        if token.kind == "string":
            return "'" + token.text.replace("'", "''") + "'"
        if token.kind == "number":
            return token.text
        if token.kind == "op" and token.text == "-":
            number = self.take()
            if number.kind != "number":
                raise ValueError(_REFUSED.format("minus sign before a non-number"))
            return f"-{number.text}"
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

    def resolve(self, name: str, *, quoted: bool) -> str:
        """The dataset column ``name`` refers to, as PostgreSQL resolves it:
        an unquoted name folded to lower case, a quoted one as written."""
        target = name if quoted else _fold(name)
        if self.columns is None or target in self.columns:
            return target
        raise ValueError(f"Unknown column: {name}")


def render_filter(
    where: str, columns: Sequence[str] | None = None, max_depth: int = MAX_DEPTH
) -> str:
    """Parse ``where`` strictly and return its fully parenthesized render.

    ``columns`` are the dataset's column names; every name must resolve to
    one of them. Without them, names are kept as PostgreSQL would read them.
    Parentheses and negations may nest ``max_depth`` deep.

    Raises:
        ValueError: ``where`` is outside the filter language.
    """
    if not where or not where.strip():
        raise ValueError("Empty WHERE expression")
    return _Parser(_lex(where), columns, max_depth).parse()
