"""The checks and catalog stamp around a dataset's kept previous versions.

The swap in ``tasks_common.install_candidate_table`` calls the checks before
it renames anything; the replacement and restore writes call the stamp.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.relations import dependent_relations, relation_present
from app.platform.jobs.heartbeat import (
    previous_version_name_claimed,
    previous_version_table,
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


async def kept_versions(
    session: AsyncSession, dataset_id: Any
) -> list[tuple[int, str]]:
    """The dataset's kept versions as ``(version number, table)``, newest first."""
    rows = await session.execute(
        text(
            "SELECT version_number, kept_table FROM catalog.dataset_versions "
            "WHERE dataset_id = :dataset_id AND kept_table IS NOT NULL "
            "ORDER BY version_number DESC"
        ),
        {"dataset_id": dataset_id},
    )
    return [(number, table) for number, table in rows.all()]


async def kept_tables_to_drop(
    session: AsyncSession, dataset: Any, *, keeping: bool, restoring: int | None
) -> list[str]:
    """The kept tables a swap drops, oldest first past ``PREVIOUS_VERSIONS_KEPT``.

    ``keeping`` says whether the swap keeps the live table, which counts as
    the newest; ``restoring`` is the kept version it publishes, which no
    longer counts. A table a catalog dataset uses as its own is never
    dropped; the stamp forgets it as a kept version.
    """
    from app.core.persistent_config import PREVIOUS_VERSIONS_KEPT

    # Uncached: a stale lower limit would drop versions an admin just chose to keep.
    limit = await PREVIOUS_VERSIONS_KEPT.get_uncached(session)
    retained = [
        table
        for number, table in await kept_versions(session, dataset.id)
        if number != restoring
    ]
    past = retained[max(limit - int(keeping), 0) :]
    claimed = set(
        await session.scalars(
            text(
                "SELECT table_name FROM catalog.datasets "
                "WHERE table_name = ANY(CAST(:names AS text[]))"
            ),
            {"names": past},
        )
    )
    return [table for table in past if table not in claimed]


def _name_taken(dataset: Any) -> PreviousVersionNameTaken:
    structlog.get_logger().warning(
        "previous_version_name_taken", dataset_id=str(dataset.id)
    )
    return PreviousVersionNameTaken(
        "Another table already uses the name this dataset keeps its "
        "previous version under, so the data was not replaced. Ask an "
        "administrator to rename that table."
    )


async def require_free_previous_version_name(
    session: AsyncSession, dataset: Any, name: str, *, schema: str
) -> None:
    """Refuse unless no relation and no catalog dataset uses ``name``.

    The name is predictable, and the swap is about to keep the live table
    under it.
    """
    if await previous_version_name_claimed(session, name) or await relation_present(
        session, schema, name
    ):
        raise _name_taken(dataset)


async def require_unclaimed_previous_version_name(
    session: AsyncSession, dataset: Any, name: str
) -> None:
    """Refuse when a catalog dataset uses ``name``, a kept table the swap would publish."""
    if await previous_version_name_claimed(session, name):
        raise _name_taken(dataset)


# The live version's row, written from the dataset when a first import left
# none, and otherwise given the facts it was written without. A restore row's
# source CRS is left alone: a restore made before restores reinstated it left
# the dataset naming the replaced file's.
_RECORD_LIVE_VERSION = text(
    """
    INSERT INTO catalog.dataset_versions AS v (
        dataset_id, version_number, source_filename, source_format,
        feature_count, srid, geometry_type, file_hash, original_srid, is_3d,
        n_dims, column_info, uploaded_by, uploaded_at
    )
    SELECT d.id, d.current_version, d.source_filename, d.source_format,
        d.feature_count, d.srid, d.geometry_type,
        CASE WHEN d.origin_ref->>'kind' = 'upload'
            THEN d.origin_ref->>'file_hash' END,
        d.original_srid, d.is_3d, d.n_dims, d.column_info, r.created_by, r.created_at
    FROM catalog.datasets d
    JOIN catalog.records r ON r.id = d.record_id
    WHERE d.id = :dataset_id
    ON CONFLICT (dataset_id, version_number) DO UPDATE SET
        original_srid = COALESCE(
            v.original_srid,
            CASE WHEN v.restored_from_version IS NULL
                THEN EXCLUDED.original_srid END
        ),
        is_3d = COALESCE(v.is_3d, EXCLUDED.is_3d),
        n_dims = COALESCE(v.n_dims, EXCLUDED.n_dims),
        column_info = COALESCE(v.column_info, EXCLUDED.column_info)
    """
)


async def record_live_version(session: AsyncSession, dataset: Any) -> None:
    """Make the live version's row describe the data a swap is about to keep.

    Call holding the catalog rows, before the projection moves the dataset's
    columns on to the incoming data: a restore of the kept version reads its
    source fields, source CRS and dimensionality back from this row.
    """
    await session.execute(_RECORD_LIVE_VERSION, {"dataset_id": dataset.id})


async def stamp_kept_versions(
    session: AsyncSession, dataset: Any, version_number: int
) -> None:
    """Record the table the swap kept ``version_number`` in, and forget kept tables that are gone.

    A kept version is forgotten once its table is gone, which a swap does by
    dropping it or publishing it, or once a catalog dataset uses its name.
    Call after the swap and ``record_live_version``, in their transaction,
    holding the catalog rows, and before ``last_refreshed_at`` is moved on: it
    records the replaced data's.
    """
    schema = _current_tenant_schema()
    name = previous_version_table(dataset.table_name, dataset.id, version_number)
    size = await session.scalar(
        text("SELECT pg_total_relation_size(to_regclass(:kept))"),
        {"kept": _qtable(name, schema=schema)},
    )
    if size is not None:
        await session.execute(
            text(
                "UPDATE catalog.dataset_versions SET kept_table = :name, "
                "kept_at = now(), kept_bytes = :size, kept_refreshed_at = :refreshed "
                "WHERE dataset_id = :dataset_id AND version_number = :number"
            ),
            {
                "name": name,
                "size": size,
                "refreshed": dataset.last_refreshed_at,
                "dataset_id": dataset.id,
                "number": version_number,
            },
        )
    await session.execute(_FORGET_MISSING, {"dataset_id": dataset.id, "schema": schema})


_FORGET_MISSING = text(
    """
    UPDATE catalog.dataset_versions v SET kept_table = NULL, kept_at = NULL,
        kept_bytes = NULL, kept_refreshed_at = NULL
    WHERE v.dataset_id = :dataset_id AND v.kept_table IS NOT NULL
      AND (
        NOT EXISTS (
            SELECT 1 FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema AND c.relname = v.kept_table
        )
        OR EXISTS (
            SELECT 1 FROM catalog.datasets o WHERE o.table_name = v.kept_table
        )
      )
    """
)
