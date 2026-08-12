"""A physical table name freed by a delete must never be handed out again.

fix(#1443). ``generate_table_name`` collided only against LIVE catalog rows
and LIVE relations, and a delete clears both — so the name of a deleted dataset
went straight back into circulation. GH-1429 keyed tile BYTES on the dataset id,
which cannot reach the tile router's ``table_name -> metadata`` map: the vector
tile route is addressed by table name, the dataset id is the result of that
lookup, and the cached entry is what decides authorization. On the checked-in
two-worker default, a worker that never saw the delete authorizes an anonymous
caller against the deleted dataset's ``public`` visibility and then queries a
table its private successor now owns.

Propagation is unavailable in the supported topologies (Redis unset by default;
LISTEN/NOTIFY needs a session-pinned connection transaction-mode PgBouncer does
not give), so the fix removes the precondition rather than chasing the
invalidation: retire the name, and a stale entry can only ever describe the
dataset it was cached for.
"""

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import RetiredTableName
from tests.factories import create_dataset, get_user_id

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


async def _retired_rows(
    session: AsyncSession, table_name: str
) -> list[RetiredTableName]:
    result = await session.execute(
        select(RetiredTableName).where(RetiredTableName.table_name == table_name)
    )
    return list(result.scalars().all())


async def _make_vector_dataset(session: AsyncSession, title: str):
    """A dataset plus the physical table a real vector ingest would have left."""
    from app.processing.ingest.service import generate_table_name

    admin_id = await get_user_id(session, "admin")
    table_name, _ = await generate_table_name(title, session)
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        name=title,
        table_name=table_name,
        record_type="vector_dataset",
    )
    await session.execute(text(f'CREATE TABLE data."{table_name}" (marker integer)'))
    await session.commit()
    return dataset, table_name


class TestNameIsNeverRedrawn:
    async def test_successor_gets_a_suffix_instead_of_the_freed_name(
        self, test_db_session: AsyncSession
    ):
        """Delete A on `roads`, create B with the same title -> B gets `roads_2`."""
        from app.processing.ingest.service import generate_table_name

        title = f"Roads {uuid.uuid4().hex[:6]}"
        dataset_a, first_name = await _make_vector_dataset(test_db_session, title)

        await _delete(test_db_session, dataset_a.id, title)
        await test_db_session.commit()

        second_name, warning = await generate_table_name(title, test_db_session)
        assert second_name == f"{first_name}_2", (
            "the freed name was handed straight back — a tile worker still "
            "holding the deleted dataset's metadata would authorize the "
            "successor's rows against the predecessor's visibility"
        )
        assert warning is not None and second_name in warning

    async def test_retired_name_walks_the_suffix_past_live_collisions(
        self, test_db_session: AsyncSession
    ):
        """A retired name is one more taken name, not a separate rule."""
        from app.processing.ingest.service import generate_table_name

        title = f"Trails {uuid.uuid4().hex[:6]}"
        dataset_a, first_name = await _make_vector_dataset(test_db_session, title)

        await _delete(test_db_session, dataset_a.id, title)
        # A live dataset already sits on the _2 the retirement pushes toward.
        admin_id = await get_user_id(test_db_session, "admin")
        await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"{title} two",
            table_name=f"{first_name}_2",
            record_type="vector_dataset",
        )
        await test_db_session.commit()

        third_name, _ = await generate_table_name(title, test_db_session)
        assert third_name == f"{first_name}_3"

    async def test_unrelated_names_are_untouched(self, test_db_session: AsyncSession):
        """Retiring one name must not push every other slug down a suffix."""
        from app.processing.ingest.service import generate_table_name

        title = f"Rivers {uuid.uuid4().hex[:6]}"
        dataset_a, _ = await _make_vector_dataset(test_db_session, title)
        await _delete(test_db_session, dataset_a.id, title)
        await test_db_session.commit()

        other_title = f"Bridges {uuid.uuid4().hex[:6]}"
        other_name, warning = await generate_table_name(other_title, test_db_session)
        assert not other_name.endswith("_2")
        assert warning is None


