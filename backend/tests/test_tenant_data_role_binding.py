"""Least-privilege statement and GDAL role binding for tenant data schemas."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_TENANT_A = "00000000-0000-0000-0000-000000000001"
_TENANT_B = "00000000-0000-0000-0000-000000000002"
_SCHEMA_A = "data_t_00000000_0000_0000_0000_000000000001"
_SCHEMA_B = "data_t_00000000_0000_0000_0000_000000000002"
_READER_A = "geolens_reader_t_00000000_0000_0000_0000_000000000001"
_WRITER_A = "geolens_writer_t_00000000_0000_0000_0000_000000000001"


def _bind(monkeypatch, statement: str, parameters: object = ()):
    from app.core.db.tenant_session import (
        _before_tenant_cursor_execute,
        current_tenant_var,
    )

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    cursor = MagicMock()
    context = SimpleNamespace()
    token = current_tenant_var.set(_TENANT_A)
    try:
        _before_tenant_cursor_execute(
            object(), cursor, statement, parameters, context, False
        )
    finally:
        current_tenant_var.reset(token)
    return cursor, context


def test_select_uses_tenant_reader_and_resets_after_statement(monkeypatch):
    from app.core.db.tenant_session import _after_tenant_cursor_execute

    cursor, context = _bind(
        monkeypatch,
        f'SELECT * FROM "{_SCHEMA_A}"."roads"',
    )

    cursor.execute.assert_called_once_with(f'SET LOCAL ROLE "{_READER_A}"')
    _after_tenant_cursor_execute(object(), cursor, "", (), context, False)
    assert cursor.execute.call_args_list[-1].args == ("SET LOCAL ROLE NONE",)


@pytest.mark.parametrize(
    "statement",
    [
        f'INSERT INTO "{_SCHEMA_A}"."roads" (gid) VALUES (1)',
        f'UPDATE "{_SCHEMA_A}"."roads" SET gid = 2',
        f'ALTER TABLE "{_SCHEMA_A}"."roads" ADD COLUMN name text',
        f'WITH changed AS (DELETE FROM "{_SCHEMA_A}"."roads" RETURNING gid) '
        "SELECT gid FROM changed",
    ],
)
def test_mutating_sql_uses_tenant_writer(monkeypatch, statement):
    cursor, _context = _bind(monkeypatch, statement)
    cursor.execute.assert_called_once_with(f'SET LOCAL ROLE "{_WRITER_A}"')


def test_bound_schema_parameter_triggers_reader_binding(monkeypatch):
    cursor, _context = _bind(
        monkeypatch,
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %(schema)s",
        {"schema": _SCHEMA_A},
    )
    cursor.execute.assert_called_once_with(f'SET LOCAL ROLE "{_READER_A}"')


def test_catalog_payload_tenant_shaped_string_does_not_trigger_binding(monkeypatch):
    from app.core.db.tenant_session import (
        _before_tenant_cursor_execute,
        current_tenant_var,
    )

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    cursor = MagicMock()
    token = current_tenant_var.set(_TENANT_A)
    try:
        _before_tenant_cursor_execute(
            object(),
            cursor,
            "UPDATE catalog.records SET properties = %(payload)s",
            {"payload": {"note": f"migration from {_SCHEMA_B}"}},
            SimpleNamespace(),
            False,
        )
    finally:
        current_tenant_var.reset(token)
    cursor.execute.assert_not_called()


@pytest.mark.parametrize(
    "statement",
    [
        f'SELECT \'UPDATE {_SCHEMA_B}.roads\' FROM "{_SCHEMA_A}"."roads"',
        f'-- UPDATE "{_SCHEMA_B}"."roads"\nSELECT * FROM "{_SCHEMA_A}"."roads"',
        f'/* UPDATE "{_SCHEMA_B}"."roads" */ SELECT * FROM "{_SCHEMA_A}"."roads"',
    ],
)
def test_update_in_literal_or_comment_remains_reader_only(monkeypatch, statement):
    cursor, _context = _bind(monkeypatch, statement)
    cursor.execute.assert_called_once_with(f'SET LOCAL ROLE "{_READER_A}"')


def test_legacy_shared_data_schema_is_rejected_in_multi_tenant(monkeypatch):
    from app.core.db.tenant_session import (
        _before_tenant_cursor_execute,
        current_tenant_var,
    )

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    cursor = MagicMock()
    token = current_tenant_var.set(_TENANT_A)
    try:
        with pytest.raises(RuntimeError, match="shared data schema is forbidden"):
            _before_tenant_cursor_execute(
                object(),
                cursor,
                'SELECT * FROM "data"."roads"',
                (),
                SimpleNamespace(),
                False,
            )
    finally:
        current_tenant_var.reset(token)
    cursor.execute.assert_not_called()


def test_cross_tenant_schema_is_rejected_before_execution(monkeypatch):
    from app.core.db.tenant_session import (
        _before_tenant_cursor_execute,
        current_tenant_var,
    )

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    cursor = MagicMock()
    token = current_tenant_var.set(_TENANT_A)
    try:
        with pytest.raises(RuntimeError, match="outside the active tenant"):
            _before_tenant_cursor_execute(
                object(),
                cursor,
                f'SELECT * FROM "{_SCHEMA_B}"."roads"',
                (),
                SimpleNamespace(),
                False,
            )
    finally:
        current_tenant_var.reset(token)
    cursor.execute.assert_not_called()


def test_unscoped_tenant_schema_is_rejected(monkeypatch):
    from app.core.db.tenant_session import _before_tenant_cursor_execute

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    cursor = MagicMock()
    with pytest.raises(RuntimeError, match="active tenant context"):
        _before_tenant_cursor_execute(
            object(),
            cursor,
            f'SELECT * FROM "{_SCHEMA_A}"."roads"',
            (),
            SimpleNamespace(),
            False,
        )
    cursor.execute.assert_not_called()


def test_single_tenant_statement_binder_is_hard_noop(monkeypatch):
    from app.core.db.tenant_session import _before_tenant_cursor_execute

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
    cursor = MagicMock()
    _before_tenant_cursor_execute(
        object(),
        cursor,
        f'UPDATE "{_SCHEMA_A}"."roads" SET gid = 2',
        (),
        SimpleNamespace(),
        False,
    )
    cursor.execute.assert_not_called()


def test_ogr_role_envs_are_tenant_scoped_and_preserve_options(monkeypatch):
    from app.core.db.tenant_session import current_tenant_var
    from app.processing.ingest.ogr import (
        _tenant_reader_subprocess_env,
        _tenant_writer_subprocess_env,
    )

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    token = current_tenant_var.set(_TENANT_A)
    try:
        reader_env = _tenant_reader_subprocess_env(
            _SCHEMA_A, base_env={"PGOPTIONS": "-c statement_timeout=1000"}
        )
        writer_env = _tenant_writer_subprocess_env(_SCHEMA_A, base_env={})
    finally:
        current_tenant_var.reset(token)

    assert reader_env == {"PGOPTIONS": f"-c statement_timeout=1000 -c role={_READER_A}"}
    assert writer_env == {"PGOPTIONS": f"-c role={_WRITER_A}"}


def test_ogr_writer_rejects_cross_tenant_schema(monkeypatch):
    from app.core.db.tenant_session import current_tenant_var
    from app.processing.ingest.ogr import _tenant_writer_subprocess_env

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    token = current_tenant_var.set(_TENANT_A)
    try:
        with pytest.raises(RuntimeError, match="does not match"):
            _tenant_writer_subprocess_env(_SCHEMA_B, base_env={})
    finally:
        current_tenant_var.reset(token)


def test_writer_role_name_rejects_invalid_tenant(monkeypatch):
    from app.core.db.tenant_schema import tenant_writer_role

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    assert tenant_writer_role(_TENANT_B).endswith(
        "00000000_0000_0000_0000_000000000002"
    )
    with pytest.raises(ValueError, match="invalid tenant_id"):
        tenant_writer_role("tenant-b; SET ROLE postgres")
