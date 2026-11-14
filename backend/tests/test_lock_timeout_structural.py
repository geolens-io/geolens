"""Only catalog_locks.py names lock_timeout in code; the listed modules are the shrink-only exceptions."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

# Any string the code builds that names the setting: SET, set_config, RESET,
# current_setting, or a key or argument passed to something that sets it.
_NAMES_SETTING = re.compile(r"\block_timeout\b", re.IGNORECASE)

# Job, ingest and tenant machinery that sets its own budget; remove entries as
# they move onto the shared helpers, never add one.
_ALLOWED = {
    "core/db/tenant_adoption_sql.py",
    "modules/catalog/datasets/domain/relationship_columns.py",
    "platform/jobs/attempt_tables.py",
    "platform/jobs/heartbeat.py",
    "platform/jobs/ledger.py",
    "processing/ingest/publication.py",
    "processing/ingest/tasks_common.py",
    "processing/ingest/tasks_postgis_refresh.py",
    "processing/ingest/tasks_vrt.py",
}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, owners) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def _names_lock_timeout(source: str) -> bool:
    """True when a string literal outside a docstring, f-string parts included, names the setting."""
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and _NAMES_SETTING.search(node.value)
        for node in ast.walk(tree)
    )


def _private_lock_names() -> frozenset[str]:
    """Every private top-level name catalog_locks.py defines."""
    tree = ast.parse((APP / "platform" / "catalog_locks.py").read_text("utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(t.id for t in targets if isinstance(t, ast.Name))
    return frozenset(name for name in names if name.startswith("_"))


def _reaches_private_lock_helper(source: str, private: frozenset[str]) -> bool:
    """True for a private catalog_locks import, or any mention of one of its
    private names as an identifier, attribute, import alias or exact string,
    whatever module spelling reached it."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.rsplit(".", 1)[-1] == "catalog_locks" and any(
                alias.name.startswith("_") for alias in node.names
            ):
                return True
        if _mentioned_names(node) & private:
            return True
    return False


def _mentioned_names(node: ast.AST) -> set[object]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.alias):
        return {node.name, node.asname}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    return set()


def _modules() -> dict[str, str]:
    return {
        path.relative_to(APP).as_posix(): path.read_text(encoding="utf-8")
        for path in APP.rglob("*.py")
        if path.name != "catalog_locks.py"
    }


def _files_naming_lock_timeout() -> set[str]:
    return {name for name, source in _modules().items() if _names_lock_timeout(source)}


@pytest.mark.parametrize(
    "source",
    [
        "text(\"SELECT set_config('lock_timeout', :v, true)\")",
        "text(f\"SET LOCAL lock_timeout = '{budget}'\")",
        "text('RESET lock_timeout')",
        "params = {'name': 'lock_timeout', 'value': '5s'}",
        "GUC = 'Lock_Timeout'",
    ],
)
def test_scanner_catches_each_spelling(source: str) -> None:
    """The scan trips on SQL, f-string, renamed-argument and constant spellings of the setting."""
    assert _names_lock_timeout(source)


def test_scanner_ignores_comments_and_docstrings() -> None:
    """A comment or docstring that mentions the setting sets nothing and does not trip the scan."""
    source = '"""Waits under lock_timeout."""\n# SET LOCAL lock_timeout\nx = 1\n'
    assert not _names_lock_timeout(source)


@pytest.mark.architecture
def test_no_new_module_sets_lock_timeout_by_hand() -> None:
    """A module outside the allowlist that names lock_timeout in code fails; use bounded_row_lock."""
    found = _files_naming_lock_timeout()
    assert found <= _ALLOWED, f"set lock_timeout by hand: {sorted(found - _ALLOWED)}"


@pytest.mark.architecture
def test_lock_timeout_allowlist_has_no_stale_entries() -> None:
    """An allowlisted module that no longer names lock_timeout is removed from the list."""
    stale = _ALLOWED - _files_naming_lock_timeout()
    assert not stale, f"drop from the allowlist: {sorted(stale)}"


@pytest.mark.parametrize(
    "source",
    [
        "from app.platform.catalog_locks import _set_lock_timeout",
        "from app.platform.catalog_locks import _set_lock_timeout as bound",
        "from .catalog_locks import _install_lock_timeout",
        "from app.platform import catalog_locks\ncatalog_locks._set_lock_timeout(s, v)",
        "import app.platform.catalog_locks as cl\ncl._set_lock_timeout(s, v)",
        "import app.platform.catalog_locks\napp.platform.catalog_locks._set_lock_timeout(s, v)",
        "import importlib\ngetattr(importlib.import_module(m), '_set_lock_timeout')",
    ],
)
def test_private_helper_scan_catches_each_spelling(source: str) -> None:
    """Importing a private catalog_locks name, or naming one through any alias, attribute path or string, trips the scan."""
    assert _reaches_private_lock_helper(source, _private_lock_names())


def test_private_names_include_the_timeout_setters() -> None:
    """The backstop's name list is read from catalog_locks.py and covers its timeout setters."""
    assert {"_set_lock_timeout", "_install_lock_timeout"} <= _private_lock_names()


@pytest.mark.architecture
def test_no_module_reaches_a_private_lock_helper() -> None:
    """No module outside catalog_locks.py names its private timeout setters, which would bypass the scan."""
    private = _private_lock_names()
    found = sorted(
        name
        for name, source in _modules().items()
        if _reaches_private_lock_helper(source, private)
    )
    assert not found, f"use a public catalog_locks helper instead: {found}"
