# SPDX-License-Identifier: Apache-2.0
"""fix(#1778 review round 2): structural gate — every construction of the
SDK's generated ``GeolensClient`` in this package must go through
``_sdk_helpers.make_client()``, the single point that binds the request to
``DEFAULT_HTTP_TIMEOUT_SECONDS``. Before this gate, AppState.sdk(),
auth.try_refresh(), and call_sdk_with_reauth's retry client had each been
given the timeout bound independently (or, in the interactive login flow's
case, missed it entirely) — a new call site had nothing to stop it from
shipping unbounded.

This walks the package source with ``ast`` rather than a bare text grep so
a match inside a comment or a docstring (this module's own docstring
included) cannot produce a false positive or a false negative.
"""
from __future__ import annotations

import ast
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "geolens_cli"


def _find_geolens_client_calls(tree: ast.AST) -> list[ast.Call]:
    """Return every ``Call`` node whose callee is named ``GeolensClient``."""
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == "GeolensClient":
            calls.append(node)
    return calls


def _make_client_line_range(tree: ast.AST) -> tuple[int, int]:
    """Return the (start, end) source line range of ``def make_client``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "make_client":
            assert node.end_lineno is not None
            return node.lineno, node.end_lineno
    raise AssertionError("_sdk_helpers.py has no top-level `def make_client`")


def test_every_geolensclient_construction_is_inside_make_client() -> None:
    sdk_helpers_path = _PACKAGE_DIR / "_sdk_helpers.py"
    sdk_helpers_tree = ast.parse(sdk_helpers_path.read_text(), filename=str(sdk_helpers_path))
    make_client_start, make_client_end = _make_client_line_range(sdk_helpers_tree)

    offenders: list[str] = []
    total_calls = 0

    for path in sorted(_PACKAGE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for call in _find_geolens_client_calls(tree):
            total_calls += 1
            in_make_client = (
                path == sdk_helpers_path
                and make_client_start <= call.lineno <= make_client_end
            )
            if not in_make_client:
                offenders.append(f"{path.relative_to(_PACKAGE_DIR.parent)}:{call.lineno}")

    assert offenders == [], (
        "GeolensClient(...) constructed outside _sdk_helpers.make_client(): "
        f"{offenders}. Route it through make_client() so the request is "
        "bound to DEFAULT_HTTP_TIMEOUT_SECONDS."
    )
    # Positive control: if this drops to 0, the AST walk (or make_client
    # itself) broke silently and the assertion above would pass vacuously.
    assert total_calls >= 1
