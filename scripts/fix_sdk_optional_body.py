#!/usr/bin/env python3
"""Guard the generated Python SDK's optional-request-body emission.

fix(#1277 review). openapi-python-client emits this for an endpoint whose
request body is optional::

    def _get_kwargs(..., body: Foo | None | Unset = UNSET) -> dict[str, Any]:
        ...
        if isinstance(body, Foo):
            _kwargs["json"] = body.to_dict()
        else:
            _kwargs["json"] = body

The ``else`` is correct for ``body=None`` — that is a caller explicitly asking
to send JSON ``null`` — and wrong for the default. ``UNSET`` is a sentinel
object, not data, so calling the method the documented way (omit the body
entirely) hands ``json=UNSET`` to httpx, which raises ``TypeError`` while
serializing and never sends the request. Every optional-body endpoint in the
SDK is unusable at its own default.

This rewrites that one ``else`` into ``elif not isinstance(body, Unset)``, so
an omitted body sets no ``json`` key at all and httpx sends no payload. An
explicit ``None`` still serializes to ``null``, which keeps the one behaviour
the ``else`` got right.

### Why this runs in the pipeline instead of being a patch to the output

Generated files are overwritten on every ``make sdks``, so a fix applied to
them is a fix that lasts until the next regen — and this class of defect (a
convention that is correct on one side of a boundary and wrong on the other)
is exactly the kind that comes back silently. Running here makes the corrected
form the only form the tree ever holds.

Overriding the generator's Jinja template was the alternative and is worse: it
means vendoring an upstream template and re-reconciling it on every
openapi-python-client bump, to change two lines.

The script fails loudly rather than silently no-opping. If a module takes an
optional body and this transform leaves an unguarded assignment behind, the
generator's emission has changed shape and the guard needs rewriting — which
is a thing to be told about at build time, not to discover from a TypeError in
somebody's client.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1] / "sdks/python/geolens/api"

# A body parameter that can arrive as the UNSET sentinel.
_OPTIONAL_BODY = re.compile(r"^\s*body:\s.*\bUnset\b\s*=\s*UNSET\s*,?\s*$", re.MULTILINE)

# The unguarded fallback, captured with its indentation so the replacement
# lands at the same depth. Matches both shapes the generator emits: the model
# branch (`body.to_dict()`) and the bare-collection branch, which differ only
# in the blank line the formatter leaves before the `else`.
_UNGUARDED_ELSE = re.compile(
    r"^(?P<indent>[ ]+)else:\n(?P=indent)[ ]{4}_kwargs\[\"json\"\] = body$",
    re.MULTILINE,
)


def _guard(source: str) -> tuple[str, int]:
    """Return (rewritten source, replacements made)."""

    def _replace(match: re.Match[str]) -> str:
        indent = match.group("indent")
        return (
            f"{indent}elif not isinstance(body, Unset):\n"
            f'{indent}    _kwargs["json"] = body'
        )

    return _UNGUARDED_ELSE.subn(_replace, source)


def main() -> int:
    if not _API_ROOT.is_dir():
        print(f"ERROR: generated SDK not found at {_API_ROOT}", file=sys.stderr)
        return 1

    patched: list[str] = []
    unfixed: list[str] = []

    for path in sorted(_API_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if not _OPTIONAL_BODY.search(source):
            continue
        rewritten, count = _guard(source)
        if count:
            path.write_text(rewritten, encoding="utf-8")
            patched.append(f"{path.relative_to(_API_ROOT.parents[2])} ({count})")
        if _UNGUARDED_ELSE.search(rewritten):
            unfixed.append(str(path.relative_to(_API_ROOT.parents[2])))

    if unfixed:
        print(
            "ERROR: optional-body endpoints still assign the UNSET sentinel to "
            "`json` after the guard ran. openapi-python-client's emission has "
            "changed shape; update scripts/fix_sdk_optional_body.py.\n  "
            + "\n  ".join(unfixed),
            file=sys.stderr,
        )
        return 1

    if patched:
        print(f"Guarded optional request bodies in {len(patched)} module(s):")
        for entry in patched:
            print(f"  {entry}")
    else:
        print("No optional-body endpoints needed guarding.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
