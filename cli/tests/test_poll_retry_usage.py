# SPDX-License-Identifier: Apache-2.0
"""fix(#1778 review round 8): structural gate — every --wait poll loop in
this package must call call_sdk() with reraise_timeout=True (routed through
_sdk_helpers.poll_until), not the plain default that treats a per-request
httpx.TimeoutException as immediately fatal.

wait_for_refresh() (refresh.py) still called plain call_sdk() with no
reraise_timeout, so one slow status GET made `geolens refresh --wait` exit
EXIT_NETWORK immediately even with the operation's own deadline nowhere
near reached (or, for the default unbounded --wait, with no deadline at
all). resolve_dataset_id() (publish.py, shared by `publish --wait` and
`analysis materialize --wait`) was fixed for this in round 7.

Uses ``ast`` rather than a bare text grep so a match inside a comment or a
docstring (this module's own docstring included) cannot produce a false
positive or negative.
"""
from __future__ import annotations

import ast
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "geolens_cli"

#: Every function in this package that runs a `--wait`-style poll loop
#: (a `while` around a job-status GET). New poll loops must be added here
#: — the point of this gate is that a NEW one can't quietly skip the
#: retry path.
POLL_LOOP_FUNCTIONS: dict[str, str] = {
    "publish.py": "resolve_dataset_id",
    "refresh.py": "wait_for_refresh",
}


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no top-level `def {name}` found")


def _call_sdk_calls(node: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "call_sdk"
        ):
            calls.append(child)
    return calls


def _has_reraise_timeout_true(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "reraise_timeout":
            return isinstance(kw.value, ast.Constant) and kw.value.value is True
    return False


def test_every_poll_loop_calls_call_sdk_with_reraise_timeout() -> None:
    offenders: list[str] = []
    total_calls = 0

    for filename, function_name in POLL_LOOP_FUNCTIONS.items():
        path = _PACKAGE_DIR / filename
        tree = ast.parse(path.read_text(), filename=str(path))
        fn = _find_function(tree, function_name)
        calls = _call_sdk_calls(fn)
        assert calls, (
            f"{filename}::{function_name} no longer calls call_sdk() at "
            "all — update POLL_LOOP_FUNCTIONS or this gate is checking "
            "nothing."
        )
        total_calls += len(calls)
        for call in calls:
            if not _has_reraise_timeout_true(call):
                offenders.append(f"{filename}:{call.lineno}")

    assert offenders == [], (
        "A --wait poll loop calls call_sdk() without reraise_timeout=True "
        f"at: {offenders}. A per-request timeout there is immediately "
        "fatal (EXIT_NETWORK) even when the operation's own deadline "
        "still has time left — route it through _sdk_helpers.poll_until "
        "instead."
    )
    # Positive control: if this drops to 0, the AST walk (or every
    # registered poll loop) broke silently and the assertion above would
    # pass vacuously.
    assert total_calls >= len(POLL_LOOP_FUNCTIONS)
