"""GATE-01: cross-tenant isolation gate (Phase 1208-04).

The security gate the whole phase exists to deliver.

What this tests
---------------
In ``multi_tenant`` mode with FORCE RLS active + 2 tenant fixtures (tenant A
and tenant B), each owning a set of catalog entities (dataset/record/map/
embed_token/collection), a session scoped to tenant A MUST NOT see tenant B's
entities across ANY of the representative read paths — and vice versa.

Enforcement boundary: **the database** (RLS), NOT the permission port / the
application filter layer.  The test proves the DB is the backstop regardless
of what the application does above it.

Why SET LOCAL ROLE geolens_reader
----------------------------------
The test DB connects as ``geolens`` which is a PostgreSQL superuser
(``rolsuper=True, rolbypassrls=True``).  Superusers always bypass RLS even
under ``FORCE ROW LEVEL SECURITY``.  To prove the DB boundary holds, we must
run queries as a non-privileged role.  The ``multi_tenant_rls`` harness's
``tenant_session()`` helper issues ``SET LOCAL ROLE geolens_reader`` (a
NOLOGIN role with ``rolbypassrls=False``) inside the transaction — subject to
FORCE RLS — then the engine begin-hook issues ``set_config('app.current_tenant',
tid, true)`` scoping the query to that tenant.

Paths covered
-------------
- Datasets  (catalog.datasets)       — the primary data registration entity
- Records   (catalog.records)        — the metadata record dataset FKs into
- Maps      (catalog.maps)           — the collaborative map entity
- Embed     (catalog.embed_tokens)   — the external embed capability
- OGC/Coll  (catalog.collections)   — OGC API collections

All 5 of the 6 tenant-shared tables are covered (``catalog.users`` is covered
by the 1208-03 leak-lint).  Together with the leak-lint's coverage of
``catalog.users``, all 6 tables are represented.

Runs on every core PR
---------------------
This test lives in the default backend suite with no secret/overlay-install
gating.  The only dependency is the ``multi_tenant_rls`` fixture (registered
in conftest.py via pytest_plugins).  It runs on every ``pytest`` invocation
alongside the rest of the backend suite.

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_gate01_cross_tenant_isolation.py -x -q
"""

from __future__ import annotations

import pytest

from tests.fixtures.dummy_overlay.tenant_isolation import TenantIsolationSurface


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _with_surface(ctx, fn):
    """Run *fn* with a seeded TenantIsolationSurface and return its result."""
    async with TenantIsolationSurface(ctx) as surface:
        return await fn(surface)


