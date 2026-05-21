"""Regression tests for the conftest test-DB lifecycle (TI-01).

Pins:
- worker_id-aware DB naming under pytest-xdist
- 63-char PostgreSQL identifier truncation
- settings.postgres_db_test mutation during the session fixture
- the test DB actually exists and is reachable after the fixture yields

These tests are the regression net for the 1363 InvalidCatalogNameError
errors observed in v1016 Phase 1074. If any of them fail, the conftest
test-DB lifecycle has drifted from the TI-01 contract.

Pure-unit style for Tests 1-4 (no @pytest.mark.asyncio, no DB I/O); they
exercise the naming + quoting helpers in isolation. Tests 5-6 implicitly
depend on the autouse session-scoped ``_test_db_lifecycle`` fixture — they
connect to the live test DB and assert it is reachable + that the settings
mutation is in effect during the yield window.
"""

import re

import sqlalchemy
from sqlalchemy import text

from app.core.config import settings
from tests.conftest import (
    _quote_database_identifier,
    _worker_test_database_name,
)


def test_worker_test_database_name_solo(monkeypatch):
    """Without PYTEST_XDIST_WORKER set, the DB name uses the 'master' token.

    This is the legacy / sequential pytest path (also covers `-x` and IDE
    runners that don't load pytest-xdist).
    """
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    name = _worker_test_database_name("geolens_test")
    assert re.fullmatch(
        r"geolens_test_master_[0-9a-f]{8}", name
    ), f"unexpected solo DB name: {name!r}"


def test_worker_test_database_name_xdist(monkeypatch):
    """With PYTEST_XDIST_WORKER=gw3 set, the DB name embeds 'gw3'.

    This pins the per-worker isolation contract that makes `pytest -n auto`
    safe: each xdist worker gets a physically distinct database.
    """
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    name = _worker_test_database_name("geolens_test")
    assert re.fullmatch(
        r"geolens_test_gw3_[0-9a-f]{8}", name
    ), f"unexpected xdist DB name: {name!r}"


def test_worker_test_database_name_truncates_to_63_chars(monkeypatch):
    """PostgreSQL identifiers cap at 63 chars; the helper MUST respect that.

    A 65-char base name + worker_id + uuid suffix would otherwise blow past
    the limit and PG would silently truncate, breaking the DROP DATABASE
    teardown lookup.
    """
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw15")  # longer worker id
    long_base = "a" * 65
    name = _worker_test_database_name(long_base)
    assert len(name) <= 63, f"identifier exceeds 63 chars: len={len(name)} {name!r}"
    # The worker_id + 8-hex suffix MUST still be present after truncation.
    assert "_gw15_" in name, f"worker_id missing after truncate: {name!r}"
    assert re.search(r"_[0-9a-f]{8}$", name), f"uuid suffix missing: {name!r}"


def test_quote_database_identifier_escapes_doublequotes():
    """Embedded double-quotes in DB names MUST be doubled per PG quoting rules.

    Belt-and-braces — the helper is fed only generated names today, but the
    helper itself is the trust boundary for SQL identifier injection.
    """
    assert _quote_database_identifier("plain") == '"plain"'
    assert _quote_database_identifier('foo"bar') == '"foo""bar"'
    # Multiple embedded quotes
    assert _quote_database_identifier('a"b"c') == '"a""b""c"'


def test_test_db_exists_after_session_fixture_yields():
    """The autouse session fixture MUST have created a reachable test DB.

    This is the headline regression for the 1363 InvalidCatalogNameError
    errors: if `_test_db_lifecycle` setup ran AND the worker_id naming +
    teardown ordering work, then a fresh sync connection to
    settings.test_database_url_sync must complete `SELECT 1` cleanly.
    """
    engine = sqlalchemy.create_engine(settings.test_database_url_sync)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
            assert result == 1, f"SELECT 1 returned {result!r}"
    finally:
        engine.dispose()


def test_settings_postgres_db_test_is_mutated():
    """During the fixture's yield, settings.postgres_db_test MUST embed a worker_id.

    Protects against future refactors that bypass the fixture's mutation step.
    The pattern `_(master|gw\\d+)_` matches both the solo and xdist forms;
    we don't assert the specific worker_id because that varies across runs.
    """
    db_name = settings.postgres_db_test
    assert re.search(
        r"_(master|gw\d+)_[0-9a-f]{8}$", db_name
    ), f"settings.postgres_db_test not mutated to per-worker form: {db_name!r}"
