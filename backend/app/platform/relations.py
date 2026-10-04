"""Reads of pg_catalog about tables: whether one exists, and what depends on it."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Views (through their rewrite rules), SQL-standard routine bodies and foreign
# keys elsewhere that hold a table, or a partition under it, by oid. A rename
# leaves them reading the renamed table.
_DEPENDENT_RELATIONS = text(
    """
    WITH target AS (
        SELECT t.oid
        FROM pg_class t
        JOIN pg_namespace tn ON tn.oid = t.relnamespace
        WHERE tn.nspname = :schema AND t.relname = :table
    ),
    -- pg_partition_tree lists nothing for a table that is not partitioned.
    tree AS (
        SELECT oid FROM target
        UNION
        SELECT p.relid FROM target CROSS JOIN LATERAL pg_partition_tree(target.oid) p
    )
    SELECT format('%I.%I', dn.nspname, dc.relname)
    FROM tree
    JOIN pg_depend d
      ON d.refobjid = tree.oid AND d.refclassid = 'pg_class'::regclass
     AND d.classid = 'pg_rewrite'::regclass
    JOIN pg_rewrite r ON r.oid = d.objid
    JOIN pg_class dc ON dc.oid = r.ev_class
    JOIN pg_namespace dn ON dn.oid = dc.relnamespace
    WHERE dc.oid NOT IN (SELECT oid FROM tree)
    UNION
    SELECT d.objid::regprocedure::text
    FROM tree
    JOIN pg_depend d
      ON d.refobjid = tree.oid AND d.refclassid = 'pg_class'::regclass
     AND d.classid = 'pg_proc'::regclass
    UNION
    SELECT format('%I.%I', cn.nspname, cc.relname)
    FROM tree
    JOIN pg_constraint con ON con.confrelid = tree.oid AND con.contype = 'f'
    JOIN pg_class cc ON cc.oid = con.conrelid
    JOIN pg_namespace cn ON cn.oid = cc.relnamespace
    WHERE cc.oid NOT IN (SELECT oid FROM tree)
    ORDER BY 1
    """
)


async def relation_present(session: AsyncSession, schema: str, name: str) -> bool:
    """Whether the relation exists, read at the statement's own snapshot."""
    present = await session.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relname = :name)"
        ),
        {"schema": schema, "name": name},
    )
    return bool(present)


async def dependent_relations(
    session: AsyncSession, schema: str, table: str
) -> list[str]:
    """Other relations and routines that depend on *table*, schema-qualified and sorted."""
    rows = await session.execute(
        _DEPENDENT_RELATIONS, {"schema": schema, "table": table}
    )
    return [row[0] for row in rows]