# ---------------------------------------------------------------------------
# GATE-01A: Datasets — catalog.datasets
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestGate01Datasets:
    """Tenant A's session cannot see tenant B's datasets (and vice versa).

    Representative path: datasets → ``catalog.datasets`` is the primary entity
    for user-uploaded spatial data.  A cross-tenant leak here means a malicious
    tenant could enumerate another tenant's datasets.
    """

    async def test_tenant_a_sees_own_dataset(self, multi_tenant_rls):
        """Scoped to tenant_a: tenant_a's dataset is visible (RLS allows own row)."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_datasets(ctx.tenant_a, surface.ds_a_id)
            assert count == 1, (
                f"GATE-01 FAIL [datasets/A-own]: tenant_a cannot see its own dataset.\n"
                f"  count={count}, ds_a_id={surface.ds_a_id!r}, tenant_a={ctx.tenant_a!r}\n"
                f"  RLS policy is over-filtering — check tenant_isolation_datasets policy."
            )

        await _with_surface(ctx, fn)

    async def test_tenant_a_cannot_see_tenant_b_dataset(self, multi_tenant_rls):
        """Scoped to tenant_a: tenant_b's dataset is invisible (cross-tenant blocked by RLS)."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_datasets(ctx.tenant_a, surface.ds_b_id)
            assert count == 0, (
                f"GATE-01 FAIL [datasets/A-cross]: tenant_a can see tenant_b's dataset!\n"
                f"  count={count}, ds_b_id={surface.ds_b_id!r}, tenant_b={ctx.tenant_b!r}\n"
                f"  Cross-tenant data leak — RLS policy is not enforcing isolation.\n"
                f"  The DB boundary does NOT hold for catalog.datasets."
            )

        await _with_surface(ctx, fn)

    async def test_tenant_b_sees_own_dataset(self, multi_tenant_rls):
        """Scoped to tenant_b: tenant_b's dataset is visible (symmetric)."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_datasets(ctx.tenant_b, surface.ds_b_id)
            assert count == 1, (
                f"GATE-01 FAIL [datasets/B-own]: tenant_b cannot see its own dataset.\n"
                f"  count={count}, ds_b_id={surface.ds_b_id!r}, tenant_b={ctx.tenant_b!r}"
            )

        await _with_surface(ctx, fn)

    async def test_tenant_b_cannot_see_tenant_a_dataset(self, multi_tenant_rls):
        """Scoped to tenant_b: tenant_a's dataset is invisible (cross-tenant blocked by RLS)."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_datasets(ctx.tenant_b, surface.ds_a_id)
            assert count == 0, (
                f"GATE-01 FAIL [datasets/B-cross]: tenant_b can see tenant_a's dataset!\n"
                f"  count={count}, ds_a_id={surface.ds_a_id!r}, tenant_a={ctx.tenant_a!r}\n"
                f"  Cross-tenant data leak in catalog.datasets."
            )

        await _with_surface(ctx, fn)


# ---------------------------------------------------------------------------
# GATE-01B: Records — catalog.records
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestGate01Records:
    """Tenant A's session cannot see tenant B's metadata records (and vice versa).

    Representative path: records → ``catalog.records`` is the metadata record
    that datasets FK into.  A cross-tenant leak here exposes dataset metadata.
    """

    async def test_tenant_a_sees_own_record(self, multi_tenant_rls):
        """Scoped to tenant_a: tenant_a's record is visible."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_records(ctx.tenant_a, surface.rec_a_id)
            assert count == 1, (
                f"GATE-01 FAIL [records/A-own]: tenant_a cannot see its own record.\n"
                f"  count={count}, rec_a_id={surface.rec_a_id!r}"
            )

        await _with_surface(ctx, fn)

    async def test_tenant_a_cannot_see_tenant_b_record(self, multi_tenant_rls):
        """Scoped to tenant_a: tenant_b's record is invisible."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_records(ctx.tenant_a, surface.rec_b_id)
            assert count == 0, (
                f"GATE-01 FAIL [records/A-cross]: tenant_a can see tenant_b's record!\n"
                f"  count={count}, rec_b_id={surface.rec_b_id!r}\n"
                f"  Cross-tenant data leak in catalog.records."
            )

        await _with_surface(ctx, fn)

    async def test_tenant_b_sees_own_record(self, multi_tenant_rls):
        """Scoped to tenant_b: tenant_b's record is visible (symmetric)."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_records(ctx.tenant_b, surface.rec_b_id)
            assert count == 1, (
                f"GATE-01 FAIL [records/B-own]: tenant_b cannot see its own record.\n"
                f"  count={count}, rec_b_id={surface.rec_b_id!r}"
            )

        await _with_surface(ctx, fn)

    async def test_tenant_b_cannot_see_tenant_a_record(self, multi_tenant_rls):
        """Scoped to tenant_b: tenant_a's record is invisible."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_records(ctx.tenant_b, surface.rec_a_id)
            assert count == 0, (
                f"GATE-01 FAIL [records/B-cross]: tenant_b can see tenant_a's record!\n"
                f"  count={count}, rec_a_id={surface.rec_a_id!r}\n"
                f"  Cross-tenant data leak in catalog.records."
            )

        await _with_surface(ctx, fn)


