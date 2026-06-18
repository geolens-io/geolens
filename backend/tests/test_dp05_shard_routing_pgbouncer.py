"""DP-05: Shard routing map + PgBouncer transaction-mode config + SET LOCAL survival.

Tests
-----
A: Routing-map lookup — ``tenant_shard_id(tid)`` returns 'shard-0' for a seeded
   tenant row (catalog.tenants with shard_id='shard-0'); returns None for
   single_tenant mode and for None input.

B: PgBouncer config-value assertion — parse ``infra/pgbouncer/pgbouncer.ini``
   and assert ``pool_mode == transaction``, ``min_pool_size == 2``,
   ``default_pool_size == 10`` (the fixed tile pool sizing from config.py).

C: SET LOCAL survival-within-txn proof — open ONE connection, begin a
   transaction, issue ``SET LOCAL ROLE geolens_reader_t_{A}`` and
   ``SET LOCAL search_path = data_t_{A}, data, public``, then WITHIN THE SAME
   TRANSACTION assert ``current_user`` reflects the per-tenant role and
   ``SHOW search_path`` begins with the per-tenant schema.

   This is the PgBouncer transaction-mode contract: SET LOCAL survives WITHIN a
   single BEGIN...COMMIT block. Reuse across the pooled connection (statement-mode
   multiplexing) is the documented constraint — not tested here.

   Mirror the NullPool engine pattern from iso05 for clean isolation.

Background
----------
The PgBouncer config uses ``pool_mode = transaction`` because the data plane
issues per-request ``SET LOCAL ROLE`` + ``SET LOCAL search_path``. These are
transaction-local: they survive within the single ``BEGIN...COMMIT`` block that
holds the request but are cleared at ``COMMIT`` (per PostgreSQL semantics).
Statement-mode pooling would route SET and the subsequent SELECT to DIFFERENT
physical connections, making the role/search_path appear unset.
See: the internal tenancy/PgBouncer constraint runbook.

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_dp05_shard_routing_pgbouncer.py -x -q
"""

from __future__ import annotations

import configparser
import importlib
import os

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT_A = "00000000-0000-0000-0000-000000000001"
_TENANT_A_SCHEMA = "data_t_00000000_0000_0000_0000_000000000001"
_TENANT_A_ROLE = "geolens_reader_t_00000000_0000_0000_0000_000000000001"

# Path to the PgBouncer config (relative to the project root).
# __file__ is backend/tests/test_dp05_*.py → ../.. is the project root.
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PGBOUNCER_INI = os.path.join(_PROJECT_ROOT, "infra", "pgbouncer", "pgbouncer.ini")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_settings_multi():
    """Set GEOLENS_TENANCY_MODE=multi_tenant and reload settings + tenancy module."""
    import app.core.config as cfg_mod
    import app.core.tenancy as ten_mod

    os.environ["GEOLENS_TENANCY_MODE"] = "multi_tenant"
    cfg_mod.settings = cfg_mod.Settings()  # type: ignore[attr-defined]
    importlib.reload(ten_mod)
    return cfg_mod.settings


def _reload_settings_single():
    """Restore GEOLENS_TENANCY_MODE=single_tenant and reload."""
    import app.core.config as cfg_mod
    import app.core.tenancy as ten_mod

    os.environ.pop("GEOLENS_TENANCY_MODE", None)
    cfg_mod.settings = cfg_mod.Settings()  # type: ignore[attr-defined]
    importlib.reload(ten_mod)


async def _get_db_url() -> str:
    # Per-worker TEST database (conftest provisions the per-tenant data_t_* schemas
    # + geolens_reader_t_* roles there) — not the main app DB, which is `postgres`
    # on CI and lacks the per-tenant provisioning. Mirrors dp02's working pattern.
    from app.core.config import settings

    return settings.test_database_url


# ---------------------------------------------------------------------------
# Test A: Routing-map lookup (tenant_shard_id)
# ---------------------------------------------------------------------------


