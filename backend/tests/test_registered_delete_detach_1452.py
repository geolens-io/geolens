"""Deleting a REGISTERED dataset must detach, never drop.

fix(#1452). ``register_existing_table`` points the catalog at a table the
operator built, and registration copies no data — the dataset row is a
reference, not a managed copy. ``delete_dataset``'s vector branch dropped it
anyway, so removing a catalog entry destroyed the operator's original.

The two halves of the contract are tested here together because they are one
answer with two effects: GeoLens drops the table AND retires its name when it
created the table (ingest, analysis output), and does NEITHER when it did not.
Retiring a detached name would be worse than pointless — ``register_existing_table``
refuses a retired name, so it would leave the operator holding a table their own
catalog can never accept again.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import RetiredTableName
from app.platform.dataset_origin import geolens_owns_table
from app.processing.ingest.schemas import RegisterRequest
from app.processing.ingest.service import register_existing_table
from tests.factories import create_dataset, get_user_id


class _MockStorage:
    """delete_dataset reaps originals/ and vectors/; nothing is staged here."""

    async def list(self, prefix: str) -> list[str]:
        return []

    async def delete(self, key: str) -> None:  # pragma: no cover - nothing listed
        raise AssertionError("no keys were listed")


async def _delete(session: AsyncSession, dataset_id: uuid.UUID, title: str) -> str:
    from app.modules.catalog.datasets.domain.service import delete_dataset

    with patch(
        "app.platform.storage.provider.get_storage", return_value=_MockStorage()
    ):
        return await delete_dataset(session, dataset_id, title)


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    result = await session.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'data' AND c.relname = :t)"
        ).bindparams(t=table_name)
    )
    return bool(result.scalar())


async def _retired_count(session: AsyncSession, table_name: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(RetiredTableName)
        .where(RetiredTableName.table_name == table_name)
    )
    return int(result.scalar_one())


async def _operator_table(session: AsyncSession, rows: int = 3) -> str:
    """A table the OPERATOR created, with rows GeoLens never copied."""
    table_name = f"operator_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(f'CREATE TABLE data."{table_name}" (gid serial primary key, note text)')
    )
    await session.execute(
        text(
            f'INSERT INTO data."{table_name}" (note) SELECT g::text '
            f"FROM generate_series(1, :n) g"
        ).bindparams(n=rows)
    )
    await session.commit()
    return table_name


async def _spatial_operator_table(session: AsyncSession, rows: int = 2) -> str:
    """An operator table with a geom column, so registration adds geom_4326."""
    table_name = f"operator_geo_{uuid.uuid4().hex[:10]}"
    await session.execute(
        text(
            f'CREATE TABLE data."{table_name}" '
            f"(gid serial primary key, geom geometry(Point, 4326))"
        )
    )
    await session.execute(
        text(
            f'INSERT INTO data."{table_name}" (geom) '
            f"SELECT ST_SetSRID(ST_MakePoint(g, g), 4326) "
            f"FROM generate_series(1, :n) g"
        ).bindparams(n=rows)
    )
    await session.commit()
    return table_name


async def _column_names(session: AsyncSession, table_name: str) -> set[str]:
    result = await session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'data' AND table_name = :t"
        ).bindparams(t=table_name)
    )
    return {row[0] for row in result.all()}


async def _register(
    session: AsyncSession, table_name: str, title: str, *, managed: bool = False
):
    admin_id = await get_user_id(session, "admin")
    dataset = await register_existing_table(
        session,
        RegisterRequest(table_name=table_name, title=title),
        SimpleNamespace(id=admin_id),
        managed=managed,
    )
    await session.commit()
    return dataset


class TestRegisteredDeleteDetaches:
    async def test_delete_leaves_the_operators_table_and_its_rows_alone(
        self, test_db_session: AsyncSession
    ):
        table_name = await _operator_table(test_db_session, rows=3)
        title = f"Registered {uuid.uuid4().hex[:6]}"
        dataset = await _register(test_db_session, table_name, title)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        assert await _table_exists(test_db_session, table_name), (
            "the delete dropped a table GeoLens never created — registration "
            "copies no data, so this destroyed the operator's original"
        )
        surviving = await test_db_session.execute(
            text(f'SELECT count(*) FROM data."{table_name}"')
        )
        assert surviving.scalar_one() == 3, "rows were deleted out of a detached table"

        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()

    async def test_a_spatial_table_keeps_its_geometry_and_the_added_4326_column(
        self, test_db_session: AsyncSession
    ):
        """Detach leaves the table as REGISTRATION left it, not as it was born.

        Registration adds ``geom_4326`` and its index to a table that has a
        geom column. Delete undoes none of that: dropping the column would
        rewrite the operator's table under a lock to remove something
        harmless, and re-registering re-adds it idempotently anyway.
        """
        table_name = await _spatial_operator_table(test_db_session, rows=2)
        title = f"Spatial {uuid.uuid4().hex[:6]}"
        dataset = await _register(test_db_session, table_name, title)
        assert "geom_4326" in await _column_names(test_db_session, table_name)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        assert await _table_exists(test_db_session, table_name)
        assert {"gid", "geom", "geom_4326"} <= await _column_names(
            test_db_session, table_name
        )
        surviving = await test_db_session.execute(
            text(f'SELECT count(*) FROM data."{table_name}" WHERE geom IS NOT NULL')
        )
        assert surviving.scalar_one() == 2

        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()

    async def test_the_catalog_row_and_its_grants_are_gone(
        self, test_db_session: AsyncSession
    ):
        """Detach is about the TABLE. Everything catalog-side still goes."""
        from app.modules.catalog.datasets.domain.models import Dataset

        table_name = await _operator_table(test_db_session)
        title = f"Registered {uuid.uuid4().hex[:6]}"
        dataset = await _register(test_db_session, table_name, title)
        dataset_id = dataset.id

        await _delete(test_db_session, dataset_id, title)
        await test_db_session.commit()

        remaining = await test_db_session.execute(
            select(func.count()).select_from(Dataset).where(Dataset.id == dataset_id)
        )
        assert remaining.scalar_one() == 0

        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()

    async def test_the_name_is_not_retired_so_the_table_can_be_registered_again(
        self, test_db_session: AsyncSession
    ):
        """The whole point of leaving the table: the operator can re-adopt it.

        ``register_existing_table`` refuses a retired name (fix #1444), so a
        tombstone here would strand the operator's own table permanently.
        """
        table_name = await _operator_table(test_db_session)
        title = f"Registered {uuid.uuid4().hex[:6]}"
        dataset = await _register(test_db_session, table_name, title)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        assert await _retired_count(test_db_session, table_name) == 0, (
            "a detached name was tombstoned — nothing was freed, and the "
            "operator can now never re-register their own table"
        )

        second = await _register(
            test_db_session, table_name, f"Re-registered {uuid.uuid4().hex[:6]}"
        )
        assert second.table_name == table_name
        assert second.id != dataset.id

        await _delete(test_db_session, second.id, second.record.title)
        await test_db_session.commit()
        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()


class TestDetachOfAnAlreadyMissingTableStillRetires:
    """fix(#1452 review round 1): a detach only frees nothing while the
    relation is there to occupy the name.

    A registered dataset whose table the operator already dropped frees its
    name outright. Skipping the tombstone for it reopened GH-1443 through the
    ingest door: nothing kept generate_table_name from handing the name to a
    new dataset while a worker that missed the delete still authorized against
    the deleted one.
    """

    async def test_a_vanished_table_frees_the_name_and_it_is_retired(
        self, test_db_session: AsyncSession
    ):
        table_name = await _operator_table(test_db_session)
        title = f"Vanished {uuid.uuid4().hex[:6]}"
        dataset = await _register(test_db_session, table_name, title)

        # The operator drops their own table behind GeoLens's back.
        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        assert await _retired_count(test_db_session, table_name) == 1, (
            "the name was released with no tombstone — generate_table_name "
            "would hand it to the next ingest while a stale tile worker still "
            "authorizes against the deleted dataset"
        )

    async def test_the_freed_name_is_not_handed_to_a_new_ingest(
        self, test_db_session: AsyncSession
    ):
        """The retirement's actual job, asked through generate_table_name."""
        from app.processing.ingest.service import generate_table_name

        table_name = await _operator_table(test_db_session)
        title = f"Vanished {uuid.uuid4().hex[:6]}"
        dataset = await _register(test_db_session, table_name, title)

        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()
        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        redrawn, _ = await generate_table_name(table_name, test_db_session)
        assert redrawn == f"{table_name}_2", (
            f"the freed name {table_name} was handed straight back to a new "
            "ingest (GH-1443)"
        )

    async def test_a_surviving_table_keeps_its_name_off_new_ingests(
        self, test_db_session: AsyncSession
    ):
        """The other half: the relation itself is what holds the name.

        This is why the detach case can skip the tombstone at all. The name is
        unavailable to ingest either way; only the reason differs.
        """
        from app.processing.ingest.service import generate_table_name

        table_name = await _operator_table(test_db_session)
        title = f"Surviving {uuid.uuid4().hex[:6]}"
        dataset = await _register(test_db_session, table_name, title)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        assert await _retired_count(test_db_session, table_name) == 0
        redrawn, _ = await generate_table_name(table_name, test_db_session)
        assert redrawn == f"{table_name}_2", (
            "generate_table_name drew a name a live relation still occupies"
        )

        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()


class TestIngestedDeleteStillDrops:
    """#1444 must not regress: an ingested table is still dropped and retired."""

    async def test_ingested_delete_drops_the_table_and_retires_the_name(
        self, test_db_session: AsyncSession
    ):
        from app.processing.ingest.service import generate_table_name

        admin_id = await get_user_id(test_db_session, "admin")
        title = f"Ingested {uuid.uuid4().hex[:6]}"
        table_name, _ = await generate_table_name(title, test_db_session)
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=title,
            table_name=table_name,
            record_type="vector_dataset",
            source_format="geojson",
        )
        await test_db_session.execute(
            text(f'CREATE TABLE data."{table_name}" (marker integer)')
        )
        await test_db_session.commit()

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        assert not await _table_exists(test_db_session, table_name), (
            "GeoLens created this table from an upload; delete must reclaim it"
        )
        assert await _retired_count(test_db_session, table_name) == 1

    async def test_a_managed_registration_is_dropped_and_retired(
        self, test_db_session: AsyncSession
    ):
        """The analysis materialize path CTAS's its output, then registers it.

        Same postgis origin and same null source_format as an operator's
        table, so ``managed`` is the only thing that keeps delete reclaiming
        it. Without it every analysis output would leak a table.
        """
        table_name = await _operator_table(test_db_session)
        title = f"Analysis output {uuid.uuid4().hex[:6]}"
        dataset = await _register(test_db_session, table_name, title, managed=True)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        assert not await _table_exists(test_db_session, table_name)
        assert await _retired_count(test_db_session, table_name) == 1


class TestOwnershipRule:
    """``geolens_owns_table`` decides both the DROP and the retirement."""

    @pytest.mark.parametrize(
        "source_format,record_type,origin_ref,owned",
        [
            ("geojson", "vector_dataset", None, True),
            ("shapefile", "vector_dataset", None, True),
            ("created", "vector_dataset", None, True),
            ("wfs", "vector_dataset", None, True),
            ("stac", "raster_dataset", None, True),
            ("geotiff", "raster_dataset", None, True),
            # A raster with no stamped format must not read as registered-in-
            # place. Registration only ever creates vector datasets, so the
            # record type settles it before the origin rule is consulted; the
            # name still gets retired (GH-1443).
            (None, "raster_dataset", None, True),
            (None, "raster_dataset", {"kind": "postgis"}, True),
            # A VRT composes other datasets and classifies as originless. It
            # drops no table, but its catalog name is still freed, so #1444's
            # retirement has to keep firing for it.
            (None, "vrt_dataset", None, True),
            # Registered in place: null source_format IS the postgis origin.
            (None, "vector_dataset", None, False),
            (None, "vector_dataset", {"kind": "postgis"}, False),
            ("", "vector_dataset", {"kind": "postgis", "table_name": "data.x"}, False),
            # Stored false and an absent key mean the same thing, so a row
            # written before the key existed reads as "not ours".
            (None, "vector_dataset", {"kind": "postgis", "managed": False}, False),
            (None, "vector_dataset", {"kind": "postgis", "managed": True}, True),
            # JSONB can hold shapes build_origin_ref never writes, and the
            # caller is one line above a DROP. Only a dict saying managed is
            # ours; a truthy-but-not-True value is not a claim.
            (None, "vector_dataset", "data.parcels", False),
            (None, "vector_dataset", ["postgis"], False),
            (None, "vector_dataset", {"kind": "postgis", "managed": "yes"}, False),
            (None, "vector_dataset", {"kind": "postgis", "managed": None}, False),
        ],
    )
    def test_truth_table(self, source_format, record_type, origin_ref, owned):
        assert geolens_owns_table(source_format, record_type, origin_ref) is owned

    def test_managed_is_ignored_for_every_other_origin(self):
        """`managed` is a postgis-only key; it cannot make an upload unowned."""
        assert geolens_owns_table("geojson", "vector_dataset", {"managed": False})


class TestManagedIsStampedOnlyWhereItIsClaimed:
    async def test_operator_registration_stores_the_pre_1452_ref_shape(
        self, test_db_session: AsyncSession
    ):
        """An unmanaged registration writes exactly what it wrote before.

        ``managed`` is passed as True/None so the key is OMITTED rather than
        stored false — the back catalog and a fresh operator registration are
        then byte-identical, and neither can be misread as managed.
        """
        table_name = await _operator_table(test_db_session)
        dataset = await _register(
            test_db_session, table_name, f"Plain {uuid.uuid4().hex[:6]}"
        )

        assert dataset.origin_ref == {
            "kind": "postgis",
            "table_name": f"data.{table_name}",
        }

        await _delete(test_db_session, dataset.id, dataset.record.title)
        await test_db_session.commit()
        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()

    async def test_managed_registration_stamps_the_ref(
        self, test_db_session: AsyncSession
    ):
        table_name = await _operator_table(test_db_session)
        dataset = await _register(
            test_db_session,
            table_name,
            f"Managed {uuid.uuid4().hex[:6]}",
            managed=True,
        )

        assert dataset.origin_ref == {
            "kind": "postgis",
            "managed": True,
            "table_name": f"data.{table_name}",
        }

        await _delete(test_db_session, dataset.id, dataset.record.title)
        await test_db_session.commit()