class TestGeneratedNamesFitPostgresIdentifiers:
    """fix(#1444 review): a suffix must never push a name past 63 bytes.

    PostgreSQL truncates a longer identifier silently. At a 60-character base,
    `_100` is the first candidate that crosses the limit, and a truncated
    `{base}_100` addresses the same physical relation as `{base}_10` while the
    catalog keeps both untruncated strings — two logical names on one table,
    which hands back exactly the disclosure GH-1443 closes. Before retirement
    that took 99 LIVE datasets sharing one title; retired names accumulate
    forever, so the walk genuinely reaches it.
    """

    async def test_a_three_digit_suffix_trims_the_base_instead_of_overflowing(
        self, test_db_session: AsyncSession
    ):
        from app.processing.ingest.service import (
            _MAX_IDENTIFIER_CHARS,
            generate_table_name,
        )

        base = f"z{uuid.uuid4().hex}{uuid.uuid4().hex}"[:60]
        assert len(base) == 60
        # Retire the base and its first 99 suffixes, which is the state a long
        # enough create/delete history reaches.
        test_db_session.add(RetiredTableName(table_name=base))
        for n in range(2, 100):
            test_db_session.add(RetiredTableName(table_name=f"{base}_{n}"))
        await test_db_session.commit()

        name, warning = await generate_table_name(base, test_db_session)

        assert name == f"{base[:59]}_100"
        assert len(name) == _MAX_IDENTIFIER_CHARS
        assert warning is not None

        # The real proof: Postgres stores it under the name we generated.
        await test_db_session.execute(text(f'CREATE TABLE data."{name}" (m integer)'))
        stored = (
            await test_db_session.execute(
                text(
                    "SELECT c.relname FROM pg_catalog.pg_class c"
                    " JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace"
                    " WHERE n.nspname = 'data' AND c.relname = :n"
                ),
                {"n": name},
            )
        ).scalar_one_or_none()
        await test_db_session.execute(text(f'DROP TABLE data."{name}"'))
        await test_db_session.commit()
        assert stored == name, "PostgreSQL truncated the generated identifier"

    async def test_short_names_keep_their_untrimmed_suffix(
        self, test_db_session: AsyncSession
    ):
        """The trim is length-driven; ordinary names are byte-identical."""
        from app.processing.ingest.service import generate_table_name

        base = f"short_{uuid.uuid4().hex[:8]}"
        test_db_session.add(RetiredTableName(table_name=base))
        await test_db_session.commit()

        name, _ = await generate_table_name(base, test_db_session)
        assert name == f"{base}_2"

    async def test_an_exhausted_namespace_refuses_instead_of_truncating(
        self, test_db_session: AsyncSession, monkeypatch
    ):
        """Past the bound the walk raises; it never emits a truncatable name."""
        from app.processing.ingest import service as ingest_service

        monkeypatch.setattr(ingest_service, "_MAX_COLLISION_SUFFIX", 3)
        base = f"y{uuid.uuid4().hex}{uuid.uuid4().hex}"[:60]
        for taken in (base, f"{base}_2", f"{base}_3", f"{base}_4"):
            test_db_session.add(RetiredTableName(table_name=taken))
        await test_db_session.commit()

        with pytest.raises(ValueError, match="Exhausted table names"):
            await ingest_service.generate_table_name(base, test_db_session)


