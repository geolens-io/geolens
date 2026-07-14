"""Regression coverage for admin identity migration compatibility."""

import importlib.util
from pathlib import Path
from typing import Any


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0016_admin_identity_hardening.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "migration_0016_admin_identity_hardening",
    _MIGRATION_PATH,
)
assert _SPEC is not None
migration = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(migration)


def test_downgrade_restores_legacy_disabled_state_before_column_drop(monkeypatch):
    """Pre-0016 code must be able to list and reactivate disabled users."""
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def record(name: str):
        def _record(*args: Any, **kwargs: Any) -> None:
            calls.append((name, args, kwargs))

        return _record

    monkeypatch.setattr(migration.op, "drop_constraint", record("drop_constraint"))
    monkeypatch.setattr(migration.op, "execute", record("execute"))
    monkeypatch.setattr(migration.op, "drop_column", record("drop_column"))

    migration.downgrade()

    assert [name for name, _args, _kwargs in calls] == [
        "drop_constraint",
        "execute",
        "drop_column",
    ]
    normalized_sql = " ".join(calls[1][1][0].split())
    assert normalized_sql == (
        "UPDATE catalog.users SET status = 'active', is_active = false "
        "WHERE status IN ('deactivated', 'suspended')"
    )
