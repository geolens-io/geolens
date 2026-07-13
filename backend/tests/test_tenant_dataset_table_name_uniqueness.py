"""Live contract tests for migration 0018's tenant-scoped table names."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


async def _insert_record(db, record_id: uuid.UUID, tenant_id: uuid.UUID | None) -> None:
    await db.execute(
        text(
            "INSERT INTO catalog.records "
            "(id, title, visibility, record_status, record_type, tenant_id) "
            "VALUES (:id, :title, 'private', 'draft', 'vector_dataset', :tenant_id)"
        ),
        {
            "id": record_id,
            "title": f"table-name-contract-{record_id}",
            "tenant_id": tenant_id,
        },
    )


async def _insert_dataset(
    db,
    record_id: uuid.UUID,
    table_name: str,
    tenant_id: uuid.UUID | None,
) -> None:
    await db.execute(
        text(
            "INSERT INTO catalog.datasets (record_id, table_name, tenant_id) "
            "VALUES (:record_id, :table_name, :tenant_id)"
        ),
        {
            "record_id": record_id,
            "table_name": table_name,
            "tenant_id": tenant_id,
        },
    )


@pytest.mark.anyio
async def test_tenant_table_name_partial_unique_indexes(
    test_db_session,
    clean_tables,
):
    """Cross-tenant reuse works; same-tenant and global duplicates fail."""
    del clean_tables

    index_result = await test_db_session.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'catalog' "
            "AND indexname IN ("
            "  'uq_datasets_table_name_global', "
            "  'uq_datasets_table_name_tenant'"
            ")"
        )
    )
    index_defs = {name: definition for name, definition in index_result.all()}
    assert set(index_defs) == {
        "uq_datasets_table_name_global",
        "uq_datasets_table_name_tenant",
    }
    assert "WHERE (tenant_id IS NULL)" in index_defs["uq_datasets_table_name_global"]
    assert (
        "WHERE (tenant_id IS NOT NULL)" in index_defs["uq_datasets_table_name_tenant"]
    )

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    shared_name = f"shared_{uuid.uuid4().hex}"
    record_ids = [uuid.uuid4() for _ in range(5)]
    tenant_ids = [tenant_a, tenant_b, tenant_a, None, None]
    for record_id, tenant_id in zip(record_ids, tenant_ids, strict=True):
        await _insert_record(test_db_session, record_id, tenant_id)

    await _insert_dataset(test_db_session, record_ids[0], shared_name, tenant_a)
    await _insert_dataset(test_db_session, record_ids[1], shared_name, tenant_b)

    with pytest.raises(IntegrityError):
        async with test_db_session.begin_nested():
            await _insert_dataset(
                test_db_session,
                record_ids[2],
                shared_name,
                tenant_a,
            )

    global_name = f"global_{uuid.uuid4().hex}"
    await _insert_dataset(test_db_session, record_ids[3], global_name, None)
    with pytest.raises(IntegrityError):
        async with test_db_session.begin_nested():
            await _insert_dataset(test_db_session, record_ids[4], global_name, None)
