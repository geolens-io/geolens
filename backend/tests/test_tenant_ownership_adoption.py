"""Forward-only tenant-ownership adoption at the head schema (#998).

The only path that ever reconstructed tenant ownership was
``alembic downgrade 0016`` followed by a re-upgrade through 0019 — a data-loss
event on a populated cluster.  ``app.core.db.tenant_adoption`` does the same
reconstruction at head; these tests hold it to the state 0019 produced.

Coverage
--------
A: a head-schema database carrying tenant data with no ownership rows — schema,
   relations, and roles all sitting where ``pg_restore --no-owner --no-acl``
   leaves them — is adopted into the 0019 end state.
B: a second run changes nothing.  Asserted by diffing a full catalog snapshot
   (owners, ACLs, role attributes, memberships), not by trusting the report.
C: the dump-restore case — the SECURITY DEFINER boundary functions are already
   present, owned by the restoring login, with the PostgreSQL default ACL that
   grants EXECUTE to PUBLIC.  Adoption must not collide with them and must take
   that grant away.
D: the tenant boundary is read from the database, never from a constant frozen
   into a migration.

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_tenant_ownership_adoption.py -x -q
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db.rls import RLS_TABLES
from app.core.db.tenant_adoption import (
    BOUNDARY_FUNCTIONS,
    CONTROL,
    PROVISIONER,
    boundary_drift,
    boundary_function_states,
    live_tenant_boundary,
    run_adoption,
    tenant_ownership_state,
)

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parents[2]


def _new_tenant() -> tuple[str, str, str, str]:
    """A tenant id whose cluster-wide role names cannot collide with a peer.

    Per-tenant roles are cluster objects shared by every xdist worker's test
    database, so a fixed fixture id would have two workers adopting and dropping
    the same roles.
    """
    tenant_id = str(uuid.uuid4())
    suffix = tenant_id.replace("-", "_")
    return (
        tenant_id,
        f"data_t_{suffix}",
        f"geolens_reader_t_{suffix}",
        f"geolens_writer_t_{suffix}",
    )


def _make_engine():
    from app.core.config import settings

    return create_async_engine(settings.test_database_url, poolclass=NullPool)


async def _seed_restored_tenant(engine, tenant_id: str, schema: str) -> None:
    """Recreate what a ``pg_restore --no-owner --no-acl`` hands the operator.

    Every relation is owned by the restoring login, no ACLs survive, and the
    per-tenant reader/writer roles do not exist at all — the fresh-cluster case
    where no globals dump was replayed.
    """
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO catalog.tenants (id, slug, name) "
                "VALUES (CAST(:id AS uuid), :slug, :name)"
            ),
            {"id": tenant_id, "slug": f"w998-{tenant_id[:8]}", "name": "adoption"},
        )
        await conn.execute(sa.text(f"CREATE SCHEMA {schema}"))
        # bigserial gives us a column-owned sequence: PostgreSQL refuses
        # ALTER SEQUENCE ... OWNER TO on those, and every ogr2ogr vector ingest
        # produces one as ogc_fid.
        await conn.execute(
            sa.text(
                f"CREATE TABLE {schema}.parcels "
                "(id bigserial PRIMARY KEY, name text NOT NULL)"
            )
        )
        await conn.execute(
            sa.text(f"INSERT INTO {schema}.parcels (name) VALUES ('restored row')")
        )
        await conn.execute(
            sa.text(
                f"CREATE VIEW {schema}.parcel_names AS SELECT name FROM {schema}.parcels"
            )
        )


async def _drop_tenant(engine, tenant_id: str) -> None:
    """Remove the tenant whatever state the test left it in.

    Not through ``deprovision_tenant_data_schema``: that refuses on a schema the
    provisioner does not own, which is exactly the state the dry-run and
    failure-path tests leave behind. Per-tenant roles are cluster objects, so
    teardown has to drop them or every run leaks two roles into the cluster the
    other xdist workers share.
    """
    suffix = tenant_id.replace("-", "_")
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM catalog.tenants WHERE id = CAST(:id AS uuid)"),
            {"id": tenant_id},
        )
        await conn.execute(sa.text(f"DROP SCHEMA IF EXISTS data_t_{suffix} CASCADE"))
        for role in (f"geolens_reader_t_{suffix}", f"geolens_writer_t_{suffix}"):
            await conn.execute(
                sa.text(
                    "DO $$ BEGIN "
                    f"IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN "
                    f"EXECUTE 'DROP OWNED BY {role}'; "
                    f"EXECUTE 'DROP ROLE {role}'; "
                    "END IF; END $$"
                )
            )


async def _catalog_snapshot(engine, tenant_id: str) -> list[tuple]:
    """Owners, ACLs, role attributes, and memberships for one tenant."""
    suffix = tenant_id.replace("-", "_")
    async with engine.connect() as conn:
        rows: list[tuple] = []
        rows += list(
            await conn.execute(
                sa.text(
                    "SELECT 'schema', nspname, pg_get_userbyid(nspowner), "
                    "COALESCE(nspacl::text, '') FROM pg_namespace "
                    "WHERE nspname = :schema"
                ),
                {"schema": f"data_t_{suffix}"},
            )
        )
        rows += list(
            await conn.execute(
                sa.text(
                    "SELECT 'relation', relation.relname, "
                    "pg_get_userbyid(relation.relowner), "
                    "COALESCE(relation.relacl::text, '') "
                    "FROM pg_class AS relation "
                    "JOIN pg_namespace AS namespace "
                    "  ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = :schema "
                    "ORDER BY relation.relname"
                ),
                {"schema": f"data_t_{suffix}"},
            )
        )
        rows += list(
            await conn.execute(
                sa.text(
                    "SELECT 'role', rolname, rolcanlogin::text || rolinherit::text "
                    "|| rolsuper::text || rolcreaterole::text || rolbypassrls::text, '' "
                    "FROM pg_roles WHERE rolname LIKE :pattern ORDER BY rolname"
                ),
                {"pattern": f"%{suffix}"},
            )
        )
        rows += list(
            await conn.execute(
                sa.text(
                    "SELECT 'member', granted.rolname, member.rolname, "
                    "membership.admin_option::text || membership.inherit_option::text "
                    "|| membership.set_option::text "
                    "FROM pg_auth_members AS membership "
                    "JOIN pg_roles AS granted ON granted.oid = membership.roleid "
                    "JOIN pg_roles AS member ON member.oid = membership.member "
                    "WHERE granted.rolname LIKE :pattern OR member.rolname LIKE :pattern "
                    "ORDER BY granted.rolname, member.rolname"
                ),
                {"pattern": f"%{suffix}"},
            )
        )
        return [tuple(row) for row in rows]


async def _break_boundary_functions(engine) -> None:
    """Leave the functions exactly as a --no-owner --no-acl restore leaves them."""
    async with engine.begin() as conn:
        current_user = (await conn.execute(sa.text("SELECT current_user"))).scalar_one()
        for name in BOUNDARY_FUNCTIONS:
            signature = f"catalog.{name}(uuid)"
            await conn.execute(
                sa.text(f"ALTER FUNCTION {signature} OWNER TO {current_user}")
            )
            await conn.execute(
                sa.text(f"REVOKE ALL ON FUNCTION {signature} FROM {CONTROL}")
            )
            await conn.execute(
                sa.text(f"GRANT EXECUTE ON FUNCTION {signature} TO PUBLIC")
            )


async def _restore_boundary_functions(engine) -> None:
    async with engine.begin() as conn:
        for name in BOUNDARY_FUNCTIONS:
            signature = f"catalog.{name}(uuid)"
            await conn.execute(
                sa.text(f"ALTER FUNCTION {signature} OWNER TO {PROVISIONER}")
            )
            await conn.execute(
                sa.text(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
            )
            await conn.execute(
                sa.text(f"GRANT EXECUTE ON FUNCTION {signature} TO {CONTROL}")
            )


# ---------------------------------------------------------------------------
# A: reconstruct ownership on a head-schema database
# ---------------------------------------------------------------------------


class TestAdoptionReconstructsOwnership:
    """A: the 0019 end state, reached forward-only at head."""

    async def test_restored_tenant_is_adopted(self):
        tenant_id, schema, reader, writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)

            async with engine.connect() as conn:
                before = await tenant_ownership_state(conn, tenant_id)
            assert not before.adopted
            assert not before.reader_exists
            assert not before.writer_exists
            assert before.relations_not_owned_by_writer == before.relations > 0

            report = await run_adoption(engine, apply=True)
            assert report.failures == {}, report.failures
            assert report.ok

            async with engine.connect() as conn:
                after = await tenant_ownership_state(conn, tenant_id)
                assert after.adopted
                assert after.schema_owner == PROVISIONER
                assert after.relations_not_owned_by_writer == 0
                assert after.relations_without_reader_select == 0

                # The reader reads and cannot write; the data itself survives.
                privileges = (
                    await conn.execute(
                        sa.text(
                            "SELECT has_table_privilege(:reader, :table, 'SELECT'), "
                            "has_table_privilege(:reader, :table, 'INSERT'), "
                            "has_schema_privilege(:reader, :schema, 'USAGE'), "
                            "has_schema_privilege(:writer, :schema, 'CREATE')"
                        ),
                        {
                            "reader": reader,
                            "writer": writer,
                            "schema": schema,
                            "table": f"{schema}.parcels",
                        },
                    )
                ).one()
                assert tuple(privileges) == (True, False, True, True)

                rows = (
                    await conn.execute(
                        sa.text(f"SELECT count(*) FROM {schema}.parcels")
                    )
                ).scalar_one()
                assert rows == 1

                # Per-tenant roles are NOLOGIN/NOINHERIT, and the provisioner
                # holds ADMIN only — no inherit, no SET.
                attributes = (
                    await conn.execute(
                        sa.text(
                            "SELECT rolcanlogin, rolinherit, rolsuper, rolbypassrls "
                            "FROM pg_roles WHERE rolname = :role"
                        ),
                        {"role": reader},
                    )
                ).one()
                assert tuple(attributes) == (False, False, False, False)

                membership = (
                    await conn.execute(
                        sa.text(
                            "SELECT membership.admin_option, membership.inherit_option, "
                            "membership.set_option "
                            "FROM pg_auth_members AS membership "
                            "JOIN pg_roles AS granted ON granted.oid = membership.roleid "
                            "JOIN pg_roles AS member ON member.oid = membership.member "
                            "WHERE granted.rolname = :writer AND member.rolname = :owner"
                        ),
                        {"writer": writer, "owner": PROVISIONER},
                    )
                ).one()
                assert tuple(membership) == (True, False, False)

                # The transaction-scoped SET edge the transfer needs is handed
                # back before commit.
                leftover = (
                    await conn.execute(
                        sa.text(
                            "SELECT count(*) FROM pg_auth_members AS membership "
                            "JOIN pg_roles AS granted ON granted.oid = membership.roleid "
                            "JOIN pg_roles AS member ON member.oid = membership.member "
                            "WHERE granted.rolname = :writer "
                            "AND member.rolname = current_user"
                        ),
                        {"writer": writer},
                    )
                ).scalar_one()
                assert leftover == 0
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_column_owned_sequence_follows_its_table(self):
        """``bigserial``/identity sequences cannot be re-owned directly.

        0019's loop issued ``ALTER SEQUENCE … OWNER TO`` unconditionally, which
        PostgreSQL rejects for a column-owned sequence.  Adoption skips them and
        lets the ``ALTER TABLE`` carry them across.
        """
        tenant_id, schema, reader, writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            report = await run_adoption(engine, apply=True)
            assert report.failures == {}, report.failures

            async with engine.connect() as conn:
                owner = (
                    await conn.execute(
                        sa.text(
                            "SELECT pg_get_userbyid(relation.relowner) "
                            "FROM pg_class AS relation "
                            "JOIN pg_namespace AS namespace "
                            "  ON namespace.oid = relation.relnamespace "
                            "WHERE namespace.nspname = :schema "
                            "AND relation.relname = 'parcels_id_seq'"
                        ),
                        {"schema": schema},
                    )
                ).scalar_one()
                assert owner == writer

                reader_usage = (
                    await conn.execute(
                        sa.text(
                            "SELECT has_sequence_privilege(:reader, :sequence, 'SELECT')"
                        ),
                        {"reader": reader, "sequence": f"{schema}.parcels_id_seq"},
                    )
                ).scalar_one()
                assert reader_usage is True
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()


# ---------------------------------------------------------------------------
# B: a second run is a no-op
# ---------------------------------------------------------------------------


class TestAdoptionIsIdempotent:
    """B: re-running changes nothing, and says so."""

    async def test_second_run_leaves_the_catalog_byte_identical(self):
        tenant_id, schema, _reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            first = await run_adoption(engine, apply=True)
            assert first.failures == {}, first.failures
            snapshot_after_first = await _catalog_snapshot(engine, tenant_id)

            second = await run_adoption(engine, apply=True)
            assert second.failures == {}, second.failures
            assert second.ok
            snapshot_after_second = await _catalog_snapshot(engine, tenant_id)

            assert snapshot_after_second == snapshot_after_first

            # The report distinguishes "already adopted" from "just adopted",
            # which is what tells an operator a re-run did nothing.
            before_states = {state.tenant_id: state for state in second.before}
            assert before_states[tenant_id].adopted
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_dry_run_makes_no_changes(self):
        tenant_id, schema, _reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            snapshot_before = await _catalog_snapshot(engine, tenant_id)

            report = await run_adoption(engine, apply=False)
            assert not report.applied
            # A dry run over an unadopted tenant reports pending work, which is
            # the non-zero exit an operator can script against.
            assert not report.ok

            assert await _catalog_snapshot(engine, tenant_id) == snapshot_before
        finally:
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()


# ---------------------------------------------------------------------------
# C: the dump-restore case — functions already present, wide open
# ---------------------------------------------------------------------------


class TestAdoptionWithRestoredBoundaryFunctions:
    """C: no CREATE FUNCTION collision, and the PUBLIC grant goes away."""

    async def test_restored_functions_are_re_owned_and_re_restricted(self):
        tenant_id, schema, _reader, _writer = _new_tenant()
        engine = _make_engine()
        try:
            await _seed_restored_tenant(engine, tenant_id, schema)
            await _break_boundary_functions(engine)

            async with engine.connect() as conn:
                broken = await boundary_function_states(conn)
            assert len(broken) == len(BOUNDARY_FUNCTIONS)
            assert all(state.public_execute for state in broken)
            assert all(state.owner != PROVISIONER for state in broken)
            assert not any(state.secured for state in broken)

            report = await run_adoption(engine, apply=True)
            assert report.failures == {}, report.failures
            assert report.ok

            async with engine.connect() as conn:
                repaired = await boundary_function_states(conn)
                after = await tenant_ownership_state(conn, tenant_id)
            assert all(state.secured for state in repaired)
            assert all(state.owner == PROVISIONER for state in repaired)
            assert not any(state.public_execute for state in repaired)
            assert after.adopted
        finally:
            await _restore_boundary_functions(engine)
            await _drop_tenant(engine, tenant_id)
            await engine.dispose()

    async def test_missing_function_refuses_instead_of_installing_one(self):
        """Bodies belong to the migrations; adoption never writes one."""
        from app.core.db.tenant_adoption import secure_boundary_functions

        engine = _make_engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "ALTER FUNCTION catalog.deprovision_tenant_data_schema(uuid) "
                        "RENAME TO w998_absent_boundary_function"
                    )
                )
                with pytest.raises(RuntimeError, match="alembic upgrade heads"):
                    await secure_boundary_functions(conn)
        finally:
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "ALTER FUNCTION catalog.w998_absent_boundary_function(uuid) "
                        "RENAME TO deprovision_tenant_data_schema"
                    )
                )
            await _restore_boundary_functions(engine)
            await engine.dispose()


# ---------------------------------------------------------------------------
# D: the boundary is read from the database
# ---------------------------------------------------------------------------


class TestLiveTenantBoundary:
    """D: introspected, never enumerated from a frozen migration constant."""

    async def test_boundary_matches_the_constant_that_drives_rls(self):
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                boundary = await live_tenant_boundary(conn)
        finally:
            await engine.dispose()

        stamped = {table.name for table in boundary if table.has_stamping_trigger}
        assert stamped == set(RLS_TABLES), (
            "The live insert-stamping boundary and app.core.db.rls.RLS_TABLES "
            "have diverged. A table stamped in the database but missing from "
            "RLS_TABLES never gets RLS enabled at boot."
        )
        assert boundary_drift(boundary) == ([], [])

        # 0018's frozen tuple is six tables; the live boundary outgrew it long
        # ago. Anything reading that constant would under-report by three.
        assert len(stamped) > 6

    async def test_dormant_tenant_id_columns_are_reported_outside_the_boundary(self):
        """0037's ``dataset_refresh_runs.tenant_id`` is deliberately dormant.

        Reporting it as "tenant_id column only" is what lets an accidental
        omission be told apart from this intentional one.
        """
        engine = _make_engine()
        try:
            async with engine.connect() as conn:
                boundary = await live_tenant_boundary(conn)
        finally:
            await engine.dispose()

        dormant = {
            table.name
            for table in boundary
            if table.has_tenant_id and not table.has_stamping_trigger
        }
        assert "dataset_refresh_runs" in dormant
        assert dormant.isdisjoint(set(RLS_TABLES))


# ---------------------------------------------------------------------------
# The runbook recipe and the module it invokes
# ---------------------------------------------------------------------------


def test_runbook_documents_the_forward_only_recipe() -> None:
    """A rename that orphans the DR recipe must fail here, not mid-recovery."""
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")

    assert "python -m app.core.db.tenant_adoption --apply" in runbook
    # The destructive downgrade is documented as the thing NOT to reach for,
    # not as the recipe (#998).
    assert "#### Do not reach for `alembic downgrade 0016`" in runbook
    assert "uv run --no-dev alembic downgrade 0016" not in runbook


def test_module_is_runnable_as_documented() -> None:
    import importlib

    module = importlib.import_module("app.core.db.tenant_adoption")

    assert callable(module._main)
    parser = module._build_parser()
    assert parser.parse_args([]).apply is False
    assert parser.parse_args(["--apply"]).apply is True
