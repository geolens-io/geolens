"""The checks and catalog stamp around a dataset's previous-version table.

The swap in ``tasks_common.install_candidate_table`` calls the checks before
it renames anything; the replacement and restore writes call the stamp.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.heartbeat import (
    dependent_relations,
    previous_version_name_claimed,
    previous_version_table,
    relation_present,
)
from app.processing.ingest.metadata import _qtable
from app.processing.ingest.tasks_common import _current_tenant_schema


class PreviousVersionNameTaken(RuntimeError):
    """The previous-version name holds a table this dataset did not keep."""


class DependentRelationsBlockSwap(RuntimeError):
    """Views or foreign keys elsewhere hold a table the swap would rename or drop."""

    def __init__(self, relations: list[str]) -> None:
        super().__init__(
            f"The data was not replaced because {', '.join(relations)} "
            f"{'depends' if len(relations) == 1 else 'depend'} on this "
            "dataset's table and would keep reading the old rows. Drop or "
            "redefine them, then try again."
        )
        self.relations = relations


async def refuse_dependent_relations(
    session: AsyncSession, tables: tuple[str, ...], *, schema: str
) -> None:
    """Lock each existing table, then refuse while another relation depends on one.

    Its views and foreign keys bind the table's oid, so after a rename they
    would serve the kept rows, and a later drop of that table would fail.
    """
    blocking: list[str] = []
    for table in tables:
        if await relation_present(session, schema, table):
            await session.execute(
                text(
                    f"LOCK TABLE {_qtable(table, schema=schema)} IN ACCESS EXCLUSIVE MODE"
                )
            )
            blocking += await dependent_relations(session, schema, table)
    if blocking:
        raise DependentRelationsBlockSwap(sorted(set(blocking)))


async def require_own_previous_version_name(
    session: AsyncSession, dataset: Any, previous: str, *, schema: str
) -> None:
    """Refuse unless ``previous`` is free or holds the previous version this dataset recorded.

    The name is predictable, so a table found under it is dropped or renamed
    only when the catalog says it is this dataset's own.
    """
    from app.platform.extensions import get_processing_port

    Dataset = get_processing_port().get_dataset_orm_class()
    recorded = await session.scalar(
        select(Dataset.previous_version_number).where(Dataset.id == dataset.id)
    )
    present = await relation_present(session, schema, previous)
    if await previous_version_name_claimed(session, previous) or (
        present and recorded is None
    ):
        structlog.get_logger().warning(
            "previous_version_name_taken", dataset_id=str(dataset.id)
        )
        raise PreviousVersionNameTaken(
            "Another table already uses the name this dataset keeps its "
            "previous version under, so the data was not replaced. Ask an "
            "administrator to rename that table."
        )


async def stamp_previous_version(
    session: AsyncSession, dataset: Any, version_number: int
) -> None:
    """Record that the previous-version table holds ``version_number``, or that none exists.

    Call after the swap, in its transaction, holding the catalog rows, and
    before ``last_refreshed_at`` is moved on: it records the replaced data's.
    """
    previous = _qtable(
        previous_version_table(dataset.table_name, dataset.id),
        schema=_current_tenant_schema(),
    )
    size = await session.scalar(
        text("SELECT pg_total_relation_size(to_regclass(:previous))"),
        {"previous": previous},
    )
    kept = size is not None
    dataset.previous_version_number = version_number if kept else None
    dataset.previous_version_retained_at = datetime.now(timezone.utc) if kept else None
    dataset.previous_version_bytes = size
    dataset.previous_version_refreshed_at = dataset.last_refreshed_at if kept else None
