"""Credential renewal runs per tenant, under real RLS (#1277 review round 3).

The renewal sweep used to open one session AFTER ``sweep_stale_jobs_once`` had
exited every ``tenant_job_context`` block, so in multi-tenant mode its query
ran with no ``app.current_tenant`` set. Two problems, one of them latent and
the other permanent:

- Today no ``catalog`` table has RLS enabled — enablement is #998's work, and
  ``pg_class.relrowsecurity`` is false for all three tables the query touches
  — so it did not fail. It read ACROSS every tenant, which is not a boundary
  this code is entitled to cross even where the database permits it.
- Once FORCE RLS is on ``ingest_jobs``, the same query returns nothing for
  every tenant, and the helper's never-raises contract records that as "zero
  renewed". Every queued protected refresh would then die
  ``credential_expired`` past the TTL with nothing explaining why.

This suite runs against the second world rather than today's: the
``multi_tenant_rls`` harness enables and FORCEs RLS on the real boundary
(``ingest_jobs`` is in its set; ``dataset_refresh_runs`` deliberately is not,
matching its model docstring — it is reachable only through ``dataset_id``).
So it is a forward guard for #998 as much as a regression test for now.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.platform.refresh import credentials as creds

pytestmark = [pytest.mark.anyio, pytest.mark.rls]

_WFS_BASE = "https://services.example.com/geoserver/wfs"

# Tables the renewal path reads that the harness's own grant set does not
# cover. Granted and revoked around the test so the shared worker database is
# left exactly as it was found. `tenants` is the registry the per-tenant loop
# reads; the other two are the renewal query's non-boundary joins.
_EXTRA_READER_GRANTS = ("tenants", "dataset_refresh_runs", "procrastinate_jobs")


class _FakeBackend:
    """Minimal store; ``renew`` models EXPIRE's refusal to resurrect."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def put(self, key: str, value: str, ttl_seconds: int) -> None:
        self.store[key] = value

    async def take(self, key: str) -> str | None:
        return self.store.pop(key, None)

    async def renew(self, key: str, ttl_seconds: int) -> bool:
        return key in self.store


async def _seed_tenant_dispatch(conn, *, tenant_id: str, user_id, ref: str) -> dict:
    """One queued credentialed refresh owned by *tenant_id*.

    Seeded through the privileged AUTOCOMMIT connection, the pattern the other
    RLS suites use. ``ingest_jobs.tenant_id`` is set explicitly because that is
    the column RLS scopes on, and it is the whole point of the test.
    """
    ids = {
        "record": uuid.uuid4(),
        "dataset": uuid.uuid4(),
        "job": uuid.uuid4(),
        "run": uuid.uuid4(),
        "table_name": f"ds_{uuid.uuid4().hex[:12]}",
    }
    await conn.execute(
        sa.text(
            "INSERT INTO catalog.records "
            "(id, title, visibility, record_status, created_by, tenant_id) "
            "VALUES (:id, 'renewal probe', 'private', 'published', :uid, :tid)"
        ),
        {"id": ids["record"], "uid": user_id, "tid": tenant_id},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO catalog.datasets "
            "(id, record_id, table_name, source_format, tenant_id) "
            "VALUES (:id, :rid, :tn, 'wfs', :tid)"
        ),
        {
            "id": ids["dataset"],
            "rid": ids["record"],
            "tn": ids["table_name"],
            "tid": tenant_id,
        },
    )
    await conn.execute(
        sa.text(
            "INSERT INTO catalog.ingest_jobs "
            "(id, dataset_id, status, source_url, created_by, tenant_id, "
            " user_metadata) "
            "VALUES (:id, :did, 'pending', :url, :uid, :tid, "
            " jsonb_build_object('reupload', true))"
        ),
        {
            "id": ids["job"],
            "did": ids["dataset"],
            "url": _WFS_BASE,
            "uid": user_id,
            "tid": tenant_id,
        },
    )
    await conn.execute(
        sa.text(
            "INSERT INTO catalog.dataset_refresh_runs "
            "(id, dataset_id, ingest_job_id, origin_kind, trigger, status, "
            " started_at, tenant_id) "
            "VALUES (:id, :did, :jid, 'service', 'api', 'pending', now(), :tid)"
        ),
        {
            "id": ids["run"],
            "did": ids["dataset"],
            "jid": ids["job"],
            "tid": tenant_id,
        },
    )
    # Procrastinate's insert trigger writes procrastinate_events through
    # unqualified names, so the schema has to be on the search_path for a
    # hand-written INSERT the way it is for the library's own.
    await conn.execute(sa.text("SET search_path TO catalog, public"))
    await conn.execute(
        sa.text(
            "INSERT INTO catalog.procrastinate_jobs "
            "(queue_name, task_name, args, status) "
            "VALUES ('ingest', 'reupload_service', "
            "jsonb_build_object('job_id', CAST(:jid AS text), "
            "'credential_ref', CAST(:ref AS text)), 'todo')"
        ),
        {"jid": str(ids["job"]), "ref": ref},
    )
    return ids


