"""Reads of pg_catalog about tables: whether one exists, and what depends on it."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Every object outside the table, or a partition under it, that records an
# ordinary dependency on it or its row type by oid: views, routine bodies, foreign keys and
# row-security policies among them. A rename leaves each reading the renamed
# table. The table's own rules, constraints, policies and triggers, and its
# indexes and owned sequences (auto dependencies), move with it.
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
    ),
    -- A table is also depended on through its row type and that type's array.
    referenced AS (
        SELECT 'pg_class'::regclass AS refclassid, oid AS refobjid FROM tree
        UNION
        SELECT 'pg_type'::regclass, c.reltype FROM pg_class c
        WHERE c.oid IN (SELECT oid FROM tree)
        UNION
        SELECT 'pg_type'::regclass, ty.typarray FROM pg_class c
        JOIN pg_type ty ON ty.oid = c.reltype
        WHERE c.oid IN (SELECT oid FROM tree) AND ty.typarray <> 0
    )
    SELECT DISTINCT pg_describe_object(d.classid, d.objid, 0)
    FROM referenced
    JOIN pg_depend d
      ON d.refobjid = referenced.refobjid AND d.refclassid = referenced.refclassid
     AND d.deptype = 'n'
    WHERE NOT (
        (d.classid = 'pg_class'::regclass AND d.objid IN (SELECT oid FROM tree))
        OR (d.classid = 'pg_rewrite'::regclass AND EXISTS (
            SELECT 1 FROM pg_rewrite r
            WHERE r.oid = d.objid AND r.ev_class IN (SELECT oid FROM tree)))
        OR (d.classid = 'pg_constraint'::regclass AND EXISTS (
            SELECT 1 FROM pg_constraint c
            WHERE c.oid = d.objid AND c.conrelid IN (SELECT oid FROM tree)))
        OR (d.classid = 'pg_policy'::regclass AND EXISTS (
            SELECT 1 FROM pg_policy p
            WHERE p.oid = d.objid AND p.polrelid IN (SELECT oid FROM tree)))
        OR (d.classid = 'pg_trigger'::regclass AND EXISTS (
            SELECT 1 FROM pg_trigger g
            WHERE g.oid = d.objid AND g.tgrelid IN (SELECT oid FROM tree)))
    )
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
    """Descriptions of the objects outside *table* that depend on it, sorted."""
    rows = await session.execute(
        _DEPENDENT_RELATIONS, {"schema": schema, "table": table}
    )
    return [row[0] for row in rows]
