"""Shared MapLibre filter-expression validator/normalizer.

builder-audit P1-04: a single source of truth for the editable subset of
MapLibre expression-form layer filters. Backend layer schemas, the
style-export/import path, and the AI ``set_filter`` validation all call
``validate_filter`` so a filter that is accepted, stored, exported, and
replayed cannot diverge between those boundaries.

Contract
--------
``validate_filter(value)`` returns a normalized filter (or ``None``) and:

* accepts ``None`` and the empty array ``[]`` as *clear the filter* (returns
  ``None`` — matches the frontend EDIT-03 behavior where ``map.setFilter(id, [])``
  throws);
* accepts and normalizes the editable expression subset the builder UI emits
  (see ``frontend/src/components/builder/LayerFilterEditor.tsx``):
  ``==``, ``!=``, ``<``, ``>``, ``<=``, ``>=``, ``in`` / contains, ``has``,
  ``!``, ``all`` / ``any``, and ``to-number``-wrapped numeric comparisons;
* normalizes the deprecated MapLibre *legacy filter* bare-field comparison
  form ``[op, "field", value]`` into expression form
  ``[op, ["get", "field"], value]``;
* rejects malformed *recognized* forms — wrong arity on a comparison/``!``/
  ``has``, a non-string operator, a non-array filter, or a legacy bare-field
  ``in`` form;
* EXPLICITLY PRESERVES opaque, structurally-valid filters that use operators
  outside the editable subset (``match``, ``step``, ``case``, ``coalesce``,
  ``geometry-type``, ``$type``/``$id`` legacy pseudo-fields, ...) verbatim,
  without crashing — so power users and importers keep working.

Callers that prefer to *drop* an invalid filter rather than surface a 422 (the
AI path) can catch ``FilterValidationError``.
"""

from __future__ import annotations

from typing import Any

# Editable comparison operators the structured builder editor can round-trip.
_COMPARISON_OPERATORS = {"==", "!=", "<", ">", "<=", ">="}
# Boolean combinators.
_COMBINATORS = {"all", "any"}
# Legacy MapLibre feature-filter pseudo-fields resolved by the renderer itself,
# NOT read from feature properties — they must NOT be rewritten to ["get", ...].
_LEGACY_PSEUDO_FIELDS = {"$type", "$id"}


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


def validate_filter(value: list | None) -> list | None:
    """Validate + normalize a MapLibre layer filter (builder-audit P1-04).

    ``None`` and ``[]`` both clear the filter (return ``None``). A recognized
    form with invalid arity raises ``FilterValidationError``; opaque
    unsupported filters are preserved verbatim.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise FilterValidationError("filter must be a JSON array or null")
    if len(value) == 0:
        # EDIT-03: an empty array is not a valid MapLibre filter; treat as clear.
        return None
    return _normalize_node(value)
