"""The ``database`` origin kind: vocabulary, binding, policy and identifiers."""

from __future__ import annotations

import ast
import typing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.catalog.datasets.domain.models import Dataset
from app.platform import database_sources
from app.platform.dataset_origin import (
    ORIGIN_KINDS,
    ORIGIN_REF_KEYS,
    DatabaseSource,
    OriginKind,
    SourceBinding,
    Unavailable,
    build_origin_ref,
    classify_origin,
    read_source,
)
from app.platform.jobs.router import get_retry_capability
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import RUN_ORIGIN_KINDS

MIGRATION = (
    Path(__file__).resolve().parents[1] / "alembic/versions/0103_database_origin.py"
)


def _check_values(table, name: str) -> set[str]:
    constraint = next(c for c in table.constraints if c.name == name)
    text = str(constraint.sqltext)
    return {part.split("'")[1] for part in text.split(",") if "'" in part}


def test_the_kind_is_declared_everywhere_it_is_spelled() -> None:
    assert "database" in ORIGIN_KINDS
    assert set(typing.get_args(OriginKind)) == ORIGIN_KINDS
    assert classify_origin("database") == "database"
    assert classify_origin("database", "vector_dataset") == "database"
    assert "database" in RUN_ORIGIN_KINDS
    assert "database" in _check_values(Dataset.__table__, "chk_datasets_source_format")
    assert _check_values(
        DatasetRefreshRun.__table__, "chk_refresh_runs_origin_kind"
    ) == set(RUN_ORIGIN_KINDS)


def test_the_migration_widens_to_the_model_checks() -> None:
    namespace: dict = {}
    tree = ast.parse(MIGRATION.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id.startswith(
            ("_OLD_", "_NEW_")
        ):
            exec(compile(ast.Module([node], []), str(MIGRATION), "exec"), namespace)

    def values(spelled: str) -> set[str]:
        return {part.strip().strip("'") for part in spelled.split(",")}

    assert values(namespace["_NEW_FORMATS"]) == _check_values(
        Dataset.__table__, "chk_datasets_source_format"
    )
    assert values(namespace["_NEW_RUN_KINDS"]) == set(RUN_ORIGIN_KINDS)
    assert values(namespace["_NEW_FORMATS"]) - values(namespace["_OLD_FORMATS"]) == {
        "database"
    }


def test_the_ref_holds_only_the_connection_name_and_table() -> None:
    assert ORIGIN_REF_KEYS["database"] == {"connection", "schema", "table"}
    for secret in ("host", "port", "username", "password", "dsn"):
        with pytest.raises(ValueError):
            build_origin_ref(
                "database", connection="gis", schema="dbo", table="t", **{secret: "x"}
            )


def test_binding_points_at_the_connection_name() -> None:
    binding = SourceBinding.database("gis", schema="dbo", table="parcels")
    assert binding.kind == "database"
    assert binding.source_format == "database"
    assert binding.uri == "database://gis/dbo.parcels"
    assert binding.ref == {
        "kind": "database",
        "connection": "gis",
        "schema": "dbo",
        "table": "parcels",
    }


def test_read_source_names_the_first_missing_key() -> None:
    ref = SourceBinding.database("gis", schema="dbo", table="parcels").ref
    assert read_source("database", ref) == DatabaseSource("gis", "dbo", "parcels")
    assert read_source("database", {**ref, "schema": ""}) == Unavailable(
        "database", "schema"
    )
    assert read_source("database", {"connection": "gis", "schema": "dbo"}) == (
        Unavailable("database", "table")
    )


@pytest.mark.parametrize("name", ["dbo", "parcels_2263", "Straße", "_t", "a$b#c@d"])
def test_importable_identifiers(name: str) -> None:
    assert database_sources.importable_identifier(name)


@pytest.mark.parametrize(
    "name", ["", "a.b", "odd]name", "[x]", "-x", "1abc", "a b", "a;b", "x" * 129]
)
def test_identifiers_that_could_name_another_layer_are_refused(name: str) -> None:
    assert not database_sources.importable_identifier(name)


def test_table_probe_sql_quotes_the_names_it_is_given() -> None:
    sql = database_sources._table_columns_sql("d'bo", "a]b")
    assert "OBJECT_ID(N'[d''bo].[a]]b]')" in sql
    assert "ORDER BY c.column_id" in sql


@pytest.mark.anyio
async def test_table_probe_reads_the_first_spatial_column_and_its_srid(
    monkeypatch,
) -> None:
    run = AsyncMock(side_effect=[[{"column_name": "shape"}], [{"i": 0, "srid": 0}]])
    monkeypatch.setattr(database_sources, "run_database_sql", run)
    probed = await database_sources.probe_table_geometry("gis", "dbo", "t")
    assert probed == database_sources.TableGeometry(column="shape", srid=None)
    assert "[shape].STSrid" in run.await_args_list[1].args[1]

    run.side_effect = [[], []]
    with pytest.raises(database_sources.DatabaseTableError):
        await database_sources.probe_table_geometry("gis", "dbo", "t")


@pytest.mark.anyio
async def test_a_failed_database_import_can_be_retried() -> None:
    job = SimpleNamespace(
        status="failed",
        source_url=None,
        file_path=None,
        user_metadata={
            "database_source": {"connection": "gis", "schema": "dbo", "table": "t"}
        },
    )
    assert await get_retry_capability(job) == (True, None)
    job.user_metadata = {**job.user_metadata, "reupload": True, "refresh": True}
    assert (await get_retry_capability(job))[0] is False
