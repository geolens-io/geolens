"""Tenant-schema binding regressions for the AI SQL sandbox."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db.tenant_session import current_tenant_var
from app.platform.sandbox.schemas import SandboxError


_TENANT_A = "00000000-0000-0000-0000-000000000001"
_TENANT_B = "00000000-0000-0000-0000-000000000002"
_SCHEMA_A = "data_t_00000000_0000_0000_0000_000000000001"
_SCHEMA_B = "data_t_00000000_0000_0000_0000_000000000002"
_ROLE_A = "geolens_reader_t_00000000_0000_0000_0000_000000000001"
_ROLE_B = "geolens_reader_t_00000000_0000_0000_0000_000000000002"


def _mock_engine(executed: list[str], *, fail_role: str | None = None) -> MagicMock:
    async def _execute(stmt, *args, **kwargs):
        rendered = str(stmt)
        executed.append(rendered)
        if fail_role is not None and rendered == f"SET LOCAL ROLE {fail_role}":
            raise RuntimeError("role binding denied")
        result = MagicMock()
        result.keys.return_value = []
        result.fetchall.return_value = []
        return result

    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=None)
    transaction.__aexit__ = AsyncMock(return_value=False)

    conn = AsyncMock()
    conn.execute.side_effect = _execute
    conn.begin = MagicMock(return_value=transaction)

    connection = MagicMock()
    connection.__aenter__ = AsyncMock(return_value=conn)
    connection.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect.return_value = connection
    return engine


# (original SQL, expected rewrite) with ``<S>`` standing in for the physical
# tenant schema. Exact text: the rewrite replaces schema identifier spans and
# nothing else, so single-tenant behaviour and multi-tenant behaviour agree.
_SPAN_CASES = [
    (
        "SELECT marker FROM data.roads WHERE id = 1",
        'SELECT marker FROM "<S>".roads WHERE id = 1',
    ),
    (
        'SELECT "data"."roads".marker FROM "data"."roads"',
        'SELECT "<S>"."roads".marker FROM "<S>"."roads"',
    ),
    (
        "SELECT DATA.ROADS.marker FROM DATA.ROADS",
        'SELECT "<S>".ROADS.marker FROM "<S>".ROADS',
    ),
    (
        'SELECT data."Roads".marker FROM data."Roads"',
        'SELECT "<S>"."Roads".marker FROM "<S>"."Roads"',
    ),
    # fix(#559): a literal that spells a table reference or an operator, in any
    # quoting form, is not SQL and must survive byte for byte.
    (
        "SELECT 'data.roads <=> &&' AS lit, marker FROM data.roads",
        "SELECT 'data.roads <=> &&' AS lit, marker FROM \"<S>\".roads",
    ),
    (
        "SELECT $$data.roads <=> &&$$ AS lit, marker FROM data.roads",
        'SELECT $$data.roads <=> &&$$ AS lit, marker FROM "<S>".roads',
    ),
    (
        "SELECT E'\\x41' AS lit, marker FROM data.roads",
        "SELECT E'\\x41' AS lit, marker FROM \"<S>\".roads",
    ),
    (
        "SELECT 'e\u00e9\U0001f5fa' AS lit, marker FROM data /* c */ . roads -- tail",
        "SELECT 'e\u00e9\U0001f5fa' AS lit, marker FROM \"<S>\" /* c */ . roads -- tail",
    ),
    # fix(#557): sqlglot parses the pgvector cosine operator as NullSafeEQ, so
    # re-rendering the tree turned ranking into IS NOT DISTINCT FROM.
    (
        "SELECT embedding <=> '[1]'::vector AS cos, embedding <-> '[2]'::vector AS l2 "
        "FROM data.roads",
        "SELECT embedding <=> '[1]'::vector AS cos, embedding <-> '[2]'::vector AS l2 "
        'FROM "<S>".roads',
    ),
    (
        "SELECT a IS NOT DISTINCT FROM b, embedding <=> '[1]'::vector FROM data.roads",
        "SELECT a IS NOT DISTINCT FROM b, embedding <=> '[1]'::vector "
        'FROM "<S>".roads',
    ),
    # fix(#1892): the deleted sentinel swap restored EVERY `&&` as `<=>` once a
    # real cosine operator was present, so a PostGIS bbox overlap beside one was
    # rewritten into a distance operator.
    (
        "SELECT id FROM data.roads WHERE geom && ST_MakeEnvelope(0, 0, 1, 1, 4326) "
        "ORDER BY embedding <=> '[1]'::vector",
        'SELECT id FROM "<S>".roads WHERE geom && ST_MakeEnvelope(0, 0, 1, 1, 4326) '
        "ORDER BY embedding <=> '[1]'::vector",
    ),
    (
        "WITH roads AS (SELECT 1 AS x) SELECT marker FROM data.roads",
        'WITH roads AS (SELECT 1 AS x) SELECT marker FROM "<S>".roads',
    ),
    # A CTE named `data` qualifies columns, not schemas: only the inner table
    # reference is a schema qualifier.
    (
        "WITH data AS (SELECT marker FROM data.roads) SELECT data.marker FROM data",
        'WITH data AS (SELECT marker FROM "<S>".roads) SELECT data.marker FROM data',
    ),
    (
        "SELECT a.marker FROM data.roads AS a JOIN data.roads b ON a.id = b.id",
        'SELECT a.marker FROM "<S>".roads AS a JOIN "<S>".roads b ON a.id = b.id',
    ),
    ('SELECT * FROM "DATA".roads', 'SELECT * FROM "DATA".roads'),
]


@pytest.mark.parametrize(("sql", "expected"), _SPAN_CASES)
def test_rewrite_replaces_only_schema_identifier_spans(sql, expected):
    from app.platform.sandbox.executor import _rewrite_logical_data_schema

    assert _rewrite_logical_data_schema(sql, _SCHEMA_A) == expected.replace(
        "<S>", _SCHEMA_A
    )


@pytest.mark.parametrize(
    "meta", [{}, {"start": 0, "end": 3}, {"start": 19, "end": 10_000}]
)
def test_rewrite_refuses_unusable_source_offsets(monkeypatch, meta):
    """fix(#1892): each span is proven against the text before anything is
    spliced, so a parser that stops reporting usable offsets fails closed."""
    import sqlglot
    from sqlglot import exp

    import app.platform.sandbox.executor as executor

    sql = "SELECT marker FROM data.roads"
    statement = sqlglot.parse_one(sql, dialect="postgres")
    for table in statement.find_all(exp.Table):
        identifier = table.args["db"]
        identifier.meta.clear()
        identifier.meta.update(meta)
    monkeypatch.setattr(sqlglot, "parse", lambda *args, **kwargs: [statement])

    with pytest.raises(SandboxError) as exc_info:
        executor._rewrite_logical_data_schema(sql, _SCHEMA_A)
    assert exc_info.value.category == "query_failed"


def test_analysis_preview_sql_binds_to_the_tenant_schema():
    """service_analysis renders logical ``"data"."<table>"`` refs and calls
    execute_safe directly, so the rewrite must reach the same statement the
    physical schema would have rendered."""
    from app.modules.catalog.datasets.domain.schemas import AnalysisPreviewRequest
    from app.modules.catalog.datasets.domain.service import (
        _safe_table_ref,
        build_preview_sql,
    )
    from app.platform.analysis_sql.shared import render_bbox_predicate
    from app.platform.sandbox.executor import _rewrite_logical_data_schema

    request = AnalysisPreviewRequest(
        operation="buffer", distance_meters=500, bbox=[0.0, 0.0, 1.0, 1.0]
    )
    logical = build_preview_sql(_safe_table_ref("roads"), request)
    physical = build_preview_sql(_safe_table_ref("roads", schema=_SCHEMA_A), request)
    assert f'"{_SCHEMA_A}"."roads"' in physical
    assert _rewrite_logical_data_schema(logical, _SCHEMA_A) == physical

    predicate = render_bbox_predicate([0.0, 0.0, 1.0, 1.0], src="_t")
    count_sql = (
        f"SELECT count(*)::bigint AS source_count "
        f"FROM {_safe_table_ref('roads')} AS _t WHERE {predicate}"
    )
    assert _rewrite_logical_data_schema(count_sql, _SCHEMA_A) == count_sql.replace(
        '"data"."roads"', f'"{_SCHEMA_A}"."roads"'
    )


@pytest.mark.parametrize("suffix", [";", " ;  ", ";;", " ; ;", ";;;", ";; -- pasted"])
def test_validator_strips_the_trailing_terminator_run(suffix):
    """fix(#1892): execute_safe splices validated SQL inside a LIMIT wrapper, so
    any surviving ``;`` is a syntax error. ``;;`` is ordinary paste damage."""
    from app.platform.sandbox.validator import validate_sql

    assert validate_sql(f"SELECT id FROM data.roads{suffix}").sql == (
        "SELECT id FROM data.roads"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM data.roads --;",
        "SELECT ';' AS a FROM data.roads",
        "SELECT ';;' AS a FROM data.roads",
    ],
)
def test_validator_keeps_a_semicolon_that_is_not_a_terminator(sql):
    from app.platform.sandbox.validator import validate_sql

    assert validate_sql(sql).sql == sql


@pytest.mark.parametrize("sql", ["SELECT 1; SELECT 2;", ";", ";;"])
def test_validator_still_rejects_what_the_strip_leaves(sql):
    """Stripping the run leaves a second statement in place, and reduces a bare
    terminator to nothing; both fail the single-statement check."""
    from app.platform.sandbox.validator import validate_sql

    with pytest.raises(SandboxError) as exc_info:
        validate_sql(sql)
    assert exc_info.value.category == "invalid_query"


@pytest.mark.parametrize(
    ("schema", "table"), [("DATA", "roads"), ("Data", "roads"), ("Data", "Roads")]
)
def test_schema_rewrite_folds_unquoted_logical_schema(schema, table):
    """fix(#1891): an unquoted schema folds to lowercase, as PostgreSQL and the
    validator fold it, so any spelling of ``data`` is the logical schema and must
    reach the physical tenant schema; the table part is left as written."""
    from app.platform.sandbox.executor import _rewrite_logical_data_schema
    from app.platform.sandbox.validator import validate_sql

    sql = f"SELECT * FROM {schema}.{table}"
    assert validate_sql(sql).tables == {("data", "roads")}

    rewritten = _rewrite_logical_data_schema(sql, _SCHEMA_A)

    assert f'FROM "{_SCHEMA_A}".{table}' in rewritten
    assert f"{schema}.{table}" not in rewritten


def test_schema_rewrite_folds_unquoted_three_part_column():
    """fix(#1891): a schema-qualified column reference folds the same way as a
    table reference."""
    from app.platform.sandbox.executor import _rewrite_logical_data_schema

    rewritten = _rewrite_logical_data_schema(
        "SELECT DATA.roads.geom FROM DATA.roads", _SCHEMA_A
    )

    assert f'"{_SCHEMA_A}".roads.geom' in rewritten
    assert f'FROM "{_SCHEMA_A}".roads' in rewritten
    assert "DATA." not in rewritten


def test_schema_rewrite_leaves_quoted_uppercase_schema_alone():
    """fix(#1891): quoted ``"DATA"`` keeps its case, so it is another schema:
    the rewrite leaves it in place and the access check refuses it."""
    from app.platform.sandbox.executor import _rewrite_logical_data_schema
    from app.platform.sandbox.validator import check_table_access, validate_sql

    sql = 'SELECT * FROM "DATA".roads'
    rewritten = _rewrite_logical_data_schema(sql, _SCHEMA_A)
    assert '"DATA".roads' in rewritten
    assert _SCHEMA_A not in rewritten

    validated = validate_sql(sql)
    assert validated.tables == {("DATA", "roads")}
    with pytest.raises(SandboxError) as exc_info:
        check_table_access(validated.tables, {"roads"}, validated.cte_names)
    assert exc_info.value.category == "table_not_accessible"


@pytest.mark.asyncio
async def test_multi_tenant_rewrites_only_logical_data_schema(monkeypatch):
    monkeypatch.setattr("app.platform.sandbox.executor.is_multi_tenant", lambda: True)
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

    executed: list[str] = []
    import app.core.db as db_module
    from app.platform.sandbox.executor import execute_safe

    token = current_tenant_var.set(_TENANT_A)
    try:
        with patch.object(db_module, "engine", _mock_engine(executed)):
            await execute_safe(
                MagicMock(),
                "SELECT data.alpha.id FROM data.alpha "
                "JOIN data.beta ON data.beta.id = data.alpha.id "
                "WHERE data.alpha.note = 'data.alpha'",
            )
    finally:
        current_tenant_var.reset(token)

    query = next(
        statement for statement in executed if statement.startswith("SELECT *")
    )
    assert f'"{_SCHEMA_A}".alpha' in query
    assert f'"{_SCHEMA_A}".beta' in query
    assert f'"{_SCHEMA_A}".alpha.id' in query
    assert f'"{_SCHEMA_A}".beta.id' in query
    assert "FROM data.alpha" not in query
    assert "JOIN data.beta" not in query
    assert "data.alpha.id" not in query
    assert "data.beta.id" not in query
    assert "'data.alpha'" in query


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM data.alpha WHERE note = 'unterminated",
        # fix(#1892): parse_one reports a second statement as one Block, so the
        # rewrite used to pass `a; b` through and rewrite both halves.
        "SELECT 1; DROP TABLE data.alpha",
        "SELECT id FROM data.alpha; SELECT * FROM data.beta",
    ],
)
@pytest.mark.asyncio
async def test_multi_tenant_rejects_unusable_sql_before_connecting(monkeypatch, sql):
    """fix(#1892): the rewrite parses before anything is executed, so SQL it
    cannot bind raises SandboxError with no connection opened. execute_safe has
    direct callers that skip the validator."""
    monkeypatch.setattr("app.platform.sandbox.executor.is_multi_tenant", lambda: True)
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

    executed: list[str] = []
    import app.core.db as db_module
    from app.platform.sandbox.executor import execute_safe

    engine = _mock_engine(executed)
    token = current_tenant_var.set(_TENANT_A)
    try:
        with patch.object(db_module, "engine", engine):
            with pytest.raises(SandboxError) as exc_info:
                await execute_safe(MagicMock(), sql)
    finally:
        current_tenant_var.reset(token)

    assert exc_info.value.category == "invalid_query"
    assert executed == []
    engine.connect.assert_not_called()


@pytest.mark.asyncio
async def test_multi_tenant_role_binding_failure_is_fatal(monkeypatch):
    monkeypatch.setattr("app.platform.sandbox.executor.is_multi_tenant", lambda: True)
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

    executed: list[str] = []
    import app.core.db as db_module
    from app.platform.sandbox.executor import execute_safe

    token = current_tenant_var.set(_TENANT_A)
    try:
        with patch.object(
            db_module,
            "engine",
            _mock_engine(executed, fail_role=_ROLE_A),
        ):
            with pytest.raises(SandboxError) as exc_info:
                await execute_safe(MagicMock(), "SELECT id FROM data.alpha")
    finally:
        current_tenant_var.reset(token)

    assert exc_info.value.category == "query_failed"
    assert f"SET LOCAL ROLE {_ROLE_A}" in executed
    assert not any(statement.startswith("SELECT *") for statement in executed)


_requires_test_db = pytest.mark.skipif(
    not os.environ.get("POSTGRES_HOST"),
    reason="Requires test DB (set POSTGRES_HOST in .env.test)",
)


@pytest.mark.asyncio
@_requires_test_db
async def test_logical_data_query_reads_only_active_tenant_schema(monkeypatch):
    """The same logical query resolves to different physical tenant tables."""
    monkeypatch.setattr("app.platform.sandbox.executor.is_multi_tenant", lambda: True)
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

    from app.core.config import settings
    from app.platform.sandbox.executor import execute_safe

    table = f"sandbox_tenant_{uuid.uuid4().hex[:12]}"
    engine = create_async_engine(settings.test_database_url, poolclass=NullPool)
    import app.core.db as db_module

    try:
        async with engine.begin() as conn:
            for schema, role, marker in (
                (_SCHEMA_A, _ROLE_A, "tenant-a"),
                (_SCHEMA_B, _ROLE_B, "tenant-b"),
            ):
                await conn.execute(
                    sa.text(f'CREATE TABLE {schema}."{table}" (marker text NOT NULL)')
                )
                await conn.execute(
                    sa.text(
                        f'INSERT INTO {schema}."{table}" (marker) VALUES (:marker)'
                    ),
                    {"marker": marker},
                )
                await conn.execute(
                    sa.text(f'GRANT SELECT ON {schema}."{table}" TO {role}')
                )

        observed: dict[str, str] = {}
        with patch.object(db_module, "engine", engine):
            for tenant_id in (_TENANT_A, _TENANT_B):
                token = current_tenant_var.set(tenant_id)
                try:
                    result = await execute_safe(
                        MagicMock(),
                        f'SELECT data."{table}".marker FROM data."{table}"',
                    )
                finally:
                    current_tenant_var.reset(token)
                observed[tenant_id] = result.rows[0][0]

            # fix(#1892): the shape the span rewrite has to get right, run for
            # real: unquoted DATA, a comment inside the reference, a non-ASCII
            # literal ahead of it and a trailing line comment.
            token = current_tenant_var.set(_TENANT_A)
            try:
                awkward = await execute_safe(
                    MagicMock(),
                    f"SELECT 'eé\U0001f5fa' AS note, "
                    f'DATA /* c */ ."{table}".marker '
                    f'FROM DATA."{table}" -- tail',
                )
            finally:
                current_tenant_var.reset(token)

        assert observed == {_TENANT_A: "tenant-a", _TENANT_B: "tenant-b"}
        assert awkward.rows == [["eé\U0001f5fa", "tenant-a"]]
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'DROP TABLE IF EXISTS {_SCHEMA_A}."{table}"'))
            await conn.execute(sa.text(f'DROP TABLE IF EXISTS {_SCHEMA_B}."{table}"'))
        await engine.dispose()


@pytest.mark.asyncio
@_requires_test_db
async def test_tenant_reader_role_refuses_another_tenants_schema(monkeypatch):
    """The reader role, not the rewrite, is the isolation boundary: a statement
    naming another tenant's physical schema is refused, and the same statement
    under that tenant returns the row."""
    monkeypatch.setattr("app.platform.sandbox.executor.is_multi_tenant", lambda: True)
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

    from app.core.config import settings
    from app.platform.sandbox.executor import execute_safe

    table = f"sandbox_denial_{uuid.uuid4().hex[:12]}"
    engine = create_async_engine(settings.test_database_url, poolclass=NullPool)
    import app.core.db as db_module

    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(f'CREATE TABLE {_SCHEMA_B}."{table}" (marker text NOT NULL)')
            )
            await conn.execute(
                sa.text(f'INSERT INTO {_SCHEMA_B}."{table}" (marker) VALUES (:m)'),
                {"m": "tenant-b"},
            )
            await conn.execute(
                sa.text(f'GRANT SELECT ON {_SCHEMA_B}."{table}" TO {_ROLE_B}')
            )

        cross_tenant_sql = f'SELECT marker FROM {_SCHEMA_B}."{table}"'
        with patch.object(db_module, "engine", engine):
            token = current_tenant_var.set(_TENANT_A)
            try:
                with pytest.raises(SandboxError) as exc_info:
                    await execute_safe(MagicMock(), cross_tenant_sql)
            finally:
                current_tenant_var.reset(token)

            token = current_tenant_var.set(_TENANT_B)
            try:
                allowed = await execute_safe(MagicMock(), cross_tenant_sql)
                logical = await execute_safe(
                    MagicMock(), f'SELECT marker FROM data."{table}"'
                )
            finally:
                current_tenant_var.reset(token)

        assert exc_info.value.category == "query_failed"
        assert allowed.rows == [["tenant-b"]]
        assert logical.rows == [["tenant-b"]]
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'DROP TABLE IF EXISTS {_SCHEMA_B}."{table}"'))
        await engine.dispose()
