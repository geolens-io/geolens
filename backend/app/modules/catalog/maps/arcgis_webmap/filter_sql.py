"""ArcGIS ``definitionExpression`` (a SQL WHERE clause) to a MapLibre filter.

Only comparisons, ``IN``, ``IS [NOT] NULL`` and ``AND``/``OR``/``NOT`` over
plain field names and literals convert. Anything else (functions, ``LIKE``,
subqueries, field-to-field comparisons) returns None so the caller records a
loss instead of applying a partial filter.
"""

from __future__ import annotations

import math
import re

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<str>'(?:[^']|'')*')
      | (?P<num>[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
      | (?P<op><>|!=|<=|>=|=|<|>)
      | (?P<punct>[(),])
      | (?P<qid>"[^"]+"|\[[^\]]+\])
      | (?P<word>[A-Za-z_][A-Za-z0-9_.]*)
    )""",
    re.VERBOSE,
)
_OPS = {"=": "==", "<>": "!=", "!=": "!="}
_MAX_DEPTH = 16
_MAX_TOKENS = 2000


class _Unsupported(Exception):
    pass


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            raise _Unsupported
        pos = match.end()
        kind = match.lastgroup or ""
        tokens.append((kind, match.group(kind)))
        if len(tokens) > _MAX_TOKENS:
            raise _Unsupported
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> tuple[str, str]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ("end", "")

    def _next(self) -> tuple[str, str]:
        token = self._peek()
        self.pos += 1
        return token

    def _keyword(self, *words: str) -> bool:
        kind, value = self._peek()
        if kind == "word" and value.upper() in words:
            self.pos += 1
            return True
        return False

    def parse(self) -> list:
        node = self._or(0)
        if self._peek()[0] != "end":
            raise _Unsupported
        return node

    def _or(self, depth: int) -> list:
        parts = [self._and(depth)]
        while self._keyword("OR"):
            parts.append(self._and(depth))
        return parts[0] if len(parts) == 1 else ["any", *parts]

    def _and(self, depth: int) -> list:
        parts = [self._not(depth)]
        while self._keyword("AND"):
            parts.append(self._not(depth))
        return parts[0] if len(parts) == 1 else ["all", *parts]

    def _not(self, depth: int) -> list:
        if self._keyword("NOT"):
            if depth > _MAX_DEPTH:
                raise _Unsupported
            return ["!", self._not(depth + 1)]
        return self._primary(depth)

    def _primary(self, depth: int) -> list:
        if depth > _MAX_DEPTH:
            raise _Unsupported
        if self._peek() == ("punct", "("):
            self._next()
            node = self._or(depth + 1)
            if self._next() != ("punct", ")"):
                raise _Unsupported
            return node
        return self._comparison()

    def _field(self) -> list:
        kind, value = self._next()
        if kind == "qid":
            return ["get", value[1:-1]]
        if kind == "word" and value.upper() not in {
            "AND",
            "OR",
            "NOT",
            "NULL",
            "IN",
            "IS",
            "LIKE",
            "BETWEEN",
            "SELECT",
        }:
            return ["get", value]
        raise _Unsupported

    def _literal(self) -> str | float | int:
        kind, value = self._next()
        if kind == "str":
            return value[1:-1].replace("''", "'")
        if kind == "num":
            if re.fullmatch(r"[+-]?\d+", value):
                return int(value)
            number = float(value)
            if not math.isfinite(number):
                raise _Unsupported
            return number
        raise _Unsupported

    def _comparison(self) -> list:
        field = self._field()
        if self._keyword("IS"):
            negate = self._keyword("NOT")
            if not self._keyword("NULL"):
                raise _Unsupported
            return ["!=" if negate else "==", field, None]
        negate = self._keyword("NOT")
        if self._keyword("IN"):
            if self._next() != ("punct", "("):
                raise _Unsupported
            values = [self._literal()]
            while self._peek() == ("punct", ","):
                self._next()
                values.append(self._literal())
            if self._next() != ("punct", ")"):
                raise _Unsupported
            node = ["in", field, ["literal", values]]
            return ["!", node] if negate else node
        if negate:
            raise _Unsupported
        kind, op = self._next()
        if kind != "op":
            raise _Unsupported
        return [_OPS.get(op, op), field, self._literal()]


def definition_expression_to_filter(expression: str) -> list | None:
    """The MapLibre filter for ``expression``, or None when it can't be expressed.

    ``1=1`` and blank expressions select everything and also return None; use
    ``is_match_all`` to tell them from an unsupported expression.
    """
    try:
        return _Parser(_tokenize(expression)).parse()
    except (_Unsupported, IndexError, ValueError):
        return None


def is_match_all(expression: str) -> bool:
    return re.sub(r"\s+", "", expression) in {"", "1=1"}
