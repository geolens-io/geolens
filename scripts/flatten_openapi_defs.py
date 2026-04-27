"""Flatten OpenAPI 3.1 inline ``$defs`` blocks into top-level component refs.

Why this exists
---------------
FastAPI + pydantic v2 emit OpenAPI 3.1 schemas where each request/response
schema is a self-contained JSON Schema document. When a schema references
another model, pydantic inlines the referenced model under a local ``$defs``
block AND keeps the canonical definition under top-level
``components.schemas``. The two are byte-identical, but the inline reference
uses ``"$ref": "#/$defs/<Name>"`` (relative to the local schema) instead of
``"$ref": "#/components/schemas/<Name>"`` (absolute).

This is OpenAPI 3.1 valid, but several SDK generators trip on it:

* ``@hey-api/openapi-ts`` (TypeScript) — its ref parser crashes with
  ``TypeError: Cannot read properties of null`` because it doesn't traverse
  the nested ``$defs`` correctly.
* ``openapi-python-client`` (Python) — silently omits the affected endpoints
  with a ``Reference(ref='#/$defs/X')`` warning.

Solution: produce a generator-only intermediate file where every
``#/$defs/X`` reference is rewritten to ``#/components/schemas/X`` (when X
exists at top-level and is byte-identical), then drop the redundant
``$defs`` blocks. The committed ``backend/openapi.json`` snapshot is NEVER
modified — the flattened output is written to a separate file consumed by
the SDK generators only.

Safety
------
For every inline ``$defs.X``, the script tries (in order):

1. **Identical to top-level** — if ``components.schemas.X`` exists AND
   serializes byte-identical to the inline copy, rewrite the local
   ``#/$defs/X`` reference to ``#/components/schemas/X`` and drop the
   inline ``$defs`` block. Safe — semantics preserved exactly.

2. **Missing or different from top-level** — promote the inline schema to
   ``components.schemas`` under a deterministic synthetic name
   ``InlineDef_<X>_<sha1[:8]>`` (sha1 of the sorted-JSON serialization).
   The ``InlineDef_`` prefix avoids collision with the top-level name in
   generators that strip non-alphanumeric suffixes when emitting class
   names (e.g. openapi-python-client would otherwise emit duplicate
   ``GeoJSONFeature`` classes for inline + top-level shapes). The sha1
   suffix preserves uniqueness across genuinely-different inline copies.
   Rewrite the local ``#/$defs/X`` reference to the synthetic name and
   drop the inline ``$defs`` block.

If a synthetic-name collision occurs with an EXISTING top-level entry
that has a DIFFERENT body (extremely unlikely — sha1 collision), the
script ``sys.exit(1)`` with a clear error message.

Determinism
-----------
``json.dumps(spec, sort_keys=True, indent=2) + "\n"`` matches the format
used by ``backend/scripts/dump_openapi.py`` so the flattened intermediate
is also reproducible across machines.

Usage
-----
::

    uv run python scripts/flatten_openapi_defs.py \\
      --input backend/openapi.json \\
      --output /tmp/openapi-flat.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def _serialize(node: Any) -> str:
    """Sorted-keys JSON for byte-identical equality checks."""
    return json.dumps(node, sort_keys=True)


def _synthetic_name(base: str, schema: Any) -> str:
    """Deterministic synthetic name for a non-matching inline schema.

    Prefix ``InlineDef_`` keeps the synthetic name clear of the original
    base — important for generators (e.g. openapi-python-client) that
    strip non-alphanumeric suffixes when deriving class names; without
    the prefix, ``GeoJSONFeature`` and ``GeoJSONFeature__inline_<hash>``
    both collapse to class ``GeoJSONFeature`` and the generator errors
    on duplicate model names.

    Same shape always yields the same name, so duplicate inline copies
    fold into a single top-level entry.
    """
    digest = hashlib.sha1(_serialize(schema).encode("utf-8")).hexdigest()[:8]
    return f"InlineDef_{base}_{digest}"


def _resolve_defs_entry(
    defs_name: str,
    defs_schema: Any,
    components: dict[str, dict],
    promotions: dict[str, Any],
) -> str:
    """Decide the top-level name to use for an inline ``$defs.<name>``.

    Returns the name under which the schema lives in
    ``components.schemas`` after flattening. Promotes new schemas into
    the ``promotions`` accumulator when needed.

    Promoted schemas have their inner ``title`` field overwritten with
    the synthetic name. Some generators (e.g. openapi-python-client)
    derive class names from ``title`` rather than the schema key, so a
    promoted ``InlineDef_GeoJSONFeature_<hash>`` whose inner title still
    reads ``GeoJSONFeature`` would collide with the top-level schema's
    class. Overwriting the title gives the generator a unique name.
    """
    top = components.get(defs_name)
    if top is not None and _serialize(defs_schema) == _serialize(top):
        # Identical → reuse top-level name.
        return defs_name

    # Either missing from top-level OR shape differs → promote under
    # a deterministic synthetic name. Hash the ORIGINAL schema (before
    # title rewrite) so identical shapes still collapse to one promotion.
    synth = _synthetic_name(defs_name, defs_schema)

    # Overwrite inner title to match synthetic name (guards against
    # title-driven class-name collisions in downstream generators).
    if isinstance(defs_schema, dict) and "title" in defs_schema:
        promoted_schema = dict(defs_schema)
        promoted_schema["title"] = synth
    else:
        promoted_schema = defs_schema

    existing = components.get(synth) or promotions.get(synth)
    if existing is not None and _serialize(existing) != _serialize(promoted_schema):
        sys.stderr.write(
            f"ERROR: synthetic name '{synth}' collides with an existing "
            "schema of different shape. Refusing to overwrite.\n"
        )
        sys.exit(1)

    promotions[synth] = promoted_schema
    return synth


def _walk(
    node: Any,
    components: dict[str, dict],
    promotions: dict[str, Any],
    rename_stack: list[dict[str, str]],
) -> tuple[Any, int, int]:
    """Recursively rewrite ``#/$defs/X`` refs and remove inline ``$defs``.

    ``rename_stack`` carries the active scope: each ``$defs`` block we
    enter pushes a name-mapping frame onto the stack so descendants can
    rewrite ``#/$defs/X`` to the resolved top-level name. On the way out
    we pop the frame.

    Returns ``(new_node, refs_rewritten, defs_removed)``.
    """
    refs_rewritten = 0
    defs_removed = 0

    if isinstance(node, dict):
        # Detect ref objects: {"$ref": "#/$defs/Name"} → rewrite in place
        # using the most recently pushed (innermost) scope that knows
        # about Name.
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref[len("#/$defs/") :]
            target = None
            for frame in reversed(rename_stack):
                if name in frame:
                    target = frame[name]
                    break
            if target is None:
                sys.stderr.write(
                    f"ERROR: orphaned inline reference '#/$defs/{name}' "
                    "has no enclosing $defs scope. Input may be malformed.\n"
                )
                sys.exit(1)
            new_node = dict(node)
            new_node["$ref"] = f"#/components/schemas/{target}"
            return new_node, 1, 0

        # If this dict carries a $defs block, resolve every entry first
        # so descendants see the right name mapping. Then drop the block.
        new_dict: dict[str, Any] = {}
        local_frame: dict[str, str] = {}
        defs_block = node.get("$defs")
        if isinstance(defs_block, dict):
            for defs_name, defs_schema in defs_block.items():
                # Recurse into the schema body FIRST so any nested
                # $defs/$refs inside it are resolved. We do this before
                # pushing the local frame because the schema body must
                # see its OWN sibling defs.
                pass  # handled below
            # Two-pass resolution:
            # Pass 1: tentatively bind names so siblings can refer to
            # each other in any order.
            for defs_name, defs_schema in defs_block.items():
                # Resolve will be re-run after recursion; this initial
                # call seeds the rename frame.
                local_frame[defs_name] = _resolve_defs_entry(
                    defs_name, defs_schema, components, promotions
                )
            rename_stack.append(local_frame)
            # Pass 2: recurse into each defs schema (descendants now see
            # the local frame); promotions get overwritten with the
            # rewritten body.
            for defs_name, defs_schema in defs_block.items():
                rewritten_body, sub_rw, sub_rm = _walk(
                    defs_schema, components, promotions, rename_stack
                )
                target_name = local_frame[defs_name]
                # Update the promoted body if it lives in promotions
                # (don't touch existing top-level components.schemas to
                # preserve invariant: top-level is source-of-truth).
                #
                # Preserve the title-rewrite that Pass 1 applied (Pass 2
                # recursed the original schema, which has the original
                # title; without this branch we'd revert the synthetic
                # title that protects against generator class-name
                # collisions — see _resolve_defs_entry).
                if target_name in promotions:
                    if (
                        isinstance(rewritten_body, dict)
                        and "title" in rewritten_body
                        and target_name.startswith("InlineDef_")
                    ):
                        rewritten_body = dict(rewritten_body)
                        rewritten_body["title"] = target_name
                    promotions[target_name] = rewritten_body
                refs_rewritten += sub_rw
                defs_removed += sub_rm
            defs_removed += 1
            # Walk the rest of this dict (with the local frame still on
            # the stack) so siblings of $defs that reference the names
            # resolve correctly.
            for key, value in node.items():
                if key == "$defs":
                    continue
                new_value, sub_rw, sub_rm = _walk(
                    value, components, promotions, rename_stack
                )
                new_dict[key] = new_value
                refs_rewritten += sub_rw
                defs_removed += sub_rm
            rename_stack.pop()
            return new_dict, refs_rewritten, defs_removed

        # No $defs at this level — just recurse normally.
        for key, value in node.items():
            new_value, sub_rw, sub_rm = _walk(
                value, components, promotions, rename_stack
            )
            new_dict[key] = new_value
            refs_rewritten += sub_rw
            defs_removed += sub_rm
        return new_dict, refs_rewritten, defs_removed

    if isinstance(node, list):
        new_list: list[Any] = []
        for item in node:
            new_item, sub_rw, sub_rm = _walk(
                item, components, promotions, rename_stack
            )
            new_list.append(new_item)
            refs_rewritten += sub_rw
            defs_removed += sub_rm
        return new_list, refs_rewritten, defs_removed

    return node, 0, 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to source OpenAPI JSON (e.g. backend/openapi.json).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write flattened intermediate (e.g. /tmp/openapi-flat.json).",
    )
    args = parser.parse_args()

    if not args.input.exists():
        sys.stderr.write(f"ERROR: input {args.input} does not exist.\n")
        return 1

    spec = json.loads(args.input.read_text())
    components = spec.get("components", {}).get("schemas", {})
    if not isinstance(components, dict):
        sys.stderr.write(
            "ERROR: input has no components.schemas mapping. "
            "Not a valid OpenAPI 3.x document.\n"
        )
        return 1

    promotions: dict[str, Any] = {}
    flattened, refs_rewritten, defs_removed = _walk(
        spec, components, promotions, rename_stack=[]
    )

    # Merge promotions into components.schemas. Promotions never
    # overwrite existing entries — that's enforced by _resolve_defs_entry.
    if promotions:
        flat_components = flattened["components"]["schemas"]
        for name, schema in promotions.items():
            if name in flat_components:
                # Already there with same body (verified earlier); no-op.
                continue
            flat_components[name] = schema

    # Same serialization style as dump_openapi.py.
    output_text = json.dumps(flattened, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output_text)

    print(
        f"Flattened {args.input} → {args.output}: "
        f"{refs_rewritten} ref(s) rewritten, "
        f"{defs_removed} inline $defs block(s) removed, "
        f"{len(promotions)} schema(s) promoted to components.schemas"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