# ---------------------------------------------------------------------------
# GATE-01C: Maps — catalog.maps
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestGate01Maps:
    """Tenant A's session cannot see tenant B's maps (and vice versa).

    Representative path: maps → ``catalog.maps`` is the collaborative map
    entity.  A cross-tenant leak here means a tenant can read another tenant's
    private maps, including their layer configurations and basemap settings.
    """

    async def test_tenant_a_sees_own_map(self, multi_tenant_rls):
        """Scoped to tenant_a: tenant_a's map is visible."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_maps(ctx.tenant_a, surface.map_a_id)
            assert count == 1, (
                f"GATE-01 FAIL [maps/A-own]: tenant_a cannot see its own map.\n"
                f"  count={count}, map_a_id={surface.map_a_id!r}"
            )

        await _with_surface(ctx, fn)

    async def test_tenant_a_cannot_see_tenant_b_map(self, multi_tenant_rls):
        """Scoped to tenant_a: tenant_b's map is invisible (tiles path DB boundary)."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_maps(ctx.tenant_a, surface.map_b_id)
            assert count == 0, (
                f"GATE-01 FAIL [maps/A-cross]: tenant_a can see tenant_b's map!\n"
                f"  count={count}, map_b_id={surface.map_b_id!r}\n"
                f"  This is the tiles-path DB boundary — the tile resolver reads\n"
                f"  catalog.maps to resolve a map; cross-tenant leak here means\n"
                f"  tenant A can serve tenant B's map tiles."
            )

        await _with_surface(ctx, fn)

    async def test_tenant_b_sees_own_map(self, multi_tenant_rls):
        """Scoped to tenant_b: tenant_b's map is visible (symmetric)."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_maps(ctx.tenant_b, surface.map_b_id)
            assert count == 1, (
                f"GATE-01 FAIL [maps/B-own]: tenant_b cannot see its own map.\n"
                f"  count={count}, map_b_id={surface.map_b_id!r}"
            )

        await _with_surface(ctx, fn)

    async def test_tenant_b_cannot_see_tenant_a_map(self, multi_tenant_rls):
        """Scoped to tenant_b: tenant_a's map is invisible."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_maps(ctx.tenant_b, surface.map_a_id)
            assert count == 0, (
                f"GATE-01 FAIL [maps/B-cross]: tenant_b can see tenant_a's map!\n"
                f"  count={count}, map_a_id={surface.map_a_id!r}"
            )

        await _with_surface(ctx, fn)


# ---------------------------------------------------------------------------
# GATE-01D: Embed tokens — catalog.embed_tokens
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestGate01EmbedTokens:
    """Tenant A's session cannot see tenant B's embed tokens (and vice versa).

    Representative path: embed → ``catalog.embed_tokens`` gates external
    iframe embedding.  A cross-tenant leak here means a tenant can enumerate
    or hijack another tenant's embed tokens, which may serve private datasets.

    SEC-022 context: embed tokens intentionally serve private datasets
    (EMBED-02/04).  Cross-tenant token leakage would be a critical security
    failure — a separate tenant must never be able to read or replay another
    tenant's embed token.
    """

    async def test_tenant_a_sees_own_embed_token(self, multi_tenant_rls):
        """Scoped to tenant_a: tenant_a's embed token is visible."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_embed_tokens(ctx.tenant_a, surface.et_a_id)
            assert count == 1, (
                f"GATE-01 FAIL [embed/A-own]: tenant_a cannot see its own embed token.\n"
                f"  count={count}, et_a_id={surface.et_a_id!r}"
            )

        await _with_surface(ctx, fn)

    async def test_tenant_a_cannot_see_tenant_b_embed_token(self, multi_tenant_rls):
        """Scoped to tenant_a: tenant_b's embed token is invisible."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_embed_tokens(ctx.tenant_a, surface.et_b_id)
            assert count == 0, (
                f"GATE-01 FAIL [embed/A-cross]: tenant_a can see tenant_b's embed token!\n"
                f"  count={count}, et_b_id={surface.et_b_id!r}\n"
                f"  Cross-tenant embed token leak — tenant A can read tenant B's\n"
                f"  embed-token metadata, potentially facilitating token replay."
            )

        await _with_surface(ctx, fn)

    async def test_tenant_b_sees_own_embed_token(self, multi_tenant_rls):
        """Scoped to tenant_b: tenant_b's embed token is visible (symmetric)."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_embed_tokens(ctx.tenant_b, surface.et_b_id)
            assert count == 1, (
                f"GATE-01 FAIL [embed/B-own]: tenant_b cannot see its own embed token.\n"
                f"  count={count}, et_b_id={surface.et_b_id!r}"
            )

        await _with_surface(ctx, fn)

    async def test_tenant_b_cannot_see_tenant_a_embed_token(self, multi_tenant_rls):
        """Scoped to tenant_b: tenant_a's embed token is invisible."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_embed_tokens(ctx.tenant_b, surface.et_a_id)
            assert count == 0, (
                f"GATE-01 FAIL [embed/B-cross]: tenant_b can see tenant_a's embed token!\n"
                f"  count={count}, et_a_id={surface.et_a_id!r}"
            )

        await _with_surface(ctx, fn)


