"""A tombstone must carry the identity of the relation whose name it freed.

fix(#1456). ``catalog.retired_table_names`` recorded only the freed NAME. That
cannot tell "the table I detached" from "a new table wearing its name", and it
says nothing about who owned the dataset that held it. Both answers have to be
read inside the delete transaction, because both of their sources die in it:
the relation is dropped, and the ``catalog.records`` row carrying ``created_by``
is deleted. Neither can be reconstructed afterwards, which is why the recording
lands before anything reads it.

This is a data-carrying change only. Nothing consumes the two columns yet and
the tombstone-vs-not decision is untouched — the unchanged paths are pinned
here as hard as the new fields, because the whole claim of the change is that
it altered no behaviour on the way in.
"""

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import (
    DetachedRelation,
    RetiredTableName,
)
from app.processing.ingest.schemas import RegisterRequest
from app.processing.ingest.service import register_existing_table
from tests.factories import create_dataset

BACKEND_ROOT = Path(__file__).resolve().parent.parent


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


async def _tombstones(session: AsyncSession, table_name: str) -> list[RetiredTableName]:
    result = await session.execute(
        select(RetiredTableName).where(RetiredTableName.table_name == table_name)
    )
    return list(result.scalars().all())


async def _one_tombstone(session: AsyncSession, table_name: str) -> RetiredTableName:
    rows = await _tombstones(session, table_name)
    assert len(rows) == 1, f"expected exactly one tombstone for {table_name}: {rows}"
    return rows[0]


async def _detach_records(
    session: AsyncSession, table_name: str
) -> list[DetachedRelation]:
    result = await session.execute(
        select(DetachedRelation).where(DetachedRelation.table_name == table_name)
    )
    return list(result.scalars().all())


async def _live_oid(session: AsyncSession, table_name: str) -> int | None:
    """The oid pg_class currently holds for this name, read independently.

    Deliberately not the production probe — comparing delete_dataset's answer
    against its own helper would pass whatever that helper returned.
    """
    result = await session.execute(
        text(
            "SELECT c.oid FROM pg_catalog.pg_class c"
            " JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = 'data' AND c.relname = :t"
        ).bindparams(t=table_name)
    )
    oid = result.scalar()
    return None if oid is None else int(oid)


async def _make_user(session: AsyncSession) -> uuid.UUID:
    """A fresh owner, so the recorded id can only have come from the record."""
    from app.modules.auth.models import User

    user = User(id=uuid.uuid4(), username=f"owner_{uuid.uuid4().hex[:10]}")
    session.add(user)
    await session.commit()
    return user.id


async def _ingested_dataset(session: AsyncSession, title: str, owner: uuid.UUID):
    """A dataset plus the physical table a real vector ingest would leave."""
    from app.processing.ingest.service import generate_table_name

    table_name, _ = await generate_table_name(title, session)
    dataset = await create_dataset(
        session,
        created_by=owner,
        name=title,
        table_name=table_name,
        record_type="vector_dataset",
        source_format="geojson",
    )
    await session.execute(text(f'CREATE TABLE data."{table_name}" (marker integer)'))
    await session.commit()
    return dataset, table_name


async def _operator_table(session: AsyncSession) -> str:
    """A table the OPERATOR created, which registration only points at."""
    table_name = f"operator_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(f'CREATE TABLE data."{table_name}" (gid serial primary key, note text)')
    )
    await session.commit()
    return table_name


async def _register(session: AsyncSession, table_name: str, title: str, owner):
    dataset = await register_existing_table(
        session,
        RegisterRequest(table_name=table_name, title=title),
        SimpleNamespace(id=owner),
    )
    await session.commit()
    return dataset


class TestTheDroppedRelationIsIdentified:
    """The DROP path is the one that frees a relation GeoLens can still see."""

    async def test_the_recorded_oid_is_the_relation_the_delete_dropped(
        self, test_db_session: AsyncSession
    ):
        """Also pins the probe's POSITION, not just its result.

        The oid is only readable before the DROP: afterwards the pg_class row
        is gone inside the same transaction. A probe moved below the DROP
        would record NULL here and the delete would still succeed, so this
        equality is the only thing standing between the ordering and a silent
        regression to a column full of nulls.
        """
        owner = await _make_user(test_db_session)
        title = f"Parcels {uuid.uuid4().hex[:6]}"
        dataset, table_name = await _ingested_dataset(test_db_session, title, owner)

        oid_before = await _live_oid(test_db_session, table_name)
        assert oid_before is not None, "the fixture never created the table"

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        assert await _live_oid(test_db_session, table_name) is None, (
            "the table survived a delete that owns it — this test is measuring "
            "the wrong path"
        )
        row = await _one_tombstone(test_db_session, table_name)
        assert row.relation_oid == oid_before

    async def test_the_recorded_owner_is_the_datasets_creator(
        self, test_db_session: AsyncSession
    ):
        """A fresh user, so a stray admin id could not pass by coincidence."""
        owner = await _make_user(test_db_session)
        title = f"Owned {uuid.uuid4().hex[:6]}"
        dataset, table_name = await _ingested_dataset(test_db_session, title, owner)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        row = await _one_tombstone(test_db_session, table_name)
        assert row.previous_owner_id == owner
        assert row.dataset_id == dataset.id

    async def test_an_ownerless_dataset_records_a_null_owner(
        self, test_db_session: AsyncSession
    ):
        """``records.created_by`` is nullable and NULL survives as NULL.

        Nothing substitutes a caller or an admin for a missing owner: the
        column answers "who owned it", and inventing an answer would be worse
        than not having one.
        """
        title = f"Ownerless {uuid.uuid4().hex[:6]}"
        dataset, table_name = await _ingested_dataset(test_db_session, title, None)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        row = await _one_tombstone(test_db_session, table_name)
        assert row.previous_owner_id is None


