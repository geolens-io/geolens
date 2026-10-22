"""ArcGIS ``definitionExpression`` (a SQL WHERE clause) to a MapLibre filter.

Only comparisons, ``IN``, ``IS [NOT] NULL`` and ``AND``/``OR``/``NOT`` over
plain field names and literals convert. Anything else (functions, ``LIKE``,
subqueries, field-to-field comparisons) returns None so the caller records a
loss instead of applying a partial filter.
"""

from __future__ import annotations

import math

_OPS = {"=": "==", "<>": "!=", "!=": "!="}
_COMPARISONS = {"==", "!=", "<", ">", "<=", ">="}
_MAX_DEPTH = 16
_MAX_TOKENS = 2000
_DIGITS = frozenset("0123456789")
_WORD_START = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_")
_WORD_BODY = _WORD_START | _DIGITS | {"."}
_TWO_CHAR_OPS = ("<>", "!=", "<=", ">=")


class _Unsupported(Exception):
    pass


def _digits_end(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in _DIGITS:
        pos += 1
    return pos


def _scan_string(text: str, pos: int) -> int:
    """End of the quoted string starting at ``pos``; ``''`` is an escaped quote."""
    pos += 1
    while True:
        close = text.find("'", pos)
        if close < 0:
            raise _Unsupported
        if text[close + 1 : close + 2] != "'":
            return close + 1
        pos = close + 2


def _scan_number(text: str, pos: int) -> int | None:
    """End of a number at ``pos`` (optional sign, ``1``, ``1.``, ``1.5``, ``.5``, exponent)."""
    start = pos + 1 if text[pos] in "+-" else pos
    i = _digits_end(text, start)
    has_digits = i > start
    if text[i : i + 1] == ".":
        end = _digits_end(text, i + 1)
        if has_digits or end > i + 1:
            has_digits = True
            i = end
    if not has_digits:
        return None
    if text[i : i + 1] in ("e", "E"):
        j = i + 1
        if text[j : j + 1] in ("+", "-"):
            j += 1
        end = _digits_end(text, j)
        if end > j:
            i = end
    return i


def _is_integer(value: str) -> bool:
    body = value[1:] if value[:1] in ("+", "-") else value
    return bool(body) and all(char in _DIGITS for char in body)


def _scan_quoted_id(text: str, pos: int, closer: str) -> int:
    close = text.find(closer, pos + 1)
    if close <= pos + 1:
        raise _Unsupported
    return close + 1


def _next_token(text: str, pos: int) -> tuple[tuple[str, str], int]:
    """One token from ``pos`` (whitespace already skipped), by direct character scans."""
    char = text[pos]
    if char == "'":
        end = _scan_string(text, pos)
        return ("str", text[pos:end]), end
    if char in _DIGITS or char in "+-.":
        end = _scan_number(text, pos)
        if end is None:
            raise _Unsupported
        return ("num", text[pos:end]), end
    if text[pos : pos + 2] in _TWO_CHAR_OPS:
        return ("op", text[pos : pos + 2]), pos + 2
    if char in "=<>":
        return ("op", char), pos + 1
    if char in "(),":
        return ("punct", char), pos + 1
    if char == '"' or char == "[":
        end = _scan_quoted_id(text, pos, '"' if char == '"' else "]")
        return ("qid", text[pos:end]), end
    if char in _WORD_START:
        end = pos + 1
        while end < len(text) and text[end] in _WORD_BODY:
            end += 1
        return ("word", text[pos:end]), end
    raise _Unsupported


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            return tokens
        token, pos = _next_token(text, pos)
        tokens.append(token)
        if len(tokens) > _MAX_TOKENS:
            raise _Unsupported


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.pos = 0
        # Guarded negations, by node id, to the positive form that undoes them.
        self._positive: dict[int, tuple[list, list]] = {}

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
            return self._negate(self._not(depth + 1))
        return self._primary(depth)

    def _negate(self, node: list) -> list:
        """SQL ``NOT``: a NULL operand stays unknown, so the row stays hidden.

        MapLibre's ``!=`` and ``!`` are true for a missing property, so a
        negated comparison gets a non-null guard. Only a single comparison or
        ``IN`` negates this way; a compound expression has no faithful
        guard and is left to the caller as a loss.
        """
        if id(node) in self._positive:
            return self._positive[id(node)][1]
        op = node[0]
        if op in _COMPARISONS and node[2] is None:
            return ["!=" if op == "==" else "==", node[1], None]
        if op in _COMPARISONS or op == "in":
            return self._guarded(node[1], ["!", node], node)
        raise _Unsupported

    def _guarded(self, field: list, negated: list, positive: list) -> list:
        node = ["all", ["!=", field, None], negated]
        self._positive[id(node)] = (node, positive)
        return node

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
            if _is_integer(value):
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
            return self._negate(node) if negate else node
        if negate:
            raise _Unsupported
        kind, op = self._next()
        if kind != "op":
            raise _Unsupported
        node = [_OPS.get(op, op), field, self._literal()]
        if node[0] == "!=":
            return self._guarded(field, node, ["==", field, node[2]])
        return node


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
    return "".join(expression.split()) in {"", "1=1"}
