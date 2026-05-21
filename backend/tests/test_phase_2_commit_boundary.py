"""Regression test for ING-02 / P2-02: phase-2 metadata helpers must not commit internally.

The four helpers in ``app.processing.ingest.metadata``
(``ensure_geom_column``, ``clip_to_mercator_bounds``, ``add_4326_column``,
``grant_reader_access``) are called from inside ``_finalize_ingest``'s
phase-2 transaction at ``tasks_common.py:821``. If any of them commits
internally, a downstream failure cannot roll back the work — the
forward-only DDL would persist even after ``session.rollback()``.

These tests prove the rollback invariant holds end-to-end by:

1. Showing a phase-2 failure rolls back ``add_4326_column`` (negative test).
2. Showing a successful outer commit makes the column durable
   (positive-control — guards against false positives from spurious
   teardown side-effects in test 1).
3. Showing all four phase-2 helpers pend until the outer commit
   (cross-checked from a separate session that cannot see uncommitted work).
"""

import pytest
from sqlalchemy import text


class TestPhase2CommitBoundary:
    """Test the phase-2 commit boundary contract."""

    @pytest.fixture(autouse=True)
    async def setup_table(self, test_db_session):
        """Create a table fixture with the standard ingest shape.

        Uses the same teardown convention as test_ensure_geom_column.py:
        DROP IF EXISTS the table before and after the test, committing
        each DDL so the table is durably set up / torn down regardless of
        whether the test under test issues its own commit/rollback.
        """
        self.session = test_db_session
        self.table_name = "test_p2_rollback"
        await self.session.execute(
            text(f"DROP TABLE IF EXISTS data.{self.table_name} CASCADE")
        )
        await self.session.commit()
        yield
        await self.session.execute(
            text(f"DROP TABLE IF EXISTS data.{self.table_name} CASCADE")
        )
        await self.session.commit()

    async def _create_seed_table(self) -> None:
        """Create the test table with one valid 4326 point and commit."""
        await self.session.execute(
            text(
                f"CREATE TABLE data.{self.table_name} ("
                "  gid serial PRIMARY KEY,"
                "  geom geometry(Point, 4326)"
                ")"
            )
        )
        await self.session.execute(
            text(
                f"INSERT INTO data.{self.table_name} (geom) VALUES ("
                "  ST_SetSRID(ST_MakePoint(-73.985, 40.748), 4326)"
                ")"
            )
        )
        await self.session.commit()

    async def _column_exists(self, session, column: str) -> bool:
        """Check whether ``column`` is present on the test table."""
        result = await session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'data' "
                "AND table_name = :t "
                "AND column_name = :c"
            ).bindparams(t=self.table_name, c=column)
        )
        return result.scalar_one_or_none() is not None

    async def test_add_4326_column_rollback_undoes_column(self):
        """A rollback after add_4326_column must drop the geom_4326 column.

        This is the core ING-02 invariant: if a downstream phase-2 step
        fails after ``add_4326_column`` succeeds, the rollback must undo
        the ALTER TABLE + UPDATE + CREATE INDEX work atomically.
        """
        from app.processing.ingest.metadata import add_4326_column

        await self._create_seed_table()

        # Phase-2 helper runs inside the outer transaction (no internal commit).
        await add_4326_column(self.session, self.table_name, 4326)

        # Mid-transaction: the column is visible to this session because the
        # ALTER + UPDATE landed in the open transaction.
        assert await self._column_exists(self.session, "geom_4326"), (
            "add_4326_column should have made geom_4326 visible to the "
            "session that ran the helper (uncommitted but visible to writer)"
        )

        # Simulate a downstream phase-2 failure: rollback the outer transaction.
        await self.session.rollback()

        # After rollback, the column must NOT exist — confirmed from a fresh
        # session so we know we're seeing the committed truth, not session-
        # cached state.
        from app.core.db import async_session

        async with async_session() as fresh_session:
            exists = await self._column_for_session_exists(
                fresh_session, "geom_4326"
            )
        assert exists is False, (
            "add_4326_column work survived a session.rollback() — the helper "
            "is committing internally (P2-02 / ING-02 regression)"
        )

    async def _column_for_session_exists(self, session, column: str) -> bool:
        """Variant of ``_column_exists`` that takes an arbitrary session."""
        result = await session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'data' "
                "AND table_name = :t "
                "AND column_name = :c"
            ).bindparams(t=self.table_name, c=column)
        )
        return result.scalar_one_or_none() is not None

    async def test_add_4326_column_commit_keeps_column(self):
        """Positive control: a commit after add_4326_column makes it durable.

        Guards against test 1 being a false positive — if for any reason the
        test setup or teardown were dropping ``geom_4326`` independently of
        the rollback, test 1 could pass spuriously. This test proves the
        only difference between "column present" and "column absent" is
        whether the test committed or rolled back.
        """
        from app.processing.ingest.metadata import add_4326_column

        await self._create_seed_table()

        await add_4326_column(self.session, self.table_name, 4326)
        await self.session.commit()

        # From a fresh session, the column must be visible after the commit.
        from app.core.db import async_session

        async with async_session() as fresh_session:
            assert await self._column_for_session_exists(
                fresh_session, "geom_4326"
            ), (
                "add_4326_column work was lost across the outer commit — "
                "the helper or its caller did not persist the column"
            )

    async def test_all_four_helpers_pend_until_outer_commit(self):
        """All four phase-2 helpers must pend until the caller commits.

        Calls every phase-2 helper without committing, then probes from a
        separate session: nothing the helpers did should be visible yet.
        After the outer commit, the work becomes visible — proving the
        outer commit is the only durable boundary.
        """
        from app.core.db import async_session
        from app.processing.ingest.metadata import (
            add_4326_column,
            clip_to_mercator_bounds,
            ensure_geom_column,
            grant_reader_access,
        )

        await self._create_seed_table()

        # Run all four helpers in the order _finalize_ingest invokes them.
        # ensure_geom_column is a no-op (geom already named correctly);
        # clip_to_mercator_bounds is a no-op (geometry inside ±85° lat);
        # add_4326_column and grant_reader_access do real work.
        await ensure_geom_column(self.session, self.table_name)
        await clip_to_mercator_bounds(self.session, self.table_name)
        await add_4326_column(self.session, self.table_name, 4326)
        await grant_reader_access(self.session, self.table_name)

        # From a SEPARATE session (in its own transaction), the work must
        # NOT be visible — the helpers participate in the test session's
        # open transaction and the outer commit has not fired yet.
        async with async_session() as probe_session:
            assert (
                await self._column_for_session_exists(probe_session, "geom_4326")
                is False
            ), (
                "Probe session sees geom_4326 before the outer commit — "
                "one of the four helpers committed internally (P2-02 / ING-02)"
            )

        # Now issue the outer commit; the work becomes durable.
        await self.session.commit()

        async with async_session() as probe_session:
            assert await self._column_for_session_exists(
                probe_session, "geom_4326"
            ), (
                "Probe session does not see geom_4326 after the outer commit — "
                "the four-helper chain failed to persist its work"
            )