class TestRecordingSites:
    async def test_vector_delete_records_the_name(self, test_db_session: AsyncSession):
        title = f"Parcels {uuid.uuid4().hex[:6]}"
        dataset, table_name = await _make_vector_dataset(test_db_session, title)
        dataset_id = dataset.id

        await _delete(test_db_session, dataset_id, title)
        await test_db_session.commit()

        rows = await _retired_rows(test_db_session, table_name)
        assert len(rows) == 1
        assert rows[0].dataset_id == dataset_id
        assert rows[0].retired_at is not None

    @pytest.mark.parametrize("record_type", ["raster_dataset", "vrt_dataset"])
    async def test_raster_delete_records_the_name_too(
        self, test_db_session: AsyncSession, record_type: str
    ):
        """The raster branch drops no table, but it still frees the name.

        `_resolve_dataset_meta` caches whatever row a table_name lookup finds
        without filtering on record_type, so a raster dataset's name is as
        cacheable as a vector one and is freed by the same delete.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        title = f"Imagery {uuid.uuid4().hex[:6]}"
        table_name = f"imagery_{uuid.uuid4().hex[:12]}"
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name=title,
            table_name=table_name,
            record_type=record_type,
        )
        await test_db_session.commit()

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        assert len(await _retired_rows(test_db_session, table_name)) == 1

    async def test_delete_endpoint_records_the_name(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The single-delete route commits the tombstone with the delete."""
        title = f"Endpoint {uuid.uuid4().hex[:6]}"
        dataset, table_name = await _make_vector_dataset(test_db_session, title)

        resp = await client.request(
            "DELETE",
            f"/datasets/{dataset.id}",
            json={"confirm_title": title},
            headers=admin_auth_header,
        )
        assert resp.status_code == 204, resp.text

        assert len(await _retired_rows(test_db_session, table_name)) == 1

    async def test_bulk_delete_endpoint_records_every_name(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Bulk delete commits per item, so each item retires its own name."""
        title_one = f"Bulk one {uuid.uuid4().hex[:6]}"
        title_two = f"Bulk two {uuid.uuid4().hex[:6]}"
        ds_one, name_one = await _make_vector_dataset(test_db_session, title_one)
        ds_two, name_two = await _make_vector_dataset(test_db_session, title_two)

        resp = await client.post(
            "/datasets/bulk-delete/",
            json={
                "datasets": [
                    {"dataset_id": str(ds_one.id), "confirm_title": title_one},
                    {"dataset_id": str(ds_two.id), "confirm_title": title_two},
                ]
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted"] == 2

        assert len(await _retired_rows(test_db_session, name_one)) == 1
        assert len(await _retired_rows(test_db_session, name_two)) == 1

    async def test_retirement_rolls_back_with_the_delete(
        self, test_db_session: AsyncSession
    ):
        """No tombstone without the delete it belongs to, and none lost with it.

        The row is written with session.add inside the caller's transaction, so
        the failure direction is a delete that never happened — never a name
        freed with nothing recording it.
        """
        title = f"Rollback {uuid.uuid4().hex[:6]}"
        dataset, table_name = await _make_vector_dataset(test_db_session, title)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.rollback()

        assert await _retired_rows(test_db_session, table_name) == []
        still_there = (
            await test_db_session.execute(
                text("SELECT count(*) FROM catalog.datasets WHERE table_name = :t"),
                {"t": table_name},
            )
        ).scalar_one()
        assert still_there == 1


class TestRegistrationCannotBypassRetirement:
    """fix(#1444 review): registration takes its name from the caller.

    It is the one path that does not go through generate_table_name, so the
    probe has to be repeated there. Recreate a physical table under a deleted
    public dataset's name, register it as private, and a worker still holding
    the predecessor's metadata serves the successor's rows under `public` —
    GH-1443's disclosure through the front door.
    """

    async def test_registering_a_retired_name_is_refused(
        self, test_db_session: AsyncSession
    ):
        from app.processing.ingest.schemas import RegisterRequest
        from app.processing.ingest.service import register_existing_table

        admin_id = await get_user_id(test_db_session, "admin")
        title = f"Registered {uuid.uuid4().hex[:6]}"
        dataset, table_name = await _make_vector_dataset(test_db_session, title)

        await _delete(test_db_session, dataset.id, title)
        await test_db_session.commit()

        # The delete dropped the table; the operator recreates it themselves.
        await test_db_session.execute(
            text(f'CREATE TABLE data."{table_name}" (gid serial primary key)')
        )
        await test_db_session.commit()

        identity = SimpleNamespace(id=admin_id)
        with pytest.raises(ValueError, match="deleted dataset"):
            await register_existing_table(
                test_db_session,
                RegisterRequest(table_name=table_name, title="Successor"),
                identity,
            )
        await test_db_session.rollback()
        await test_db_session.execute(text(f'DROP TABLE data."{table_name}"'))
        await test_db_session.commit()

    async def test_registering_an_untouched_name_still_works(
        self, test_db_session: AsyncSession
    ):
        """The refusal is scoped to retired names, not to registration."""
        from app.processing.ingest.schemas import RegisterRequest
        from app.processing.ingest.service import register_existing_table

        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"never_retired_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(f'CREATE TABLE data."{table_name}" (gid serial primary key)')
        )
        await test_db_session.commit()

        identity = SimpleNamespace(id=admin_id)
        dataset = await register_existing_table(
            test_db_session,
            RegisterRequest(table_name=table_name, title=f"Fresh {table_name}"),
            identity,
        )
        assert dataset.table_name == table_name
        await test_db_session.commit()


class TestRecordingSiteEnumeration:
    """Exactly one site retires a name, and it is the dataset delete.

    Every other DROP under backend/app/ frees a name no `catalog.datasets` row
    ever carried — attempt-scoped ingest staging tables, the `{table}_old`
    intermediate inside the reupload swap, and analysis output tables dropped
    only when the adoption probe says no dataset claimed them. The tile
    router's metadata map is populated from `catalog.datasets` alone, so a name
    no row ever carried was never cacheable and retiring it would buy nothing
    while permanently burning a slug after every failed ingest attempt.
    """

    def test_only_delete_dataset_constructs_a_tombstone(self):
        sites: list[str] = []
        for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "RetiredTableName"
                ):
                    sites.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")

        assert len(sites) == 1, (
            "a new site retires a table name. Retiring is for names a LIVE "
            f"catalog.datasets row carried; confirm this one qualifies: {sites}"
        )
        assert sites[0].startswith(
            "app/modules/catalog/datasets/domain/service_lifecycle.py"
        ), sites


class TestSchema:
    async def test_migration_leaves_the_table_and_its_index_at_head(
        self, test_db_session: AsyncSession
    ):
        """The suite's DB is built by running the chain, so this asserts head."""
        columns = dict(
            (
                await test_db_session.execute(
                    text(
                        "SELECT column_name, is_nullable FROM information_schema.columns"
                        " WHERE table_schema = 'catalog'"
                        "   AND table_name = 'retired_table_names'"
                    )
                )
            ).all()
        )
        assert columns == {
            "id": "NO",
            "table_name": "NO",
            "tenant_id": "YES",
            "dataset_id": "YES",
            "retired_at": "NO",
        }

        index_names = (
            (
                await test_db_session.execute(
                    text(
                        "SELECT indexname FROM pg_indexes"
                        " WHERE schemaname = 'catalog'"
                        "   AND tablename = 'retired_table_names'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(index_names) == {
            "retired_table_names_pkey",
            "ix_retired_table_names_table_name",
        }

    async def test_the_same_name_may_be_retired_more_than_once(
        self, test_db_session: AsyncSession
    ):
        """No unique constraint, so a repeat retirement can never fail a delete.

        Nothing promises a name reaches this table once — a future recording
        site, an operator insert, a restore that merges two catalogs. Uniqueness
        would turn any of those into a failed delete, which is the one outcome
        this table must not cause, and it would buy nothing: the probe is a set
        membership test.
        """
        table_name = f"readopted_{uuid.uuid4().hex[:12]}"
        for _ in range(2):
            test_db_session.add(RetiredTableName(table_name=table_name))
        await test_db_session.commit()

        count = (
            await test_db_session.execute(
                select(func.count())
                .select_from(RetiredTableName)
                .where(RetiredTableName.table_name == table_name)
            )
        ).scalar_one()
        assert count == 2