class TestADetachWhoseTableAlreadyVanished:
    """The registered path that still frees the name (fix(#1452) round 1).

    The relation is already gone when the delete runs, so there is no identity
    left to record — the honest oid is NULL. The owner is not lost with it,
    and that is the half the issue called unrecoverable after the fact.
    """

    async def test_the_owner_is_recorded_although_no_relation_survives(
        self, test_db_session: AsyncSession
    ):
        owner = await _make_user(test_db_session)
        table_name = await _operator_table(test_db_session)
        title = f"Vanished {uuid.uuid4().hex[:6]}"
        dataset = await _register(test_db_session, table_name, title, owner)

        # The operator drops their own table behind GeoLens's back.
        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        row = await _one_tombstone(test_db_session, table_name)
        assert row.previous_owner_id == owner
        assert row.relation_oid is None, (
            "an oid was recorded for a relation that was already gone — the "
            "column would then be asserting an identity nothing verified"
        )

    async def test_no_detach_record_is_written_when_nothing_survived(
        self, test_db_session: AsyncSession
    ):
        """A detach record claims a relation is still standing. None is."""
        owner = await _make_user(test_db_session)
        table_name = await _operator_table(test_db_session)
        title = f"Vanished {uuid.uuid4().hex[:6]}"
        dataset = await _register(test_db_session, table_name, title, owner)

        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        assert await _detach_records(test_db_session, table_name) == []


class TestASurvivingDetachRecordsWhatItReleased:
    """fix(#1456 codex round 1): the path GH-1456's window 1 actually lives on.

    A detach that leaves the operator's table standing frees no name, so it
    writes no tombstone. Before this, that meant the probed oid and the owner
    were read and thrown away on the one path where the residual exists: if the
    operator drops that relation after the delete commits, the name goes free
    with nothing recorded anywhere, and neither value can be recovered.
    """

    async def test_the_released_relation_is_recorded_with_its_live_oid(
        self, test_db_session: AsyncSession
    ):
        owner = await _make_user(test_db_session)
        table_name = await _operator_table(test_db_session)
        title = f"Released {uuid.uuid4().hex[:6]}"
        dataset = await _register(test_db_session, table_name, title, owner)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        records = await _detach_records(test_db_session, table_name)
        assert len(records) == 1
        assert records[0].relation_oid == await _live_oid(test_db_session, table_name)
        assert records[0].previous_owner_id == owner
        assert records[0].dataset_id == dataset.id

        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()

    async def test_the_record_does_not_retire_the_name(
        self, test_db_session: AsyncSession
    ):
        """The reason it is a sibling table and not a flag on the tombstone.

        The retirement set's whole API is membership: a name in it is never
        handed out again, and ``register_existing_table`` refuses it outright.
        The operator's table is still theirs to re-register, so this record has
        to be invisible to both of those readers, which it is by construction
        rather than by anyone remembering a predicate.
        """
        from app.processing.ingest.service import generate_table_name

        owner = await _make_user(test_db_session)
        table_name = await _operator_table(test_db_session)
        title = f"Readopt {uuid.uuid4().hex[:6]}"
        dataset = await _register(test_db_session, table_name, title, owner)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()
        assert len(await _detach_records(test_db_session, table_name)) == 1

        # Registration must still accept the operator's own surviving table.
        readopted = await _register(
            test_db_session, table_name, f"Readopted {uuid.uuid4().hex[:6]}", owner
        )
        assert readopted.table_name == table_name

        # And the collision walk must refuse it for the reason it always did —
        # a live relation occupies it — not because a record retired it.
        redrawn, _ = await generate_table_name(table_name, test_db_session)
        assert redrawn == f"{table_name}_2"

        await _delete(test_db_session, readopted.id, readopted.record.title)
        await test_db_session.commit()
        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()

    async def test_a_dropped_table_writes_no_detach_record(
        self, test_db_session: AsyncSession
    ):
        """The owning path releases nothing: it destroys the relation."""
        owner = await _make_user(test_db_session)
        title = f"Ingested {uuid.uuid4().hex[:6]}"
        dataset, table_name = await _ingested_dataset(test_db_session, title, owner)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        assert await _detach_records(test_db_session, table_name) == []
        assert len(await _tombstones(test_db_session, table_name)) == 1

    def test_only_delete_dataset_constructs_a_detach_record(self):
        """One write site, matching the tombstone's own enumeration.

        A second one would mean something other than a dataset delete claims
        GeoLens released a relation, which is not a claim any other path is in
        a position to make.
        """
        sites: list[str] = []
        for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "DetachedRelation"
                ):
                    sites.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")

        assert len(sites) == 1, sites
        assert sites[0].startswith(
            "app/modules/catalog/datasets/domain/service_lifecycle.py"
        ), sites


