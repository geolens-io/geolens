# SPDX-License-Identifier: Apache-2.0
"""fix(#1778 review round 5): structural gate — every CLI request that
carries a file body (a ``files=`` / multipart POST) must be made inside a
``with upload_timeout(client):`` block. Before this fix, each such call
site open-coded its own save/override/restore of the client's httpx
timeout (or, in replace.py's case, never did — it just inherited
AppState.sdk()'s plain 30s default), so a large file could time out on
the backend's save-and-validate response. Routing every one through
``_sdk_helpers.upload_timeout()`` closes the class: a new call site with
this shape has nowhere else to get its extended timeout from.

Uses ``ast`` rather than a bare text grep so a match inside a comment or
a docstring (this module's own docstring included) cannot produce a
false positive or negative, and so nesting is checked precisely rather
than by proximity.
"""
from __future__ import annotations

import ast
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "geolens_cli"


def _is_upload_timeout_call(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "upload_timeout"
    )


class _FilesCallVisitor(ast.NodeVisitor):
    """Walks a module tracking `with upload_timeout(...):` nesting depth,
    and records every `files=` call made outside that depth."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._upload_timeout_depth = 0
        self.unwrapped_files_calls: list[str] = []
        self.files_call_count = 0

    def visit_With(self, node: ast.With) -> None:
        is_upload_timeout = any(
            _is_upload_timeout_call(item.context_expr) for item in node.items
        )
        if is_upload_timeout:
            self._upload_timeout_depth += 1
        self.generic_visit(node)
        if is_upload_timeout:
            self._upload_timeout_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        has_files_kwarg = any(kw.arg == "files" for kw in node.keywords)
        if has_files_kwarg:
            self.files_call_count += 1
            if self._upload_timeout_depth == 0:
                self.unwrapped_files_calls.append(f"{self.path.name}:{node.lineno}")
        self.generic_visit(node)


def test_every_files_kwarg_call_is_inside_upload_timeout() -> None:
    offenders: list[str] = []
    total_files_calls = 0

    for path in sorted(_PACKAGE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        visitor = _FilesCallVisitor(path)
        visitor.visit(tree)
        offenders.extend(visitor.unwrapped_files_calls)
        total_files_calls += visitor.files_call_count

    assert offenders == [], (
        "A files=/multipart POST is not wrapped in "
        f"`with upload_timeout(client):` at: {offenders}. Large file "
        "uploads can outlast AppState.sdk()'s plain 30s default."
    )
    # Positive control: if this drops to 0, the AST walk (or every
    # multipart call site) broke silently and the assertion above would
    # pass vacuously.
    assert total_files_calls >= 1
