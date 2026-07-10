"""fix(#435): an unreachable Postgres must skip DB-backed tests only.

`_test_db_lifecycle` used to call `pytest.skip()` from session-scoped autouse
setup, which skipped every collected item. `pytest -q tests/test_layering.py`
then exited 0 having executed nothing, so the architecture gates could not fail.
"""

from types import SimpleNamespace

import pytest

import tests.conftest as conftest


def _run_gate(fixturenames: set[str]) -> None:
    """Invoke the body of the `_skip_if_db_unavailable` fixture directly."""
    request = SimpleNamespace(fixturenames=fixturenames)
    conftest._skip_if_db_unavailable.__wrapped__(request)


def test_pure_test_runs_when_db_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conftest, "_db_unavailable_reason", "connection refused")
    _run_gate({"tmp_path", "monkeypatch"})  # no pytest.Skipped raised


def test_db_test_skips_when_db_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conftest, "_db_unavailable_reason", "connection refused")
    with pytest.raises(pytest.skip.Exception, match="Postgres unreachable"):
        _run_gate({"client", "tmp_path"})


def test_db_test_runs_when_db_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conftest, "_db_unavailable_reason", None)
    _run_gate({"client"})


def test_transitive_db_fixtures_are_covered() -> None:
    """Every fixture that reaches Postgres during setup must be in the gate set."""
    assert "client" in conftest._DB_FIXTURE_NAMES
    assert "test_db_session" in conftest._DB_FIXTURE_NAMES