class TestNothingElseChanged:
    """The tombstone-vs-not decision is exactly what it was before #1456."""

    async def test_a_surviving_detached_table_still_writes_no_tombstone(
        self, test_db_session: AsyncSession
    ):
        """The probe now also reads an oid on this path, and must not use it.

        Recording a tombstone here would make the operator's own table
        permanently unregisterable, which is the whole reason fix(#1452) reads
        the relation rather than the origin.
        """
        owner = await _make_user(test_db_session)
        table_name = await _operator_table(test_db_session)
        title = f"Surviving {uuid.uuid4().hex[:6]}"
        dataset = await _register(test_db_session, table_name, title, owner)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        assert await _tombstones(test_db_session, table_name) == []
        assert await _live_oid(test_db_session, table_name) is not None

        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()

    async def test_an_ingested_delete_still_drops_and_still_retires(
        self, test_db_session: AsyncSession
    ):
        owner = await _make_user(test_db_session)
        title = f"Ingested {uuid.uuid4().hex[:6]}"
        dataset, table_name = await _ingested_dataset(test_db_session, title, owner)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        assert await _live_oid(test_db_session, table_name) is None
        assert len(await _tombstones(test_db_session, table_name)) == 1

    async def test_a_raster_delete_records_no_relation_identity(
        self, test_db_session: AsyncSession
    ):
        """The raster branch never had a relation to identify.

        A raster dataset's table_name is the synthetic ``raster_<hex>`` and
        names nothing in the data schema, so that branch is not probed at all.
        Its name is still freed by the delete, so the tombstone is still
        written — with the owner, and with a NULL oid.
        """
        owner = await _make_user(test_db_session)
        title = f"Imagery {uuid.uuid4().hex[:6]}"
        table_name = f"raster_{uuid.uuid4().hex[:16]}"
        dataset = await create_dataset(
            test_db_session,
            created_by=owner,
            name=title,
            table_name=table_name,
            record_type="raster_dataset",
        )
        await test_db_session.commit()

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        row = await _one_tombstone(test_db_session, table_name)
        assert row.relation_oid is None
        assert row.previous_owner_id == owner


class TestTheColumnsCannotBreakADelete:
    """Both are nullable and neither carries a foreign key, deliberately.

    This table's one hard rule is that it must never be the reason a delete
    fails, and every tombstone written before #1456 has to stay valid — no
    backfill is possible, since both sources were already gone when those rows
    were written.
    """

    async def test_a_tombstone_with_neither_identity_column_is_accepted(
        self, test_db_session: AsyncSession
    ):
        """The shape of every pre-existing row, and of an operator insert."""
        table_name = f"legacy_{uuid.uuid4().hex[:12]}"
        test_db_session.add(RetiredTableName(table_name=table_name))
        await test_db_session.commit()

        row = await _one_tombstone(test_db_session, table_name)
        assert row.relation_oid is None
        assert row.previous_owner_id is None

    async def test_no_foreign_key_reaches_out_of_this_table(
        self, test_db_session: AsyncSession
    ):
        """An FK on previous_owner_id gives only bad options.

        CASCADE erases tombstones when a user is deleted, re-arming GH-1443
        for every name their datasets freed; RESTRICT lets a retain-forever
        row block a user deletion; SET NULL silently discards the durable half
        of the identity.
        """
        fks = (
            (
                await test_db_session.execute(
                    text(
                        "SELECT conname FROM pg_constraint"
                        " WHERE conrelid = 'catalog.retired_table_names'::regclass"
                        "   AND contype = 'f'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert list(fks) == []

    async def test_deleting_the_prior_owner_leaves_the_tombstone_intact(
        self, test_db_session: AsyncSession
    ):
        """The property the missing FK buys, asked of the database itself."""
        from app.modules.auth.models import User

        owner = await _make_user(test_db_session)
        title = f"Departing {uuid.uuid4().hex[:6]}"
        dataset, table_name = await _ingested_dataset(test_db_session, title, owner)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        await test_db_session.execute(
            text("DELETE FROM catalog.users WHERE id = :id").bindparams(id=owner)
        )
        await test_db_session.commit()

        survivors = (
            await test_db_session.execute(
                select(func.count())
                .select_from(RetiredTableName)
                .where(RetiredTableName.table_name == table_name)
                .where(RetiredTableName.previous_owner_id == owner)
            )
        ).scalar_one()
        assert survivors == 1, (
            "the tombstone followed its owner out — the name is redrawable "
            "again and GH-1443 is re-armed"
        )
        assert (
            await test_db_session.execute(
                select(func.count()).select_from(User).where(User.id == owner)
            )
        ).scalar_one() == 0, "the tombstone blocked the user deletion"
