# SPDX-License-Identifier: Apache-2.0
"""fix(#1778 review round 4): structural gate — `login` must never call
delete_credentials() directly. delete_credentials() removes every stored
credential unconditionally; calling it before storing the replacement (the
bug this fix addresses) left a user logged out if the store then failed.
Every login branch must go through auth.replace_credentials() instead,
which stores the new credential first and only evicts the competing kinds
once that succeeds.

Uses ``ast`` rather than a bare text grep so a match inside a comment or a
docstring (this module's own docstring, or main.py's comments explaining
the history, included) cannot produce a false positive or negative.
"""
from __future__ import annotations

import ast
from pathlib import Path

_MAIN_PY = Path(__file__).resolve().parent.parent / "geolens_cli" / "main.py"


def _login_function_body() -> ast.FunctionDef:
    tree = ast.parse(_MAIN_PY.read_text(), filename=str(_MAIN_PY))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "login":
            return node
    raise AssertionError("main.py has no top-level `def login`")


def _attribute_calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    """Return every ``Call`` node of the shape ``<anything>.<name>(...)``."""
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == name
        ):
            calls.append(node)
    return calls


def test_login_never_calls_delete_credentials_directly() -> None:
    login_fn = _login_function_body()
    offenders = _attribute_calls_named(login_fn, "delete_credentials")
    assert offenders == [], (
        "login() must not call delete_credentials() directly — it deletes "
        "unconditionally, before any replacement is confirmed stored. Use "
        "auth.replace_credentials(instance, kind, value) instead, at "
        f"line(s): {[c.lineno for c in offenders]}"
    )


def test_login_uses_replace_credentials_for_every_branch() -> None:
    """Positive control for the assertion above: if replace_credentials()
    stopped being called at all (e.g. the whole flow was rewritten), the
    negative assertion would pass vacuously. There are three login
    branches (--api-key, --token, interactive), so three calls."""
    login_fn = _login_function_body()
    calls = _attribute_calls_named(login_fn, "replace_credentials")
    assert len(calls) == 3, (
        f"expected 3 replace_credentials() calls (one per login branch), "
        f"found {len(calls)} at line(s): {[c.lineno for c in calls]}"
    )