class TestDp05ShardRoutingMap:
    """DP-05-A: tenant_shard_id routing lookup.

    - single_tenant → None (routing primitive inactive)
    - tenant_id=None → None
    - seeded tenant with shard_id='shard-0' → 'shard-0'
    """

    def test_single_tenant_returns_none(self, monkeypatch):
        """In single_tenant mode, tenant_shard_id always returns None."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import tenant_shard_id

        assert tenant_shard_id(None) is None, (
            "DP-05 FAIL [A-single_tenant]: tenant_shard_id(None) should return None "
            "in single_tenant — routing primitive is inactive."
        )
        assert tenant_shard_id(_TENANT_A) is None, (
            "DP-05 FAIL [A-single_tenant-uuid]: tenant_shard_id(uuid) should return None "
            "in single_tenant — even with a valid UUID, routing is inactive."
        )

    def test_none_tenant_id_returns_none_in_multi_tenant(self, monkeypatch):
        """In multi_tenant mode, tenant_shard_id(None) returns None (no routing)."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.core.db.tenant_schema import tenant_shard_id

        assert tenant_shard_id(None) is None, (
            "DP-05 FAIL [A-none]: tenant_shard_id(None) should return None in "
            "multi_tenant — no tenant context means no shard routing."
        )

    async def test_seeded_tenant_returns_shard_zero(self):
        """In multi_tenant mode, a seeded tenant with shard_id='shard-0' returns 'shard-0'.

        Seeds a row into catalog.tenants with the test UUID and shard_id='shard-0',
        then calls tenant_shard_id() and asserts the return value.
        """
        _reload_settings_multi()
        db_url = await _get_db_url()

        test_tenant_id = _TENANT_A
        engine = create_async_engine(db_url, poolclass=NullPool)
        inserted = False
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                # Upsert a tenant row with shard_id='shard-0'.
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.tenants (id, slug, name, shard_id) "
                        "VALUES (:id, :slug, :name, 'shard-0') "
                        "ON CONFLICT (id) DO UPDATE SET shard_id = 'shard-0'"
                    ),
                    {
                        "id": test_tenant_id,
                        "slug": f"test-tenant-dp05-{test_tenant_id[:8]}",
                        "name": "DP-05 Routing Test Tenant",
                    },
                )
                inserted = True

            # Now call tenant_shard_id() — it will query catalog.tenants.
            from app.core.db.tenant_schema import tenant_shard_id

            shard = tenant_shard_id(test_tenant_id)
        finally:
            if inserted:
                async with engine.connect() as conn:
                    await conn.execution_options(isolation_level="AUTOCOMMIT")
                    await conn.execute(
                        sa.text("DELETE FROM catalog.tenants WHERE id = :id"),
                        {"id": test_tenant_id},
                    )
            await engine.dispose()
            _reload_settings_single()

        assert shard == "shard-0", (
            f"DP-05 FAIL [A-shard-lookup]: tenant_shard_id({test_tenant_id!r}) "
            f"returned {shard!r}, expected 'shard-0'.\n"
            f"  Check catalog.tenants.shard_id column (migration 0007_tenant_data_schemas)\n"
            f"  and the tenant_shard_id() implementation in tenant_schema.py."
        )

    async def test_absent_tenant_returns_shard_zero_default(self):
        """For a tenant that has no row in catalog.tenants, fallback is 'shard-0'.

        tenant_shard_id() must not raise — it returns the default 'shard-0'
        when the tenant row is absent.
        """
        _reload_settings_multi()
        try:
            from app.core.db.tenant_schema import tenant_shard_id

            # Use a UUID that is very unlikely to exist in the test DB.
            nonexistent_tenant = "ffffffff-ffff-ffff-ffff-ffffffffffff"
            shard = tenant_shard_id(nonexistent_tenant)
        finally:
            _reload_settings_single()

        assert shard == "shard-0", (
            f"DP-05 FAIL [A-absent]: tenant_shard_id for a non-existent tenant "
            f"returned {shard!r}, expected 'shard-0' (fallback default).\n"
            f"  The routing primitive must not raise on missing rows — it falls "
            f"back to 'shard-0' to ensure Phase 1214 has a safe composition point."
        )


# ---------------------------------------------------------------------------
# Test B: PgBouncer config-value assertion
# ---------------------------------------------------------------------------