# ---------------------------------------------------------------------------
# GATE-01E: Collections — catalog.collections (OGC API path)
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestGate01Collections:
    """Tenant A's session cannot see tenant B's OGC collections (and vice versa).

    Representative path: OGC → ``catalog.collections`` backs the OGC API
    Features ``/collections`` endpoint.  A cross-tenant leak here means a
    tenant can enumerate another tenant's OGC feature collections.
    """

    async def test_tenant_a_sees_own_collection(self, multi_tenant_rls):
        """Scoped to tenant_a: tenant_a's collection is visible."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_collections(ctx.tenant_a, surface.coll_a_id)
            assert count == 1, (
                f"GATE-01 FAIL [collections/A-own]: tenant_a cannot see its own collection.\n"
                f"  count={count}, coll_a_id={surface.coll_a_id!r}"
            )

        await _with_surface(ctx, fn)

    async def test_tenant_a_cannot_see_tenant_b_collection(self, multi_tenant_rls):
        """Scoped to tenant_a: tenant_b's collection is invisible."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_collections(ctx.tenant_a, surface.coll_b_id)
            assert count == 0, (
                f"GATE-01 FAIL [collections/A-cross]: tenant_a can see tenant_b's collection!\n"
                f"  count={count}, coll_b_id={surface.coll_b_id!r}\n"
                f"  Cross-tenant OGC collection leak."
            )

        await _with_surface(ctx, fn)

    async def test_tenant_b_sees_own_collection(self, multi_tenant_rls):
        """Scoped to tenant_b: tenant_b's collection is visible (symmetric)."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_collections(ctx.tenant_b, surface.coll_b_id)
            assert count == 1, (
                f"GATE-01 FAIL [collections/B-own]: tenant_b cannot see its own collection.\n"
                f"  count={count}, coll_b_id={surface.coll_b_id!r}"
            )

        await _with_surface(ctx, fn)

    async def test_tenant_b_cannot_see_tenant_a_collection(self, multi_tenant_rls):
        """Scoped to tenant_b: tenant_a's collection is invisible."""
        ctx = multi_tenant_rls

        async def fn(surface):
            count = await surface.count_collections(ctx.tenant_b, surface.coll_a_id)
            assert count == 0, (
                f"GATE-01 FAIL [collections/B-cross]: tenant_b can see tenant_a's collection!\n"
                f"  count={count}, coll_a_id={surface.coll_a_id!r}"
            )

        await _with_surface(ctx, fn)


