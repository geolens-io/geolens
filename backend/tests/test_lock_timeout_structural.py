"""Only catalog_locks.py names lock_timeout in code; the listed modules are the shrink-only exceptions."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
_LOCKS_MODULE = "app.platform.catalog_locks"

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


def _reaches_private_lock_helper(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module == _LOCKS_MODULE:
            if any(alias.name.startswith("_") for alias in node.names):
                return True
        if (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("_")
            and isinstance(node.value, ast.Name)
            and node.value.id == "catalog_locks"
        ):
            return True
    return False


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
        "from app.platform import catalog_locks\ncatalog_locks._set_lock_timeout(s, v)",
    ],
)
def test_private_helper_scan_catches_both_spellings(source: str) -> None:
    """Importing or reaching a private catalog_locks helper by attribute trips the scan."""
    assert _reaches_private_lock_helper(source)


@pytest.mark.architecture
def test_no_module_reaches_a_private_lock_helper() -> None:
    """No module calls catalog_locks' private timeout setters, which would bypass the scan."""
    found = sorted(
        name
        for name, source in _modules().items()
        if _reaches_private_lock_helper(source)
    )
    assert not found, f"import a public catalog_locks helper instead: {found}"
