"""Standards-layer import guard: ``backend/app/standards/`` may not reach into
``app.processing.*``.

``test_layering.py::test_no_catalog_imports_processing`` holds
``backend/app/modules/catalog/`` to a strict zero on ``app.processing``
references, and catalog pays a real ergonomic cost to honor it (see the
comment at ``catalog/sources/preview.py``). ``standards/`` was never held to
the same rule, so the STAC router welded catalog ORM to processing ORM in one
module — the backend's largest router acting as an unguarded bridge between
two domains that are otherwise kept apart. A rename in
``processing/raster/models.py`` broke STAC output with no layering signal.

The rule is the same one catalog follows: processing-owned ORM classes,
queries, and helpers are reached through ``CatalogPort``
(``app.core.catalog_port``), whose community implementation defers every
``app.processing`` import into a method body.

This walks the AST rather than grepping, for two reasons: an import is a
syntactic fact and a comment mentioning the module name is not one, and
``git grep`` is blind to files that are not yet tracked. Both module-scope
and function-scope imports count — a deferred import inside a function is the
exact shape this guard exists to catch.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
STANDARDS_ROOT = BACKEND_ROOT / "app" / "standards"

# Both spellings resolve to the same package; the second is how the repo is
# imported when `backend/` itself is on the path.
_BANNED_ROOTS = ("app.processing", "backend.app.processing")


def _is_banned(module: str | None) -> bool:
    if not module:
        return False
    return any(
        module == root or module.startswith(f"{root}.") for root in _BANNED_ROOTS
    )


def _absolute_module(path: Path, node: ast.ImportFrom) -> str | None:
    """Resolve ``node``'s target to a dotted module name.

    A relative import states its target as a hop count plus a suffix, so
    ``from ...processing.raster.models import RasterAsset`` inside
    ``app/standards/stac/`` names the banned package without spelling it.
    Resolve against the file's own package so the guard reads the target, not
    the syntax used to write it.
    """
    if node.level == 0:
        return node.module

    package = path.parent.relative_to(BACKEND_ROOT).parts
    # level 1 is the containing package, level 2 its parent, and so on.
    trimmed = package[: len(package) - (node.level - 1)]
    if not trimmed:
        # Climbs past the `app` package root — not a resolvable target.
        return None
    parts = [*trimmed, *(node.module.split(".") if node.module else [])]
    return ".".join(parts)


def _processing_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    rel = path.relative_to(BACKEND_ROOT.parent)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_banned(alias.name):
                    offenders.append(f"{rel}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = _absolute_module(path, node)
            if _is_banned(module):
                names = ", ".join(alias.name for alias in node.names)
                offenders.append(f"{rel}:{node.lineno}: from {module} import {names}")
    return offenders


@pytest.mark.architecture
def test_standards_does_not_import_processing() -> None:
    """No module under ``app/standards/`` imports ``app.processing`` at any scope."""
    offenders: list[str] = []
    for path in sorted(STANDARDS_ROOT.rglob("*.py")):
        offenders.extend(_processing_imports(path))

    assert not offenders, (
        "backend/app/standards/ imports app.processing directly. Processing-owned "
        "ORM classes, queries, and helpers must be reached through CatalogPort "
        "(app.core.catalog_port) — get_catalog_port().raster_asset_orm_class() for "
        "query construction, or a port read method for a whole answer. This is the "
        "rule backend/app/modules/catalog/ already follows "
        "(test_layering.py::test_no_catalog_imports_processing). Offending "
        "imports:\n" + "\n".join(offenders)
    )