# ---------------------------------------------------------------------------
# GATE-01F: Cross-entity symmetry (all 5 paths in one transaction)
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestGate01CrossEntitySymmetry:
    """Bulk symmetry test: A→B and B→A are both 0 across all 5 entity types.

    A single test that seeds once and verifies the full cross-tenant isolation
    envelope in one pass — useful as a fast single-entry regression gate.
    """

    async def test_full_cross_tenant_isolation_envelope(self, multi_tenant_rls):
        """All 5 cross-tenant reads return 0; all 5 own-tenant reads return 1.

        This is the ROADMAP fail-closed cross-tenant assertion criterion.
        A refactor that breaks the tenant contract on ANY of the 5 entity types
        will fail this test on every core PR.
        """
        ctx = multi_tenant_rls

        async def fn(surface):
            failures: list[str] = []

            # --- tenant_a sees its own entities ---
            for label, count_fn, own_id in [
                ("datasets/A-own", surface.count_datasets, surface.ds_a_id),
                ("records/A-own", surface.count_records, surface.rec_a_id),
                ("maps/A-own", surface.count_maps, surface.map_a_id),
                ("embed/A-own", surface.count_embed_tokens, surface.et_a_id),
                ("collections/A-own", surface.count_collections, surface.coll_a_id),
            ]:
                c = await count_fn(ctx.tenant_a, own_id)
                if c != 1:
                    failures.append(f"[{label}] expected 1, got {c}")

            # --- tenant_a cannot see tenant_b's entities ---
            for label, count_fn, cross_id in [
                ("datasets/A-cross", surface.count_datasets, surface.ds_b_id),
                ("records/A-cross", surface.count_records, surface.rec_b_id),
                ("maps/A-cross", surface.count_maps, surface.map_b_id),
                ("embed/A-cross", surface.count_embed_tokens, surface.et_b_id),
                ("collections/A-cross", surface.count_collections, surface.coll_b_id),
            ]:
                c = await count_fn(ctx.tenant_a, cross_id)
                if c != 0:
                    failures.append(f"[{label}] CROSS-TENANT LEAK: expected 0, got {c}")

            # --- tenant_b sees its own entities ---
            for label, count_fn, own_id in [
                ("datasets/B-own", surface.count_datasets, surface.ds_b_id),
                ("records/B-own", surface.count_records, surface.rec_b_id),
                ("maps/B-own", surface.count_maps, surface.map_b_id),
                ("embed/B-own", surface.count_embed_tokens, surface.et_b_id),
                ("collections/B-own", surface.count_collections, surface.coll_b_id),
            ]:
                c = await count_fn(ctx.tenant_b, own_id)
                if c != 1:
                    failures.append(f"[{label}] expected 1, got {c}")

            # --- tenant_b cannot see tenant_a's entities ---
            for label, count_fn, cross_id in [
                ("datasets/B-cross", surface.count_datasets, surface.ds_a_id),
                ("records/B-cross", surface.count_records, surface.rec_a_id),
                ("maps/B-cross", surface.count_maps, surface.map_a_id),
                ("embed/B-cross", surface.count_embed_tokens, surface.et_a_id),
                ("collections/B-cross", surface.count_collections, surface.coll_a_id),
            ]:
                c = await count_fn(ctx.tenant_b, cross_id)
                if c != 0:
                    failures.append(f"[{label}] CROSS-TENANT LEAK: expected 0, got {c}")

            assert not failures, (
                f"GATE-01 FAIL: {len(failures)} isolation failure(s) across "
                f"the 5 RLS-protected entity types:\n"
                + "\n".join(f"  {f}" for f in failures)
                + "\n\nThe DB boundary (FORCE RLS) does NOT hold for one or more "
                "of the 5 representative read paths (datasets/records/maps/embed/OGC).\n"
                "Check that the tenant_isolation_* policies are in place and that\n"
                "the geolens_reader role is used for the probe (rolbypassrls=False)."
            )

        await _with_surface(ctx, fn)