async def _cleanup(conn, seeded: list[dict]) -> None:
    """Remove every seeded row.

    The worker's test database is shared for the whole session, so rows left
    behind here surface as unrelated failures in later tests on the same
    worker. Runs in a finally, deepest child first.

    The search_path matters on DELETE as well as INSERT: procrastinate's
    delete trigger reaches ``procrastinate_periodic_defers`` unqualified, and
    this runs on a fresh connection whose path does not include ``catalog``.
    """
    await conn.execute(sa.text("SET search_path TO catalog, public"))
    for ids in seeded:
        await conn.execute(
            sa.text(
                "DELETE FROM catalog.procrastinate_jobs WHERE args->>'job_id' = :jid"
            ),
            {"jid": str(ids["job"])},
        )
        await conn.execute(
            sa.text("DELETE FROM catalog.dataset_refresh_runs WHERE id = :id"),
            {"id": ids["run"]},
        )
        await conn.execute(
            sa.text("DELETE FROM catalog.ingest_jobs WHERE id = :id"),
            {"id": ids["job"]},
        )
        await conn.execute(
            sa.text("DELETE FROM catalog.datasets WHERE id = :id"),
            {"id": ids["dataset"]},
        )
        await conn.execute(
            sa.text("DELETE FROM catalog.records WHERE id = :id"),
            {"id": ids["record"]},
        )


