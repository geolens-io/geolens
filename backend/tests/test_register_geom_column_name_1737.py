"""fix(#1737): a spatial table whose geometry column is not named `geom`
must be refused at registration, not catalogued as a non-spatial table.

``register_existing_table`` decides "is this spatial?" by looking for the
exact names ``geom``/``geom_4326``. Anything else left ``has_geom`` false,
skipped the whole ``add_4326_column`` branch, and let registration finish:
``extract_metadata`` reports srid, geometry_type and extent as None for a
column it does not recognize, so the dataset was created as an attribute
table with no error anywhere. Discovery does not filter these out either
(its ``geometry_columns`` join is a LEFT JOIN pinned to ``f_geometry_column
= 'geom'``), so the table looks legitimately non-spatial in the picker.

``ogr2ogr -f PostgreSQL`` names its geometry column ``wkb_geometry`` by
default, which made the most ordinary way of landing a table in the data
schema produce a dataset that renders nothing.

The non-spatial registration path is deliberate (#1359), so the fix has to
separate "geometry under another name" from "no geometry at all" rather
than tightening registration for every table. Both halves are pinned here.
"""

import uuid as _uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import get_user_id


@pytest.mark.anyio
async def test_register_refuses_geometry_column_under_another_name(
    test_db_session: AsyncSession,
):
    """The ogr2ogr default (`wkb_geometry`) is refused, and named."""
    from app.processing.ingest.schemas import RegisterRequest
    from app.processing.ingest.service import register_existing_table

    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"tbl_wkbgeom_{_uuid.uuid4().hex[:10]}"

    await test_db_session.execute(
        text(
            f'CREATE TABLE data."{table_name}" '
            f"(gid serial PRIMARY KEY, name text, "
            f"wkb_geometry geometry(Point, 4326))"
        )
    )
    await test_db_session.execute(
        text(
            f'INSERT INTO data."{table_name}" (name, wkb_geometry) '  # noqa: S608
            f"VALUES ('a', ST_SetSRID(ST_MakePoint(-73.9, 40.7), 4326))"
        )
    )
    await test_db_session.commit()

    try:
        with pytest.raises(ValueError) as excinfo:
            await register_existing_table(
                test_db_session,
                RegisterRequest(table_name=table_name, title="Wkb Geometry"),
                SimpleNamespace(id=admin_id),
            )

        message = str(excinfo.value)
        # The offending column has to be IN the message: "rename it" with no
        # name sends the operator back to psql to work out which column.
        assert "wkb_geometry" in message
        assert "geom" in message
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text(f'DROP TABLE IF EXISTS data."{table_name}" CASCADE')
        )
        await test_db_session.commit()


@pytest.mark.anyio
async def test_register_still_accepts_a_table_with_no_geometry(
    test_db_session: AsyncSession,
):
    """The #1359 attribute-table path is the boundary the refusal must not cross.

    A table with no geometry column anywhere has no ``geometry_columns`` row,
    so the new probe finds nothing and registration proceeds exactly as it
    did. Pinned next to the refusal because the two answers come from one
    branch, and a probe that matched too widely would turn every non-spatial
    registration into an error.
    """
    from app.processing.ingest.schemas import RegisterRequest
    from app.processing.ingest.service import register_existing_table

    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"tbl_noge_{_uuid.uuid4().hex[:10]}"

    await test_db_session.execute(
        text(
            f'CREATE TABLE data."{table_name}" '
            f"(gid serial PRIMARY KEY, code text, population integer)"
        )
    )
    await test_db_session.execute(
        text(
            f'INSERT INTO data."{table_name}" (code, population) '  # noqa: S608
            f"VALUES ('a', 1)"
        )
    )
    await test_db_session.commit()

    try:
        dataset = await register_existing_table(
            test_db_session,
            RegisterRequest(table_name=table_name, title="No Geometry"),
            SimpleNamespace(id=admin_id),
        )
        await test_db_session.commit()

        assert dataset.geometry_type is None
        assert dataset.feature_count == 1
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text(f'DROP TABLE IF EXISTS data."{table_name}" CASCADE')
        )
        await test_db_session.commit()
