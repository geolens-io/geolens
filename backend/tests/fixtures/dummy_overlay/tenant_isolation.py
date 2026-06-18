"""Tenant isolation surface extending the dummy overlay (GATE-01, Phase 1208-04).

Purpose
-------
This module is a SEPARATE extension of the 1206 dummy overlay
(``backend/tests/fixtures/dummy_overlay/overlay.py``).  It must NOT be merged
into or edit ``overlay.py`` — overlay.py is intentionally kept minimal and
stable so 1206 tests are unaffected.

This surface seeds two tenant-owned entities (record, dataset, map, embed_token,
collection) for each of the two tenants produced by the ``multi_tenant_rls``
harness, and provides helpers to read those entities through a tenant-scoped
session so the GATE-01 cross-tenant isolation tests can assert 0/empty via RLS.

Usage (by test_gate01_cross_tenant_isolation.py)
-------------------------------------------------
::

    ctx = multi_tenant_rls
    async with TenantIsolationSurface(ctx) as surface:
        # Isolation read — tenant_a's session must NOT see tenant_b's dataset
        count = await surface.count_datasets(ctx.tenant_a, surface.ds_b_id)
        assert count == 0

Schema dependency order (FK constraints)
-----------------------------------------
records (created_by -> users.id)
  → datasets (record_id -> records.id)
  → maps (created_by -> users.id)
    → embed_tokens (map_id -> maps.id, created_by -> users.id)
  → collections (created_by -> users.id)

Teardown deletes in reverse FK order to avoid constraint violations.

Design notes
------------
- Seeds rows via fresh AUTOCOMMIT NullPool engine (connects as ``geolens``
  superuser, BYPASSRLS=True) — the policy does not block inserts.
- Teardown (``__aexit__``) deletes all seeded rows unconditionally so no
  artifacts remain after the test even on failure.
- Does NOT subclass or import anything from overlay.py (no dependency).
- Reused by Phase 1209 data-plane tests (just add new entity types here).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import TracebackType

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


class TenantIsolationSurface:
    """Seeds per-tenant entities and exposes isolation-read helpers.

    Parameters
    ----------
    ctx:
        A ``MultiTenantContext`` from the ``multi_tenant_rls`` fixture.
        Provides tenant_a, tenant_b, db_url, user_a_id, user_b_id,
        and tenant_session().
    """

    def __init__(self, ctx) -> None:
        self._ctx = ctx
        # Record row ids (seeded first — datasets FK into records)
        self.rec_a_id: str = ""
        self.rec_b_id: str = ""
        # Dataset row ids
        self.ds_a_id: str = ""
        self.ds_b_id: str = ""
        # Map row ids
        self.map_a_id: str = ""
        self.map_b_id: str = ""
        # Embed-token row ids
        self.et_a_id: str = ""
        self.et_b_id: str = ""
        # Collection row ids
        self.coll_a_id: str = ""
        self.coll_b_id: str = ""

    # ------------------------------------------------------------------
    # Async context manager — seed on enter, delete on exit
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "TenantIsolationSurface":
        """Seed all per-tenant rows (AUTOCOMMIT, superuser — bypasses RLS)."""
        suffix = uuid.uuid4().hex[:8]
        ctx = self._ctx
        now = datetime.now(timezone.utc)
        token_expiry = datetime(2099, 1, 1, tzinfo=timezone.utc)

        self.rec_a_id = str(uuid.uuid4())
        self.rec_b_id = str(uuid.uuid4())
        self.ds_a_id = str(uuid.uuid4())
        self.ds_b_id = str(uuid.uuid4())
        self.map_a_id = str(uuid.uuid4())
        self.map_b_id = str(uuid.uuid4())
        self.et_a_id = str(uuid.uuid4())
        self.et_b_id = str(uuid.uuid4())
        self.coll_a_id = str(uuid.uuid4())
        self.coll_b_id = str(uuid.uuid4())

        engine = create_async_engine(ctx.db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")

                # Grant SELECT on the 5 entity tables to geolens_reader for the
                # duration of this surface.  The harness only grants USAGE on
                # the catalog schema (for catalog.users); the other tables need
                # per-table SELECT grants so the SET LOCAL ROLE geolens_reader
                # sessions in tenant_session() can query them.  Revoked in
                # __aexit__.
                for tbl in (
                    "records",
                    "datasets",
                    "maps",
                    "embed_tokens",
                    "collections",
                ):
                    await conn.execute(
                        sa.text(f"GRANT SELECT ON catalog.{tbl} TO geolens_reader")
                    )

                # -- records (FK: created_by -> users.id) --
                for rec_id, user_id, tid in [
                    (self.rec_a_id, ctx.user_a_id, ctx.tenant_a),
                    (self.rec_b_id, ctx.user_b_id, ctx.tenant_b),
                ]:
                    await conn.execute(
                        sa.text(
                            "INSERT INTO catalog.records "
                            "(id, title, visibility, record_status, created_by, "
                            " tenant_id, created_at, updated_at) "
                            "VALUES (:id, :title, 'private', 'active', :created_by, "
                            "        :tenant, :now, :now)"
                        ),
                        {
                            "id": rec_id,
                            "title": f"gate01_rec_{suffix}_{rec_id[:8]}",
                            "created_by": user_id,
                            "tenant": tid,
                            "now": now,
                        },
                    )

                # -- datasets (FK: record_id -> records.id) --
                for ds_id, rec_id, tid in [
                    (self.ds_a_id, self.rec_a_id, ctx.tenant_a),
                    (self.ds_b_id, self.rec_b_id, ctx.tenant_b),
                ]:
                    await conn.execute(
                        sa.text(
                            "INSERT INTO catalog.datasets "
                            "(id, record_id, table_name, tenant_id) "
                            "VALUES (:id, :record_id, :table_name, :tenant)"
                        ),
                        {
                            "id": ds_id,
                            "record_id": rec_id,
                            "table_name": f"gate01_tbl_{suffix}_{ds_id[:8]}",
                            "tenant": tid,
                        },
                    )

                # -- maps (FK: created_by -> users.id) --
                for map_id, user_id, tid in [
                    (self.map_a_id, ctx.user_a_id, ctx.tenant_a),
                    (self.map_b_id, ctx.user_b_id, ctx.tenant_b),
                ]:
                    await conn.execute(
                        sa.text(
                            "INSERT INTO catalog.maps "
                            "(id, name, created_by, tenant_id, created_at, updated_at) "
                            "VALUES (:id, :name, :created_by, :tenant, :now, :now)"
                        ),
                        {
                            "id": map_id,
                            "name": f"gate01_map_{suffix}_{map_id[:8]}",
                            "created_by": user_id,
                            "tenant": tid,
                            "now": now,
                        },
                    )

                # -- embed_tokens (FK: map_id -> maps.id, created_by -> users.id) --
                for et_id, map_id, user_id, tid in [
                    (self.et_a_id, self.map_a_id, ctx.user_a_id, ctx.tenant_a),
                    (self.et_b_id, self.map_b_id, ctx.user_b_id, ctx.tenant_b),
                ]:
                    await conn.execute(
                        sa.text(
                            "INSERT INTO catalog.embed_tokens "
                            "(id, map_id, token_hash, token_hint, scoped_dataset_ids, "
                            " expires_at, created_by, tenant_id, created_at, updated_at) "
                            "VALUES (:id, :map_id, :token_hash, :token_hint, "
                            "        '[]'::jsonb, :expires_at, :created_by, "
                            "        :tenant, :now, :now)"
                        ),
                        {
                            "id": et_id,
                            "map_id": map_id,
                            "token_hash": f"gate01_hash_{suffix}_{et_id[:8]}",
                            "token_hint": f"gate01_{et_id[:8]}",
                            "expires_at": token_expiry,
                            "created_by": user_id,
                            "tenant": tid,
                            "now": now,
                        },
                    )

                # -- collections (FK: created_by -> users.id) --
                for coll_id, user_id, tid in [
                    (self.coll_a_id, ctx.user_a_id, ctx.tenant_a),
                    (self.coll_b_id, ctx.user_b_id, ctx.tenant_b),
                ]:
                    await conn.execute(
                        sa.text(
                            "INSERT INTO catalog.collections "
                            "(id, name, created_by, tenant_id, created_at, updated_at) "
                            "VALUES (:id, :name, :created_by, :tenant, :now, :now)"
                        ),
                        {
                            "id": coll_id,
                            "name": f"gate01_coll_{suffix}_{coll_id[:8]}",
                            "created_by": user_id,
                            "tenant": tid,
                            "now": now,
                        },
                    )

        finally:
            await engine.dispose()

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Delete all seeded rows (AUTOCOMMIT, unconditional teardown)."""
        ctx = self._ctx
        engine = create_async_engine(ctx.db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                # Delete in reverse FK order first, then revoke grants.
                await conn.execute(
                    sa.text("DELETE FROM catalog.embed_tokens WHERE id = ANY(:ids)"),
                    {"ids": [self.et_a_id, self.et_b_id]},
                )
                await conn.execute(
                    sa.text("DELETE FROM catalog.collections WHERE id = ANY(:ids)"),
                    {"ids": [self.coll_a_id, self.coll_b_id]},
                )
                await conn.execute(
                    sa.text("DELETE FROM catalog.maps WHERE id = ANY(:ids)"),
                    {"ids": [self.map_a_id, self.map_b_id]},
                )
                await conn.execute(
                    sa.text("DELETE FROM catalog.datasets WHERE id = ANY(:ids)"),
                    {"ids": [self.ds_a_id, self.ds_b_id]},
                )
                await conn.execute(
                    sa.text("DELETE FROM catalog.records WHERE id = ANY(:ids)"),
                    {"ids": [self.rec_a_id, self.rec_b_id]},
                )
                # Revoke the per-table SELECT grants added in __aenter__.
                for tbl in (
                    "records",
                    "datasets",
                    "maps",
                    "embed_tokens",
                    "collections",
                ):
                    await conn.execute(
                        sa.text(f"REVOKE SELECT ON catalog.{tbl} FROM geolens_reader")
                    )
        finally:
            await engine.dispose()

    # ------------------------------------------------------------------
    # Isolation-read helpers (used by test_gate01_cross_tenant_isolation)
    # ------------------------------------------------------------------

    async def count_datasets(self, as_tenant: str, dataset_id: str) -> int:
        """Return count of catalog.datasets rows visible to *as_tenant* for *dataset_id*."""
        async with self._ctx.tenant_session(as_tenant) as session:
            result = await session.execute(
                sa.text("SELECT count(*) FROM catalog.datasets WHERE id = :id"),
                {"id": dataset_id},
            )
            return int(result.scalar_one())

    async def count_maps(self, as_tenant: str, map_id: str) -> int:
        """Return count of catalog.maps rows visible to *as_tenant* for *map_id*."""
        async with self._ctx.tenant_session(as_tenant) as session:
            result = await session.execute(
                sa.text("SELECT count(*) FROM catalog.maps WHERE id = :id"),
                {"id": map_id},
            )
            return int(result.scalar_one())

    async def count_embed_tokens(self, as_tenant: str, et_id: str) -> int:
        """Return count of catalog.embed_tokens rows visible to *as_tenant* for *et_id*."""
        async with self._ctx.tenant_session(as_tenant) as session:
            result = await session.execute(
                sa.text("SELECT count(*) FROM catalog.embed_tokens WHERE id = :id"),
                {"id": et_id},
            )
            return int(result.scalar_one())

    async def count_collections(self, as_tenant: str, coll_id: str) -> int:
        """Return count of catalog.collections rows visible to *as_tenant* for *coll_id*."""
        async with self._ctx.tenant_session(as_tenant) as session:
            result = await session.execute(
                sa.text("SELECT count(*) FROM catalog.collections WHERE id = :id"),
                {"id": coll_id},
            )
            return int(result.scalar_one())

    async def count_records(self, as_tenant: str, rec_id: str) -> int:
        """Return count of catalog.records rows visible to *as_tenant* for *rec_id*."""
        async with self._ctx.tenant_session(as_tenant) as session:
            result = await session.execute(
                sa.text("SELECT count(*) FROM catalog.records WHERE id = :id"),
                {"id": rec_id},
            )
            return int(result.scalar_one())
