"""Shared MapLibre filter-expression validator/normalizer.

Single source of truth (builder-audit #338 P1-04) for the editable subset
of MapLibre expression-form layer filters, shared by layer schemas, style
export/import, and the AI ``set_filter`` path.

``validate_filter(value)``: ``None``/``[]`` clear the filter; the editable
subset (comparisons, ``in``/``has``, ``!``, ``all``/``any``, legacy
bare-field rewritten to expression form) is normalized; malformed
recognized forms raise; anything outside the subset (``match``, ``case``,
...) is preserved verbatim. Catch ``FilterValidationError`` to drop an
invalid filter instead of a 422 (the AI path).
"""

from __future__ import annotations

from typing import Any

# Editable comparison operators the structured builder editor can round-trip.
_COMPARISON_OPERATORS = {"==", "!=", "<", ">", "<=", ">="}
_COMBINATORS = {"all", "any"}
# Legacy MapLibre feature-filter pseudo-fields resolved by the renderer itself,
# NOT read from feature properties — they must NOT be rewritten to ["get", ...].
_LEGACY_PSEUDO_FIELDS = {"$type", "$id"}
# fix(#1778): real filters nest single digits (`all`/`!` cost one level each);
# past this, `_normalize_node`/`json.dumps` recursion raises RecursionError
# (not ValueError), which Pydantic can't turn into a 422.
_MAX_FILTER_DEPTH = 32


class FilterValidationError(ValueError):
    """Raised when a filter uses a recognized form with invalid shape/arity.

    Subclasses ``ValueError`` so a Pydantic ``field_validator`` converts it
    into a 422 at the API boundary automatically.
    """


def _is_get(node: Any) -> bool:
    """True for a ``["get", field, ...]`` property-accessor expression.

    Note: a ``to-number``-wrapped numeric comparison (``["to-number",
    ["get", field], fallback]``) is accepted implicitly — the comparison
    handler treats any list operand as a valid expression-form operand.
    """
    return isinstance(node, list) and len(node) >= 2 and node[0] == "get"


def _normalize_node(node: Any) -> list:
    """Validate and normalize one filter expression node.

    Returns the (possibly normalized) node. Raises ``FilterValidationError``
    on a malformed recognized form. Opaque/unknown operators are preserved.
    """
    if not isinstance(node, list):
        raise FilterValidationError(
            f"filter expression must be a JSON array, got {type(node).__name__}"
        )
    if not node:
        raise FilterValidationError("filter expression must not be an empty array")

    op = node[0]
    if not isinstance(op, str):
        raise FilterValidationError(
            "filter expression operator (first element) must be a string"
        )

    if op in _COMBINATORS:
        # all/any take any number of sub-filters; recurse into array children
        # and preserve the rare non-array operand (e.g. a literal boolean).
        normalized: list = [op]
        for child in node[1:]:
            if isinstance(child, list):
                normalized.append(_normalize_node(child))
            else:
                normalized.append(child)
        return normalized

    if op == "!":
        if len(node) != 2:
            raise FilterValidationError(
                "'!' filter takes exactly one operand: ['!', <expression>]"
            )
        inner = node[1]
        if isinstance(inner, list):
            return ["!", _normalize_node(inner)]
        return node

    if op == "has":
        if len(node) != 2 or not isinstance(node[1], str):
            raise FilterValidationError(
                "'has' filter takes a single field name: ['has', <field>]"
            )
        return node

    if op == "in":
        # in_list:  ["in", ["get", field], ["literal", [...]]]
        # contains: ["in", <scalar>, ["get", field]]
        if (
            len(node) == 3
            and _is_get(node[1])
            and isinstance(node[2], list)
            and node[2]
            and node[2][0] == "literal"
        ):
            return node
        if len(node) == 3 and _is_get(node[2]):
            return node
        # Legacy bare-field "in" (["in", "field", v0, v1, ...]) is rejected with
        # guidance; an expression-operand "in" we don't recognize is opaque.
        if len(node) >= 2 and isinstance(node[1], str):
            raise FilterValidationError(
                "legacy 'in' filter form is not supported; use "
                "['in', ['get', <field>], ['literal', [...]]]"
            )
        return node

    if op in _COMPARISON_OPERATORS:
        if len(node) != 3:
            raise FilterValidationError(
                f"comparison filter '{op}' takes exactly two operands: "
                f"['{op}', <field-expression>, <value>]"
            )
        operand = node[1]
        if isinstance(operand, list):
            # ["get", field], ["to-number", ["get", field], ...], or any other
            # MapLibre expression operand — all valid expression-form operands.
            return node
        if isinstance(operand, str):
            if operand in _LEGACY_PSEUDO_FIELDS:
                # $type / $id legacy pseudo-fields — preserve verbatim.
                return node
            # Legacy bare-field comparison — normalize to expression form.
            return [op, ["get", operand], node[2]]
        # Scalar/literal first operand — opaque, preserve.
        return node

    # Unknown / unsupported operator (match, step, case, coalesce, interpolate,
    # geometry-type, ...) — explicitly PRESERVE the opaque filter, do not crash.
    return node


def _assert_depth_within_bound(value: Any) -> None:
    """Raise ``FilterValidationError`` past ``_MAX_FILTER_DEPTH`` array levels.

    Iterative on purpose: a recursive check blows the recursion limit on
    exactly the input it exists to refuse. Walks dicts too — below the
    operator a filter is arbitrary JSON that the size cap's ``json.dumps``
    recurses through, opaque operators included (``_normalize_node``
    doesn't recurse into them, but ``json.dumps`` still does).
    """
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, list):
            children: list[Any] = node
        elif isinstance(node, dict):
            children = list(node.values())
        else:
            continue
        if depth >= _MAX_FILTER_DEPTH:
            raise FilterValidationError(
                f"filter expression nests deeper than {_MAX_FILTER_DEPTH} levels"
            )
        stack.extend((child, depth + 1) for child in children)


def validate_filter(value: list | None) -> list | None:
    """Validate + normalize a MapLibre layer filter (builder-audit #338 P1-04).

    ``None``/``[]`` clear the filter. A recognized form with invalid arity
    raises ``FilterValidationError``; opaque forms pass through verbatim.
    A filter nested past ``_MAX_FILTER_DEPTH`` also raises it, so every
    caller gets a 422 (or a dropped action, on the AI path) instead of the
    RecursionError this walk used to produce.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise FilterValidationError("filter must be a JSON array or null")
    if len(value) == 0:
        # EDIT-03: an empty array is not a valid MapLibre filter; treat as clear.
        return None
    _assert_depth_within_bound(value)
    return _normalize_node(value)