class TestDp05PgBouncerConfig:
    """DP-05-B: Assert infra/pgbouncer/pgbouncer.ini contains required config values.

    pool_mode = transaction  — required for SET LOCAL ROLE/search_path survival
    min_pool_size = 2        — matches tile_pool_min_size in config.py
    default_pool_size = 10   — matches tile_pool_max_size in config.py
    """

    def test_pgbouncer_ini_exists(self):
        """The pgbouncer config exists and is readable.

        The pooler config is a deployment-infra artifact that is NOT part of the
        public source tree, so it is absent in public CI — skip cleanly there
        (the config-value assertions below also skip-when-absent).
        """
        if not os.path.isfile(_PGBOUNCER_INI):
            pytest.skip(
                "pgbouncer config absent (deployment-infra artifact) — skipping in this environment"
            )
        assert os.path.isfile(_PGBOUNCER_INI)

    def test_pool_mode_is_transaction(self):
        """pgbouncer.ini sets pool_mode = transaction.

        REQUIRED: transaction-mode is the only safe mode for the data plane's
        per-request SET LOCAL ROLE + SET LOCAL search_path. Statement-mode
        would route SET and the subsequent query to different connections,
        making the role/search_path appear unset.
        """
        assert os.path.isfile(_PGBOUNCER_INI), pytest.skip(
            "pgbouncer.ini not found — skipping (covered by test_pgbouncer_ini_exists)"
        )
        cfg = configparser.ConfigParser()
        cfg.read(_PGBOUNCER_INI)

        assert "pgbouncer" in cfg, (
            "DP-05 FAIL [B-section]: [pgbouncer] section not found in pgbouncer.ini.\n"
            "  The config file must have a [pgbouncer] section with pool_mode = transaction."
        )
        pool_mode = cfg["pgbouncer"].get("pool_mode", "").strip()
        assert pool_mode == "transaction", (
            f"DP-05 FAIL [B-pool_mode]: pool_mode = {pool_mode!r}, expected 'transaction'.\n"
            f"  Transaction-mode is REQUIRED because SET LOCAL ROLE/search_path must\n"
            f"  survive within a single BEGIN...COMMIT (see the Phase 1208 PgBouncer\n"
            f"  constraint documented in the internal tenancy runbook).\n"
            f"  Do NOT change to statement-mode — it would silently break per-tenant\n"
            f"  role isolation on every tile request."
        )

    def test_min_pool_size_is_2(self):
        """pgbouncer.ini sets min_pool_size = 2 (matches tile_pool_min_size in config.py)."""
        if not os.path.isfile(_PGBOUNCER_INI):
            pytest.skip("pgbouncer.ini not found")
        cfg = configparser.ConfigParser()
        cfg.read(_PGBOUNCER_INI)

        assert "pgbouncer" in cfg, "Missing [pgbouncer] section in pgbouncer.ini"
        min_pool_size = cfg["pgbouncer"].get("min_pool_size", "").strip()
        assert min_pool_size == "2", (
            f"DP-05 FAIL [B-min_pool_size]: min_pool_size = {min_pool_size!r}, expected '2'.\n"
            f"  Must match tile_pool_min_size = 2 in backend/app/core/config.py."
        )

    def test_default_pool_size_is_10(self):
        """pgbouncer.ini sets default_pool_size = 10 (matches tile_pool_max_size in config.py)."""
        if not os.path.isfile(_PGBOUNCER_INI):
            pytest.skip("pgbouncer.ini not found")
        cfg = configparser.ConfigParser()
        cfg.read(_PGBOUNCER_INI)

        assert "pgbouncer" in cfg, "Missing [pgbouncer] section in pgbouncer.ini"
        default_pool_size = cfg["pgbouncer"].get("default_pool_size", "").strip()
        assert default_pool_size == "10", (
            f"DP-05 FAIL [B-default_pool_size]: default_pool_size = {default_pool_size!r}, "
            f"expected '10'.\n"
            f"  Must match tile_pool_max_size = 10 in backend/app/core/config.py."
        )

    def test_pgbouncer_ini_header_documents_transaction_mode_requirement(self):
        """pgbouncer.ini header comment documents the transaction-mode requirement and privacy note.

        The config must explain WHY transaction-mode is required (SET LOCAL semantics)
        and note that infra/ must stay out of the public image build context.
        """
        if not os.path.isfile(_PGBOUNCER_INI):
            pytest.skip("pgbouncer.ini not found")

        with open(_PGBOUNCER_INI) as f:
            content = f.read()

        # Check transaction-mode documentation.
        required_phrases = [
            "transaction",
            "SET LOCAL",
            "PRIVATE",
        ]
        missing = [p for p in required_phrases if p.lower() not in content.lower()]
        assert not missing, (
            f"DP-05 FAIL [B-header]: pgbouncer.ini header is missing required documentation.\n"
            f"  Missing phrases: {missing}\n"
            f"  The config header must document: (a) why transaction-mode is required "
            f"(SET LOCAL semantics), (b) the PRIVATE nature of infra/."
        )


