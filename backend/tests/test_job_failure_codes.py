"""Every fixed job failure reason carries a stable code with a frontend translation.

``FixedReason`` (``app/core/failure_reason.py``) requires a ``code`` keyword.
This gate discovers every code from its call sites via AST, not a fixed
list, and cross-checks each one against ``failure-reason.ts``'s
``FIXED_FAILURE_CODE_KEYS`` table and all five locale bundles.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

_LOCALES = ("en", "es", "fr", "de", "zh")


def _discover_repo_roots() -> tuple[Path, Path]:
    """Return (repo_root, backend_root) for host and backend-container layouts."""
    test_file = Path(__file__).resolve()
    for candidate in test_file.parents:
        if (candidate / "backend/app").is_dir():
            return candidate, candidate / "backend"
        if (candidate / "app").is_dir() and (candidate / "tests").is_dir():
            return candidate.parent, candidate
    return test_file.parents[2], test_file.parents[1]


REPO_ROOT, BACKEND_ROOT = _discover_repo_roots()
FRONTEND_ROOT = REPO_ROOT / "frontend"


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _kwarg(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Every ``NAME = "literal"`` assignment in the file, by name.

    Resolves a ``FixedReason(..., code=SOME_CODE)`` call whose code names a
    constant defined elsewhere in the same file (``platform/refresh/service.py``)
    instead of repeating the literal at the call site.
    """
    constants: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            constants[node.targets[0].id] = node.value.value
    return constants


def _as_str(value: ast.expr | None, constants: dict[str, str]) -> str | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    if isinstance(value, ast.Name):
        return constants.get(value.id)
    return None


def _fixed_reason_codes(path: Path) -> tuple[set[str], list[str]]:
    """Codes minted in one file, and any ``FixedReason(...)`` with no discoverable code."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    constants = _module_string_constants(tree)
    codes: set[str] = set()
    missing: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node.func) != "FixedReason":
            continue
        code = _as_str(_kwarg(node, "code"), constants)
        if code is not None:
            codes.add(code)
        else:
            missing.append(
                f"{path}:{node.lineno} FixedReason(...) has no discoverable code="
            )
    return codes, missing


def fixed_reason_registry() -> tuple[set[str], list[str]]:
    """Every stable code a ``FixedReason`` carries under backend/app, and any
    mint site with no discoverable code."""
    codes: set[str] = set()
    missing: list[str] = []
    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        file_codes, file_missing = _fixed_reason_codes(path)
        codes |= file_codes
        missing.extend(file_missing)
    return codes, missing


def test_every_fixed_reason_has_a_code():
    """A FixedReason minted with no discoverable code fails here.

    Counterfactual: drop the `code=` keyword, or point it at a name this
    file never assigns a string literal to, on any mint site and this test
    fails.
    """
    _, missing = fixed_reason_registry()
    assert not missing, "FixedReasons with no stable code:\n" + "\n".join(missing)


_FAILURE_REASON_TS = FRONTEND_ROOT / "src" / "lib" / "failure-reason.ts"


def _frontend_code_keys() -> dict[str, str]:
    """Parse ``FIXED_FAILURE_CODE_KEYS`` out of failure-reason.ts.

    A regex over the table's own flat `code: 'errors.x',` shape, not a
    TypeScript parse -- fine for a table this test also owns the shape of.
    ``[^=]*`` skips the type annotation up to the assignment: the table's
    ``Record<string, `errors.${string}`>`` embeds a brace of its own, which
    would stop a scan for the object literal's opening ``{`` too early.
    """
    source = _FAILURE_REASON_TS.read_text(encoding="utf-8")
    match = re.search(
        r"FIXED_FAILURE_CODE_KEYS[^=]*=\s*\{(?P<body>.*?)\n\};", source, re.DOTALL
    )
    assert match, (
        "FIXED_FAILURE_CODE_KEYS table not found in frontend/src/lib/failure-reason.ts"
    )
    return dict(re.findall(r"(\w+):\s*'(errors\.[\w.]+)'", match.group("body")))


def test_every_fixed_reason_code_has_a_frontend_mapping():
    """A registry code with no frontend mapping, or a mapping with no
    matching registry code, fails here -- checked in both directions.

    Counterfactuals: delete an entry from `FIXED_FAILURE_CODE_KEYS` for a
    code still minted in `backend/app`, or mint a new `FixedReason` code with
    no matching entry -- either fails.
    """
    codes, _ = fixed_reason_registry()
    code_keys = _frontend_code_keys()

    unmapped = sorted(codes - code_keys.keys())
    assert not unmapped, (
        "FixedReason codes with no FIXED_FAILURE_CODE_KEYS entry in "
        f"frontend/src/lib/failure-reason.ts: {unmapped}"
    )

    stale = sorted(code_keys.keys() - codes)
    assert not stale, (
        f"FIXED_FAILURE_CODE_KEYS entries with no matching FixedReason code: {stale}"
    )


def test_every_fixed_failure_key_exists_in_every_locale():
    """A mapped key missing from any of the five locale bundles fails here.

    Counterfactual: delete a `FIXED_FAILURE_CODE_KEYS` key from any one
    locale's `common.json` and this test fails.
    """
    code_keys = _frontend_code_keys()
    missing_keys: list[str] = []
    for locale in _LOCALES:
        bundle_path = (
            FRONTEND_ROOT / "src" / "i18n" / "locales" / locale / "common.json"
        )
        errors = json.loads(bundle_path.read_text(encoding="utf-8"))["errors"]
        for code, key in code_keys.items():
            if key.removeprefix("errors.") not in errors:
                missing_keys.append(f"{locale}: {code} -> {key}")
    assert not missing_keys, (
        f"FIXED_FAILURE_CODE_KEYS entries with no locale key: {missing_keys}"
    )
