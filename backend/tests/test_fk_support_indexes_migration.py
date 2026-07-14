"""Static invariants for migration 0017's nullable FK-support indexes.

These tests intentionally need no database. The clean-DB Alembic gate remains
the integration proof; this suite gives fast coverage for the complete index
inventory, concurrent/resumable DDL, and matching ORM metadata.
"""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import Index

import app.modules.catalog.collections.models  # noqa: F401
import app.modules.catalog.datasets.domain.models  # noqa: F401
import app.modules.catalog.maps.models  # noqa: F401
import app.modules.embed_tokens.models  # noqa: F401
from app.core.db import Base


EXPECTED_INDEXES = (
    ("ix_collection_datasets_added_by", "collection_datasets", "added_by"),
    ("ix_collections_created_by", "collections", "created_by"),
    ("ix_dataset_versions_uploaded_by", "dataset_versions", "uploaded_by"),
    ("ix_embed_tokens_created_by", "embed_tokens", "created_by"),
    ("ix_map_share_tokens_created_by", "map_share_tokens", "created_by"),
    ("ix_maps_forked_from", "maps", "forked_from"),
    ("ix_records_created_by", "records", "created_by"),
    ("ix_records_updated_by", "records", "updated_by"),
)


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0017_add_fk_support_indexes.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0017", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _postgresql_predicate(index: Index) -> str:
    predicate = index.dialect_options["postgresql"]["where"]
    assert predicate is not None
    return str(predicate)


def test_orm_declares_every_partial_fk_support_index() -> None:
    for index_name, table_name, column_name in EXPECTED_INDEXES:
        table = Base.metadata.tables[f"catalog.{table_name}"]
        matches = [index for index in table.indexes if index.name == index_name]
        assert len(matches) == 1, f"missing or duplicate ORM index {index_name}"

        index = matches[0]
        assert [column.name for column in index.columns] == [column_name]
        assert _postgresql_predicate(index) == f"{column_name} IS NOT NULL"


class _FakeResult:
    def __init__(self, row) -> None:
        self._row = row

    def one_or_none(self):
        return self._row


class _FakeBind:
    def __init__(self, states: dict[str, tuple[bool, bool] | None]) -> None:
        self._states = states
        self.queries: list[str] = []

    def execute(self, statement, params):
        self.queries.append(str(statement))
        state = self._states[params["index_name"]]
        row = (
            None
            if state is None
            else SimpleNamespace(indisvalid=state[0], indisready=state[1])
        )
        return _FakeResult(row)


def test_upgrade_reuses_valid_indexes_and_repairs_invalid_ones(monkeypatch) -> None:
    migration = _load_migration()
    executed: list[str] = []
    autocommit_entries = 0
    states = {name: None for name, _table, _column in EXPECTED_INDEXES}
    states["ix_collections_created_by"] = (True, True)
    states["ix_records_created_by"] = (False, False)
    bind = _FakeBind(states)

    class FakeContext:
        @contextmanager
        def autocommit_block(self):
            nonlocal autocommit_entries
            autocommit_entries += 1
            yield

    monkeypatch.setattr(migration.op, "get_context", lambda: FakeContext())
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.upgrade()

    assert migration.FK_SUPPORT_INDEXES == EXPECTED_INDEXES
    assert len(bind.queries) == len(EXPECTED_INDEXES)
    assert all("pg_catalog.pg_index" in query for query in bind.queries)

    # Six absent indexes and one invalid index are built; the valid one is
    # untouched. Repairing the invalid index emits DROP then CREATE in the same
    # autocommit block.
    assert autocommit_entries == len(EXPECTED_INDEXES) - 1
    assert not any("ix_collections_created_by" in sql for sql in executed)
    assert (
        executed.count(
            'DROP INDEX CONCURRENTLY IF EXISTS catalog."ix_records_created_by"'
        )
        == 1
    )

    create_statements = [sql for sql in executed if sql.startswith("CREATE INDEX")]
    expected_creates = [
        item for item in EXPECTED_INDEXES if item[0] != "ix_collections_created_by"
    ]
    assert len(create_statements) == len(expected_creates)
    for sql, (index_name, table_name, column_name) in zip(
        create_statements, expected_creates, strict=True
    ):
        assert sql == (
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{index_name}" '
            f'ON catalog."{table_name}" ("{column_name}") '
            f'WHERE "{column_name}" IS NOT NULL'
        )


def test_downgrade_uses_concurrent_resumable_ddl(monkeypatch) -> None:
    migration = _load_migration()
    executed: list[str] = []
    autocommit_entries = 0

    class FakeContext:
        @contextmanager
        def autocommit_block(self):
            nonlocal autocommit_entries
            autocommit_entries += 1
            yield

    monkeypatch.setattr(migration.op, "get_context", lambda: FakeContext())
    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.downgrade()

    assert autocommit_entries == 1
    assert migration.FK_SUPPORT_INDEXES == EXPECTED_INDEXES
    assert len(executed) == len(EXPECTED_INDEXES)
    for sql, (index_name, _table_name, _column_name) in zip(
        executed, reversed(EXPECTED_INDEXES), strict=True
    ):
        assert sql == f'DROP INDEX CONCURRENTLY IF EXISTS catalog."{index_name}"'
