"""Only catalog_locks.py sets lock_timeout for a request-path row lock; the listed modules are the shrink-only exceptions."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
_HAND_ROLLED = re.compile(
    r"set_config\(\s*['\"]lock_timeout|SET\s+(?:LOCAL\s+)?lock_timeout|"
    r"RESET\s+lock_timeout",
    re.IGNORECASE,
)

# Job, ingest and tenant machinery that sets its own budget; remove entries as
# they move onto the shared helpers, never add one.
_ALLOWED = {
    "core/db/sqlstate.py",
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


def _files_setting_lock_timeout() -> set[str]:
    return {
        path.relative_to(APP).as_posix()
        for path in APP.rglob("*.py")
        if path.name != "catalog_locks.py"
        and _HAND_ROLLED.search(path.read_text(encoding="utf-8"))
    }


@pytest.mark.architecture
def test_no_new_module_sets_lock_timeout_by_hand() -> None:
    """A module outside the allowlist that sets lock_timeout fails; use bounded_row_lock."""
    found = _files_setting_lock_timeout()
    assert found <= _ALLOWED, f"set lock_timeout by hand: {sorted(found - _ALLOWED)}"


@pytest.mark.architecture
def test_lock_timeout_allowlist_has_no_stale_entries() -> None:
    """An allowlisted module that no longer sets lock_timeout is removed from the list."""
    stale = _ALLOWED - _files_setting_lock_timeout()
    assert not stale, f"drop from the allowlist: {sorted(stale)}"