async def test_every_tenants_queued_credential_is_renewed(
    multi_tenant_rls, monkeypatch
) -> None:
    """Two tenants, one queued credentialed dispatch each, both re-armed.

    This is the assertion the previous code could not satisfy under RLS: a
    single query outside any tenant context sees neither tenant's
    ``ingest_jobs`` row, so it renews nothing and reports success doing it.

    Two pieces of scaffolding earn their place, and both are about making the
    test subject to the thing it claims to test:

    - ``app.core.db.async_session`` is rebound to the harness database. The
      helper late-binds it (fix #909), and the app's own binding points at a
      different database than the one the harness seeds and RLS-enables.
    - the session drops to ``geolens_reader`` inside each transaction. The
      test connects as ``geolens``, which is BYPASSRLS, so without the role
      switch FORCE RLS never applies and this would pass against the broken
      code as happily as the fixed one.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.db.tenant_session import (
        install_tenant_session_hook,
        tenant_job_context,
    )
    from app.platform.refresh.credentials import renew_queued_credentials_once

    ctx = multi_tenant_rls
    backend = _FakeBackend()
    creds.set_credential_backend(backend)

    engine = create_async_engine(
        ctx.db_url, poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    scoped_engine = create_async_engine(ctx.db_url, poolclass=NullPool)
    install_tenant_session_hook(scoped_engine)

    @sa.event.listens_for(scoped_engine.sync_engine, "begin")
    def _drop_to_reader(conn):  # noqa: ANN001 - sqlalchemy event signature
        conn.exec_driver_sql("SET LOCAL ROLE geolens_reader")

    _session_factory = async_sessionmaker(scoped_engine, expire_on_commit=False)
    monkeypatch.setattr("app.core.db.async_session", _session_factory)

    seeded: list[dict] = []
    try:
        ref_a = await creds.stash_service_credential("tenant-a-token")
        ref_b = await creds.stash_service_credential("tenant-b-token")
        async with engine.connect() as conn:
            # The renewal query reads two tables outside the harness's grant
            # set. Under #998 these grants exist; here they are made and
            # revoked around the test so the shared worker database is left
            # exactly as it was found.
            for table in _EXTRA_READER_GRANTS:
                await conn.execute(
                    sa.text(f"GRANT SELECT ON catalog.{table} TO geolens_reader")
                )
            for tenant_id in (ctx.tenant_a, ctx.tenant_b):
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.tenants (id, slug, name) "
                        "VALUES (:id, :slug, :name) ON CONFLICT (id) DO NOTHING"
                    ),
                    {
                        "id": tenant_id,
                        "slug": f"t-{str(tenant_id)[:8]}",
                        "name": "renewal probe",
                    },
                )
            seeded.append(
                await _seed_tenant_dispatch(
                    conn, tenant_id=ctx.tenant_a, user_id=ctx.user_a_id, ref=ref_a
                )
            )
            seeded.append(
                await _seed_tenant_dispatch(
                    conn, tenant_id=ctx.tenant_b, user_id=ctx.user_b_id, ref=ref_b
                )
            )

            renewed = await renew_queued_credentials_once()

        assert renewed == 2, (
            "both tenants' queued credentials must be re-armed; a renewal that "
            "runs outside a tenant context sees neither"
        )
        # fix(#1277 review round 4): 2 as one-each, not two tenants x two
        # keys. The explicit tenant filter is what makes the total equal the
        # number of tenants rather than its square.
        per_tenant = []
        for tenant_id in (ctx.tenant_a, ctx.tenant_b):
            with tenant_job_context(str(tenant_id)):
                async with _session_factory() as scoped_session:
                    per_tenant.append(
                        await creds.renew_queued_refresh_credentials(
                            scoped_session, tenant_id=str(tenant_id)
                        )
                    )
        assert per_tenant == [1, 1], (
            "each tenant must renew exactly its own key; anything higher means "
            "the iteration is crossing the boundary it exists to respect"
        )

        # fix(#1277 review round 4): and the FILTER is what narrows it, not
        # RLS. This is today's configuration — RLS is off everywhere, so
        # tenant_job_context sets a GUC nothing enforces and the predicate in
        # the query is the only thing keeping tenants apart. Asserted on the
        # PRIVILEGED session, which is BYPASSRLS: unfiltered it sees both rows,
        # and each tenant id narrows it to one. Without the predicate every
        # tenant's iteration would renew the whole fleet.
        privileged = async_sessionmaker(engine, expire_on_commit=False)
        async with privileged() as bypass_session:
            unfiltered = await creds.renew_queued_refresh_credentials(bypass_session)
            assert unfiltered == 2, "sanity: both rows are visible to this session"
            bypass_scoped = [
                await creds.renew_queued_refresh_credentials(
                    bypass_session, tenant_id=str(tenant_id)
                )
                for tenant_id in (ctx.tenant_a, ctx.tenant_b)
            ]
        assert bypass_scoped == [1, 1], (
            "the explicit tenant predicate must narrow the query on its own; "
            "[2, 2] is the unfiltered query renewing the fleet once per tenant"
        )
        # Renewal must not consume: both are still claimable afterwards.
        assert await creds.claim_service_credential(ref_a) == "tenant-a-token"
        assert await creds.claim_service_credential(ref_b) == "tenant-b-token"
    finally:
        async with engine.connect() as conn:
            await _cleanup(conn, seeded)
            for table in _EXTRA_READER_GRANTS:
                await conn.execute(
                    sa.text(f"REVOKE SELECT ON catalog.{table} FROM geolens_reader")
                )
            for tenant_id in (ctx.tenant_a, ctx.tenant_b):
                await conn.execute(
                    sa.text("DELETE FROM catalog.tenants WHERE id = :id"),
                    {"id": tenant_id},
                )
        await engine.dispose()
        await scoped_engine.dispose()
        creds.set_credential_backend(None)