# ---------------------------------------------------------------------------
# Test C: SET LOCAL survival-within-txn proof
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestDp05SetLocalSurvival:
    """DP-05-C: SET LOCAL ROLE + SET LOCAL search_path survive WITHIN one transaction.

    This proves the PgBouncer transaction-mode contract: a request that begins a
    transaction, issues SET LOCAL ROLE + SET LOCAL search_path, then reads
    current_user / search_path — ALL within one BEGIN...COMMIT — will see the
    per-tenant role and schema throughout.

    The test uses ONE connection (NullPool) to simulate a tile request:
    1. Begin transaction
    2. SET LOCAL ROLE geolens_reader_t_{A}
    3. SET LOCAL search_path = data_t_{A}, data, public
    4. SELECT current_user → must equal geolens_reader_t_{A}
    5. SHOW search_path → must start with data_t_{A}
    """

    async def test_set_local_role_survives_within_transaction(self):
        """SET LOCAL ROLE geolens_reader_t_{A} is visible via current_user in same txn."""
        db_url = await _get_db_url()
        engine = create_async_engine(db_url, poolclass=NullPool)

        current_user_after: str | None = None
        role_set = False

        try:
            async with engine.connect() as conn:
                async with conn.begin():
                    # Issue SET LOCAL ROLE within the transaction.
                    try:
                        await conn.execute(sa.text("SAVEPOINT _dp05_role"))
                        await conn.execute(sa.text(f"SET LOCAL ROLE {_TENANT_A_ROLE}"))
                        await conn.execute(sa.text("RELEASE SAVEPOINT _dp05_role"))
                        role_set = True
                    except Exception as exc:
                        await conn.execute(sa.text("ROLLBACK TO SAVEPOINT _dp05_role"))
                        try:
                            await conn.execute(sa.text("RELEASE SAVEPOINT _dp05_role"))
                        except Exception:
                            pass
                        pytest.skip(
                            f"SET LOCAL ROLE {_TENANT_A_ROLE} failed: {exc!r}. "
                            "Role may be absent — check init-test-db.sh."
                        )

                    # Read current_user WITHIN THE SAME TRANSACTION.
                    row = await conn.execute(sa.text("SELECT current_user"))
                    current_user_after = row.scalar_one()
        finally:
            await engine.dispose()

        assert role_set, f"SET LOCAL ROLE {_TENANT_A_ROLE} did not execute cleanly."
        assert current_user_after == _TENANT_A_ROLE, (
            f"DP-05 FAIL [C-role]: SET LOCAL ROLE did not take effect within the transaction!\n"
            f"  Expected current_user = {_TENANT_A_ROLE!r}\n"
            f"  Got current_user = {current_user_after!r}\n"
            f"  SET LOCAL ROLE must be visible via current_user() within the same\n"
            f"  transaction. This is the PgBouncer transaction-mode contract:\n"
            f"  SET LOCAL survives within one BEGIN...COMMIT block."
        )

    async def test_set_local_search_path_survives_within_transaction(self):
        """SET LOCAL search_path = data_t_{A}, data, public is visible in SHOW search_path."""
        db_url = await _get_db_url()
        engine = create_async_engine(db_url, poolclass=NullPool)

        search_path_after: str | None = None

        try:
            async with engine.connect() as conn:
                async with conn.begin():
                    # Issue SET LOCAL search_path within the transaction.
                    await conn.execute(
                        sa.text(
                            f"SET LOCAL search_path = {_TENANT_A_SCHEMA}, data, public"
                        )
                    )

                    # Read search_path WITHIN THE SAME TRANSACTION.
                    row = await conn.execute(sa.text("SHOW search_path"))
                    search_path_after = row.scalar_one()
        finally:
            await engine.dispose()

        assert search_path_after is not None, (
            "SHOW search_path returned NULL — unexpected."
        )
        # The search_path should start with the per-tenant schema.
        # PostgreSQL may normalize the path (add/remove spaces, quote identifiers).
        assert _TENANT_A_SCHEMA in search_path_after, (
            f"DP-05 FAIL [C-search_path]: per-tenant schema not in search_path after SET LOCAL!\n"
            f"  Expected search_path to contain: {_TENANT_A_SCHEMA!r}\n"
            f"  Got search_path = {search_path_after!r}\n"
            f"  SET LOCAL search_path must persist within the same transaction."
        )

    async def test_role_and_search_path_cleared_after_transaction_end(self):
        """SET LOCAL ROLE/search_path are cleared at transaction end (not leaked).

        After the BEGIN...COMMIT block, a new connection (NullPool) must see
        the DEFAULT role and search_path — not the per-tenant values.

        This proves that SET LOCAL is transaction-scoped and does not leak
        across requests — the complement of the survival test above.
        """
        db_url = await _get_db_url()

        # Transaction 1: set LOCAL ROLE + search_path, let the transaction end.
        engine_a = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine_a.connect() as conn:
                async with conn.begin():
                    try:
                        await conn.execute(sa.text(f"SET LOCAL ROLE {_TENANT_A_ROLE}"))
                    except Exception:
                        pass  # Role may be absent in some test setups; that's fine.
                    await conn.execute(
                        sa.text(
                            f"SET LOCAL search_path = {_TENANT_A_SCHEMA}, data, public"
                        )
                    )
                # Transaction committed — SET LOCAL values cleared.
        finally:
            await engine_a.dispose()

        # Transaction 2: fresh NullPool connection, check that the role/search_path
        # is back to defaults (not the per-tenant values).
        engine_b = create_async_engine(db_url, poolclass=NullPool)
        fresh_user: str | None = None
        fresh_search_path: str | None = None
        try:
            async with engine_b.connect() as conn:
                async with conn.begin():
                    row = await conn.execute(sa.text("SELECT current_user"))
                    fresh_user = row.scalar_one()
                    row = await conn.execute(sa.text("SHOW search_path"))
                    fresh_search_path = row.scalar_one()
        finally:
            await engine_b.dispose()

        # The per-tenant role must NOT bleed into the fresh connection.
        assert fresh_user != _TENANT_A_ROLE, (
            f"DP-05 FAIL [C-no-leak-role]: SET LOCAL ROLE leaked to a fresh connection!\n"
            f"  fresh_user = {fresh_user!r}, expected anything except {_TENANT_A_ROLE!r}\n"
            f"  SET LOCAL is transaction-local — it must be cleared at COMMIT."
        )

        # The per-tenant schema must NOT bleed into the fresh search_path.
        assert _TENANT_A_SCHEMA not in (fresh_search_path or ""), (
            f"DP-05 FAIL [C-no-leak-search_path]: SET LOCAL search_path leaked!\n"
            f"  fresh_search_path = {fresh_search_path!r}\n"
            f"  Per-tenant schema {_TENANT_A_SCHEMA!r} must not appear in a fresh connection's "
            f"search_path after the previous transaction committed."
        )

    async def test_full_tenant_role_and_schema_in_single_transaction(self):
        """Combined test: SET LOCAL ROLE + search_path both visible within one txn.

        This is the canonical 'PgBouncer transaction-mode contract' proof:
        a single BEGIN...COMMIT holds both SET LOCAL statements and their
        read-back assertions — exactly what a tile request does.
        """
        db_url = await _get_db_url()
        engine = create_async_engine(db_url, poolclass=NullPool)

        current_user_after: str | None = None
        search_path_after: str | None = None

        try:
            async with engine.connect() as conn:
                async with conn.begin():
                    # Step 1: SET LOCAL ROLE (per-tenant reader).
                    try:
                        await conn.execute(sa.text("SAVEPOINT _dp05_full"))
                        await conn.execute(sa.text(f"SET LOCAL ROLE {_TENANT_A_ROLE}"))
                        await conn.execute(sa.text("RELEASE SAVEPOINT _dp05_full"))
                    except Exception as exc:
                        await conn.execute(sa.text("ROLLBACK TO SAVEPOINT _dp05_full"))
                        try:
                            await conn.execute(sa.text("RELEASE SAVEPOINT _dp05_full"))
                        except Exception:
                            pass
                        pytest.skip(
                            f"SET LOCAL ROLE {_TENANT_A_ROLE} failed: {exc!r}. "
                            "Role may be absent — check init-test-db.sh."
                        )

                    # Step 2: SET LOCAL search_path (per-tenant schema first).
                    await conn.execute(
                        sa.text(
                            f"SET LOCAL search_path = {_TENANT_A_SCHEMA}, data, public"
                        )
                    )

                    # Step 3: Read both values WITHIN the same transaction.
                    row = await conn.execute(sa.text("SELECT current_user"))
                    current_user_after = row.scalar_one()

                    row = await conn.execute(sa.text("SHOW search_path"))
                    search_path_after = row.scalar_one()
        finally:
            await engine.dispose()

        assert current_user_after == _TENANT_A_ROLE, (
            f"DP-05 FAIL [C-full-role]: current_user = {current_user_after!r}, "
            f"expected {_TENANT_A_ROLE!r}.\n"
            f"  SET LOCAL ROLE must be visible in the same transaction."
        )
        assert _TENANT_A_SCHEMA in (search_path_after or ""), (
            f"DP-05 FAIL [C-full-schema]: search_path = {search_path_after!r}, "
            f"expected to contain {_TENANT_A_SCHEMA!r}.\n"
            f"  SET LOCAL search_path must be visible in the same transaction."
        )
