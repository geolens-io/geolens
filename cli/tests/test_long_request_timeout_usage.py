# SPDX-License-Identifier: Apache-2.0
"""fix(#1778 review round 6): structural gate — every call to a generated
SDK function the backend documents as long-running before it responds must
be made inside a ``with long_request_timeout(client):`` block.

Round 5's structural gate keyed on ``files=`` (a multipart body), which
missed the ingest/reupload preview requests: they carry no file, but the
backend runs a synchronous ``run_ogrinfo_preview()`` probe bounded by
``OGRINFO_TIMEOUT_SECONDS = 300`` before responding
(backend/app/processing/ingest/ogr.py). The correct classification is
"the backend documents this as long-running", not "this request has a
body" — carrying a file was only ever one way a request earns that.

This test has two parts:

1. Every name in ``_sdk_helpers.LONG_RUNNING_SDK_FUNCTIONS`` is resolved
   against the INSTALLED ``geolens`` SDK package — a rename on either side
   (this registry, or the generated module/attribute) fails loudly here
   instead of silently letting a call site drop out of coverage.
2. Every call site in ``cli/geolens_cli/`` that references one of those
   functions (``<alias>.sync_detailed``, matched by resolving the local
   import alias back to its origin module) is checked for
   ``with long_request_timeout(...):`` nesting via ``ast`` — not a text
   grep, so a comment or docstring mention can't produce a false result.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

from geolens_cli._sdk_helpers import LONG_RUNNING_SDK_FUNCTIONS

_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "geolens_cli"


def test_registry_resolves_against_the_installed_sdk() -> None:
    """A rename of the module or the attribute in the generated SDK must
    fail this test, not silently stop being checked."""
    assert LONG_RUNNING_SDK_FUNCTIONS, "registry must not be empty"
    for display_name, (module_path, attr) in LONG_RUNNING_SDK_FUNCTIONS.items():
        module = importlib.import_module(module_path)
        assert hasattr(module, attr), (
            f"{display_name}: {module_path}.{attr} no longer exists — "
            "update LONG_RUNNING_SDK_FUNCTIONS in _sdk_helpers.py (and "
            "check whether the call site that used it still needs "
            "long_request_timeout)."
        )


def _is_long_request_timeout_call(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "long_request_timeout"
    )


def _import_aliases(tree: ast.AST) -> dict[str, tuple[str, str]]:
    """Map local alias -> (module, original_name) for every
    `from module import original_name [as alias]` anywhere in the file
    (including inside function bodies — this codebase imports lazily)."""
    aliases: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for imp in node.names:
                local_name = imp.asname or imp.name
                aliases[local_name] = (node.module, imp.name)
    return aliases


class _LongRunningCallVisitor(ast.NodeVisitor):
    """Walks a module tracking `with long_request_timeout(...):` nesting
    depth, recording every reference to a registered long-running SDK
    function's `.sync_detailed` attribute made outside that depth."""

    def __init__(self, path: Path, aliases: dict[str, tuple[str, str]]) -> None:
        self.path = path
        self.aliases = aliases
        self._depth = 0
        self.unwrapped: list[str] = []
        self.match_count = 0

    def visit_With(self, node: ast.With) -> None:
        is_wrapped = any(
            _is_long_request_timeout_call(item.context_expr) for item in node.items
        )
        if is_wrapped:
            self._depth += 1
        self.generic_visit(node)
        if is_wrapped:
            self._depth -= 1

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name):
            origin = self.aliases.get(node.value.id)
            if origin is not None:
                # `from <module> import <name> [as alias]` — the SDK
                # function's own module path is `<module>.<name>` (the
                # generated package has one module per endpoint).
                full_module = f"{origin[0]}.{origin[1]}"
                for module_path, attr in LONG_RUNNING_SDK_FUNCTIONS.values():
                    if full_module == module_path and node.attr == attr:
                        self.match_count += 1
                        if self._depth == 0:
                            self.unwrapped.append(f"{self.path.name}:{node.lineno}")
        self.generic_visit(node)


def test_every_long_running_call_is_inside_long_request_timeout() -> None:
    offenders: list[str] = []
    total_matches = 0

    for path in sorted(_PACKAGE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        aliases = _import_aliases(tree)
        visitor = _LongRunningCallVisitor(path, aliases)
        visitor.visit(tree)
        offenders.extend(visitor.unwrapped)
        total_matches += visitor.match_count

    assert offenders == [], (
        "A call to a registered long-running SDK function is not wrapped "
        f"in `with long_request_timeout(client):` at: {offenders}. The "
        "backend can take up to its documented deadline (e.g. 300s for "
        "the ogrinfo preview probe) to respond."
    )
    # Positive control: if this drops to 0, the AST walk (or every
    # registered call site) broke silently and the assertion above would
    # pass vacuously.
    assert total_matches >= len(LONG_RUNNING_SDK_FUNCTIONS)
