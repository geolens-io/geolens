import os
import time
import uuid
import tempfile
import warnings

import pytest
import sqlalchemy
import structlog
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.providers.local import hash_password
from app.platform.cache import init_cache
from app.core.config import settings

# Captured at module load (and refreshed in pytest_configure) so any test that
# reads it does not race the fixture body's mutation. Defaults to "master" when
# pytest-xdist is not active (sequential `pytest` or `pytest -x` runs).
_WORKER_ID = os.environ.get("PYTEST_XDIST_WORKER", "master")


def _derive_test_pool_sizing() -> tuple[int, int]:
    """Return (pool_size, max_overflow) sized to live within Postgres max_connections.

    Sequential mode (worker_id == "master") keeps the historical (5, 2) pool that
    the suite was built against. Under pytest-xdist, returns (1, 0) as a signal
    value; see _is_xdist_worker() below. The actual engine uses NullPool in xdist
    mode (no persistent idle connections).

    The (5, 2) sequential default is preserved because request handlers in some
    tests (e.g., reupload, IDOR) need >1 concurrent conn within a single test.
    The v1018 sequential baseline (3025/0/38 in 539s) is the regression floor.

    See .planning/audits/PYTEST-XDIST-SPIKE-v1019.md for measured numbers + rationale.
    """
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    if worker_id == "master":
        return (5, 2)
    # Under xdist: use (1, 0) as a sentinel; the engine creation switches to
    # NullPool which has no persistent idle connections. Connections are only
    # open during active DB operations, minimising the concurrent-connection
    # fan-out across 16 workers against max_connections=30.
    return (1, 0)


def _make_test_async_engine(test_database_url: str):
    """Create the async test engine for this worker.

    xdist workers (PYTEST_XDIST_WORKER != 'master') use NullPool — no idle
    connections persist between tests, keeping concurrent connection count within
    max_connections=30 when 16 workers run simultaneously.

    Sequential mode uses the historical (5, 2) QueuePool so request handlers that
    need multiple concurrent DB connections within a single test still work.

    This helper is extracted for direct testability (see test_conftest_pool_sizing.py
    test_xdist_engine_uses_nullpool / test_sequential_engine_uses_queuepool).
    """
    is_xdist = os.environ.get("PYTEST_XDIST_WORKER", "master") != "master"
    if is_xdist:
        return create_async_engine(test_database_url, poolclass=NullPool, echo=False)
    pool_size, max_overflow = _derive_test_pool_sizing()
    return create_async_engine(
        test_database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=30,
        echo=False,
    )


# Per-worker setup stagger — spreads the startup connection spike across time.
#
# Root-cause: when N workers run _test_db_lifecycle simultaneously, each opens
# a sync SQLAlchemy connection to the main DB (dev_engine) PLUS connections to
# their test DB (test_engine_sync, alembic, _saml_bridge_engine). With
# N=16 workers and max_connections=30 (db/postgresql.conf:11), and the running
# API/worker services already holding 8 persistent idle connections, the
# concurrent setup fan-out saturates Postgres before any test runs.
#
# Fix: stagger each worker's startup by SETUP_STAGGER_SECONDS × worker_num.
# Alembic migration (22 steps) takes ≈ 3-5s per worker. With a 5.0s stagger:
#   - Worker 0 starts immediately (no delay)
#   - Worker 1 starts after 5.0s (worker 0 is already past migration)
#   - Worker k starts after k × 5.0s
# Peak concurrent main-DB connections during stagger window: ~1-2.
# Safe under max_connections=30.
#
# This approach is O(STAGGER_SECONDS × worker_num) total overhead vs. O(N × setup_time)
# for a hard serialiser — wall-clock impact is bounded by the LAST worker's stagger
# (15 × 5.0s = 75s), not the sum.
#
# See .planning/audits/PYTEST-XDIST-SPIKE-v1019.md for measured numbers + rationale.
# Combined with NullPool for async engines (no idle connections post-setup),
# the fix addresses both the setup-phase spike and the test-phase connection budget.
# Setup phase per worker: dev_engine + test_engine_sync + alembic (22 steps) +
# _saml_bridge_engine ≈ 3-5 seconds total. Stagger must be ≥ setup time so at
# most 1 worker is in the migration phase at any time. Use 5s with some headroom.
# Impact: last worker (gw15) delays 15 × 5 = 75s. Total parallel wall clock:
#   75s (stagger overhead) + ~80s (test execution) ≈ 155s vs sequential 539s.
_SETUP_STAGGER_SECONDS = 5.0


def _get_setup_stagger_delay() -> float:
    """Return the number of seconds this worker should sleep before running setup.

    Sequential mode (master) or unrecognised worker ID returns 0.0 — no stagger needed.
    xdist worker gw0 returns 0.0, gw1 returns 5.0, gw15 returns 75.0.

    Note: if xdist changes its worker ID format (currently 'gwN'), unrecognised
    IDs silently return 0.0, defeating the stagger for those workers.
    """
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    if not worker_id.startswith("gw"):
        return 0.0
    try:
        worker_num = int(worker_id[2:])
    except ValueError:
        warnings.warn(
            f"Unexpected PYTEST_XDIST_WORKER format: {worker_id!r}; stagger disabled",
            stacklevel=2,
        )
        return 0.0
    return worker_num * _SETUP_STAGGER_SECONDS


def pytest_configure(config):
    """Re-capture the pytest-xdist worker id under config-time hooks.

    pytest-xdist injects ``config.workerinput['workerid']`` (e.g. ``"gw0"``)
    when running parallel workers. Mirror it back into the module-level
    ``_WORKER_ID`` constant + ``PYTEST_XDIST_WORKER`` env var so the
    test-DB naming helper sees a stable value regardless of whether the
    plugin set the env var itself.
    """
    global _WORKER_ID
    workerinput = getattr(config, "workerinput", None)
    if workerinput is not None:
        worker_id = workerinput.get("workerid", "master")
        _WORKER_ID = worker_id
        # Mirror into env so any subprocess (or late import) also sees it.
        os.environ["PYTEST_XDIST_WORKER"] = worker_id

# Shared test geometries
EMPTY_FEATURE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [],
}

POINT_GEOJSON = {
    "type": "Point",
    "coordinates": [-73.9857, 40.7484],
}

POLYGON_GEOJSON = {
    "type": "Polygon",
    "coordinates": [
        [[-74.0, 40.7], [-73.9, 40.7], [-73.9, 40.8], [-74.0, 40.8], [-74.0, 40.7]]
    ],
}


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
def community_edition(monkeypatch):
    from app.core.edition import init_edition

    monkeypatch.delenv("GEOLENS_EDITION", raising=False)
    init_edition([])
    yield
    init_edition([])


@pytest.fixture
def enterprise_edition(monkeypatch):
    from app.core.edition import init_edition

    monkeypatch.delenv("GEOLENS_EDITION", raising=False)
    init_edition(["enterprise"])
    yield
    init_edition([])


def _quote_database_identifier(db_name: str) -> str:
    return '"' + db_name.replace('"', '""') + '"'


def _worker_test_database_name(base_name: str) -> str:
    """Compose a per-worker, per-session test DB name within PG's 63-char limit.

    Layout: ``{safe_base}_{worker_id}_{8-hex-uuid}``

    The worker_id is read fresh from the ``PYTEST_XDIST_WORKER`` env var so
    callers (e.g. the regression test) can manipulate the value via
    ``monkeypatch`` without relying on module-load-time capture. When the
    env var is unset (sequential pytest, ``-x``, IDE runners), the worker_id
    defaults to ``"master"`` — this gives the legacy single-session DB its
    own non-empty namespace token, preventing collisions with concurrent
    xdist runs against the same Postgres server.
    """
    suffix = uuid.uuid4().hex[:8]
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    # Reserve space for `_{worker_id}_{suffix}` in the 63-char identifier budget.
    overhead = len(worker_id) + len(suffix) + 2  # two underscores
    max_base_len = 63 - overhead
    safe_base = (base_name or "geolens_test")[:max_base_len].rstrip("_")
    return f"{safe_base or 'geolens'}_{worker_id}_{suffix}"


def _drop_test_database_if_exists(db_name: str) -> None:
    teardown_engine = sqlalchemy.create_engine(
        settings.database_url_sync, isolation_level="AUTOCOMMIT"
    )
    try:
        with teardown_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db_name AND pid <> pg_backend_pid()"
                ),
                {"db_name": db_name},
            )
            conn.execute(
                text(f"DROP DATABASE IF EXISTS {_quote_database_identifier(db_name)}")
            )
    except Exception:
        pass
    finally:
        teardown_engine.dispose()


@pytest.fixture(autouse=True, scope="session")
def _test_db_lifecycle():
    """Create, migrate, and tear down the test database once per session.

    Uses sync SQLAlchemy because CREATE/DROP DATABASE require AUTOCOMMIT
    isolation which is simpler with the synchronous driver.

    Gracefully skips DB setup when database host is unreachable (e.g. pure
    unit test runs outside Docker). Tests that require DB will fail with a
    clear connection error; DB-independent tests will run normally.
    """
    original_test_db_name = settings.postgres_db_test
    db_name = _worker_test_database_name(original_test_db_name)
    settings.postgres_db_test = db_name
    should_drop_db = False

    # Stagger startup to prevent simultaneous connection spikes.
    # See _get_setup_stagger_delay() and _SETUP_STAGGER_SECONDS for rationale.
    _stagger_delay = _get_setup_stagger_delay()
    if _stagger_delay > 0:
        time.sleep(_stagger_delay)

    try:
        # --- Setup: create test database ---
        dev_engine = sqlalchemy.create_engine(
            settings.database_url_sync, isolation_level="AUTOCOMMIT"
        )
        try:
            with dev_engine.connect() as conn:
                # Drop if exists for a clean slate
                quoted_db_name = _quote_database_identifier(db_name)
                conn.execute(text(f"DROP DATABASE IF EXISTS {quoted_db_name}"))
                conn.execute(text(f"CREATE DATABASE {quoted_db_name}"))
            should_drop_db = True
        except Exception:
            # DB host unreachable — skip full setup; unit tests unaffected
            yield
            return
        finally:
            dev_engine.dispose()

        # --- Init: extensions, schemas, roles ---
        test_engine_sync = sqlalchemy.create_engine(settings.test_database_url_sync)
        try:
            with test_engine_sync.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent"))
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS catalog"))
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS data"))

                # Idempotent role grants
                conn.execute(
                    text(
                        "DO $$ BEGIN "
                        "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'geolens_reader') THEN "
                        "CREATE ROLE geolens_reader NOLOGIN; "
                        "END IF; END $$"
                    )
                )
                conn.execute(text("GRANT USAGE ON SCHEMA data TO geolens_reader"))
                conn.execute(
                    text("GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_reader")
                )
                conn.execute(
                    text(
                        "ALTER DEFAULT PRIVILEGES IN SCHEMA data "
                        "GRANT SELECT ON TABLES TO geolens_reader"
                    )
                )
                conn.commit()
        except SQLAlchemyError:
            # DB is reachable but missing required extensions (for example pgvector).
            # Let DB-light tests run; DB-backed tests will fail when they request DB fixtures.
            test_engine_sync.dispose()
            _drop_test_database_if_exists(db_name)
            should_drop_db = False
            yield
            return
        test_engine_sync.dispose()

        # --- Migrate: run alembic against the test database ---
        from alembic import command
        from alembic.config import Config as AlembicConfig

        alembic_cfg = AlembicConfig("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
        # Pre-set version_locations from the geolens.migrations entry-point group
        # before invoking command.upgrade. The env.py also performs this discovery,
        # but ScriptDirectory is constructed before env.py runs and caches the
        # version_locations from the cfg at construction time -- so an env.py-time
        # mutation does not propagate to the upgrade walk. Setting here ensures
        # enterprise branch heads (e.g. e002_add_saml_columns) participate in
        # `heads` (plural) discovery alongside the core head.
        import pathlib as _pathlib
        from importlib.metadata import entry_points as _entry_points

        _enterprise_paths: list[str] = []
        for _ep in _entry_points(group="geolens.migrations"):
            try:
                _fn = _ep.load()
                if callable(_fn):
                    for _p in _fn():
                        if _pathlib.Path(_p).is_dir():
                            _enterprise_paths.append(_p)
            except Exception:
                pass  # Non-fatal; core migrations still run.
        if _enterprise_paths:
            _base_versions = (
                alembic_cfg.get_main_option("version_locations") or "alembic/versions"
            )
            alembic_cfg.set_main_option(
                "version_locations",
                _base_versions + " " + " ".join(_enterprise_paths),
            )

        # Use "heads" (plural) so any enterprise migration branches discovered
        # above are upgraded alongside core. With community-only installs, "heads"
        # behaves identically to "head" because there is only one head; with
        # enterprise installed, this picks up the enterprise branch.
        command.upgrade(alembic_cfg, "heads")

        # --- SAML column bridge (community-only test environments) ---
        # The four SAML columns on catalog.oauth_providers are normally added by the
        # enterprise migration e002_add_saml_columns. When geolens-enterprise is NOT
        # installed, those columns are absent from the test DB. SQLAlchemy still
        # includes them in INSERTs (deferred=True only suppresses SELECT loading,
        # not INSERT column lists), causing UndefinedColumnError in any test that
        # seeds an OAuthProvider row directly.
        #
        # This bridge detects the missing columns and adds them idempotently,
        # mirroring what e002_add_saml_columns does. It only fires when the enterprise
        # package is absent (i.e. _enterprise_paths is empty), so enterprise CI is
        # unaffected.
        if not _enterprise_paths:
            _saml_bridge_engine = sqlalchemy.create_engine(
                settings.test_database_url_sync
            )
            with _saml_bridge_engine.connect() as _conn:
                # Check whether idp_entity_id already exists; if not, add all four.
                _result = _conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'catalog' "
                        "AND table_name = 'oauth_providers' "
                        "AND column_name = 'idp_entity_id'"
                    )
                )
                if _result.fetchone() is None:
                    _conn.execute(
                        text(
                            "ALTER TABLE catalog.oauth_providers "
                            "ADD COLUMN IF NOT EXISTS idp_entity_id VARCHAR(512), "
                            "ADD COLUMN IF NOT EXISTS idp_sso_url VARCHAR(512), "
                            "ADD COLUMN IF NOT EXISTS idp_certificate TEXT, "
                            "ADD COLUMN IF NOT EXISTS sp_entity_id VARCHAR(512)"
                        )
                    )
                    _conn.commit()
            _saml_bridge_engine.dispose()

        yield

    finally:
        if should_drop_db:
            # --- Teardown: drop the test database ---
            #
            # Ordering invariant (TI-01, Phase 1075):
            #   1. pg_terminate_backend() to all sessions on the test DB
            #   2. SHORT SLEEP — let libpq drain the killed connection state.
            #      pg_terminate_backend is asynchronous from libpq's POV: the
            #      SQL call returns true as soon as the backend receives
            #      SIGTERM, NOT after the connection is fully reaped from
            #      pg_stat_activity. Without this beat, a follow-up DROP can
            #      race the still-shutting-down session and surface as
            #      "database is being accessed by other users" or, in the
            #      next pytest run, an InvalidCatalogNameError when the
            #      stale connection is briefly visible.
            #   3. DROP DATABASE IF EXISTS
            teardown_engine = sqlalchemy.create_engine(
                settings.database_url_sync, isolation_level="AUTOCOMMIT"
            )
            try:
                with teardown_engine.connect() as conn:
                    # Terminate active connections before dropping
                    conn.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = :db_name AND pid <> pg_backend_pid()"
                        ),
                        {"db_name": db_name},
                    )
                    # 50ms is empirically sufficient for asyncpg-driven
                    # connection kills on a local PG instance; remote/CI
                    # deployments may need more, but the next run's
                    # `DROP DATABASE IF EXISTS` is idempotent so a stale
                    # connection only delays cleanup, never breaks it.
                    time.sleep(0.05)
                    conn.execute(
                        text(
                            f"DROP DATABASE IF EXISTS {_quote_database_identifier(db_name)}"
                        )
                    )
            finally:
                teardown_engine.dispose()
        settings.postgres_db_test = original_test_db_name


@pytest.fixture
async def client(tmp_path):
    """Create an async test client with a dedicated database engine.

    Overrides both the get_db dependency AND the database module's engine/session
    so that the lifespan seed functions and request handlers all use the same
    test engine. This prevents asyncpg pool state conflicts.
    """
    original_upload_staging_dir = settings.upload_staging_dir
    settings.upload_staging_dir = str(tmp_path / "staging")
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    original_tempdir = tempfile.tempdir
    from app.core.runtime.staging import redirect_tempfile_to_staging

    redirect_tempfile_to_staging(staging_dir)

    # Pool sizing is derived per pytest-xdist worker via _derive_test_pool_sizing().
    # The baseline connection budget is tight:
    #   max_connections=30 (db/postgresql.conf:11, PERF-05 / Phase 274)
    #   API+worker services: 8 persistent idle connections to the main DB
    #   Postgres background: 5 connections
    #   Available for test workers: 30 − 13 = 17 connections
    # Under -n auto (16 workers), any pool that holds idle connections will
    # consume the entire budget, leaving no room for setup-phase engines.
    # NullPool (xdist mode) avoids idle-connection overhead — connections are
    # opened only during active DB operations and closed immediately when released.
    # Sequential mode (worker_id=master) keeps the historical (5, 2) QueuePool
    # for request handlers that need concurrent DB conns within a single test.
    # See .planning/audits/PYTEST-XDIST-SPIKE-v1019.md for measured numbers + rationale.
    # Engine-creation logic is extracted to _make_test_async_engine() so the
    # NullPool-vs-QueuePool branch is directly testable (see test_conftest_pool_sizing.py).
    test_engine = _make_test_async_engine(settings.test_database_url)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    # Patch the database module so lifespan seed functions use our engine
    import app.core.db as db_module

    original_engine = db_module.engine
    original_session = db_module.async_session
    db_module.engine = test_engine
    db_module.async_session = test_session_factory

    # Patch health service module's engine reference
    import app.observability.health.service as health_service_module

    original_health_engine = health_service_module.engine
    health_service_module.engine = test_engine

    # Override the get_db dependency
    from app.core.dependencies import get_db
    from app.api.main import app

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # Initialize singleton cache provider for settings reads/writes in request paths.
    # Lifespan is not guaranteed in this ASGITransport test setup.
    init_cache()
    import app.platform.storage.provider as storage_provider_module
    from app.platform.storage.local import LocalStorageProvider

    original_storage = storage_provider_module._storage
    storage_provider_module._storage = LocalStorageProvider(base_dir=str(staging_dir))
    structlog.contextvars.bind_contextvars(service="api")

    # Disable rate limiter during tests
    from app.modules.auth.router import limiter

    limiter.enabled = False

    # Ensure roles and admin user exist before tests
    await _ensure_roles_and_admin(test_session_factory)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Cleanup
    app.dependency_overrides.clear()
    db_module.engine = original_engine
    db_module.async_session = original_session
    health_service_module.engine = original_health_engine
    storage_provider_module._storage = original_storage
    settings.upload_staging_dir = original_upload_staging_dir
    tempfile.tempdir = original_tempdir
    await test_engine.dispose()


async def _ensure_roles_and_admin(session_factory: async_sessionmaker) -> None:
    """Seed roles and ensure the admin user exists."""
    # Seed roles
    async with session_factory() as session:
        for role_data in [
            {"name": "admin", "description": "Full system access"},
            {"name": "editor", "description": "Can create and edit datasets"},
            {"name": "viewer", "description": "Read-only access to permitted datasets"},
        ]:
            result = await session.execute(
                select(Role).where(Role.name == role_data["name"])
            )
            if result.scalar_one_or_none() is None:
                session.add(Role(**role_data))
        await session.commit()

    # Ensure admin user exists
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one_or_none()

        if admin is None:
            admin_user = User(
                username=settings.geolens_admin_username,
                password_hash=hash_password(
                    settings.geolens_admin_password.get_secret_value()
                ),
                is_active=True,
            )
            session.add(admin_user)
            await session.flush()

            role_result = await session.execute(
                select(Role).where(Role.name == "admin")
            )
            admin_role = role_result.scalar_one()
            session.add(UserRole(user_id=admin_user.id, role_id=admin_role.id))
            await session.commit()
        elif not admin.is_active:
            # Re-activate admin if a previous test deactivated it
            admin.is_active = True
            # Reset password to known value
            admin.password_hash = hash_password(
                settings.geolens_admin_password.get_secret_value()
            )
            await session.commit()


async def get_auth_header(
    client: AsyncClient, username: str, password: str
) -> dict[str, str]:
    """Log in via POST /auth/login and return an Authorization header dict."""
    resp = await client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _create_test_user(
    client: AsyncClient,
    admin_headers: dict,
    role: str,
) -> tuple[dict[str, str], str]:
    """Create a test user with the given role and return (auth_header, user_id)."""
    unique = uuid.uuid4().hex[:8]
    username = f"{role}_{unique}"
    password = "TestPass1234!"  # SEC-S16: meets 12-char + 3-class policy
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": password, "role": role},
        headers=admin_headers,
    )
    assert resp.status_code == 201, f"Create {role} failed: {resp.text}"
    user_id = resp.json()["id"]
    headers = await get_auth_header(client, username, password)
    return headers, user_id


@pytest.fixture
async def admin_auth_header(client: AsyncClient) -> dict[str, str]:
    """Return auth headers for the seeded admin user."""
    return await get_auth_header(
        client,
        settings.geolens_admin_username,
        settings.geolens_admin_password.get_secret_value(),
    )


@pytest.fixture
async def editor_auth_header(
    client: AsyncClient, admin_auth_header: dict
) -> dict[str, str]:
    """Create an editor user and return their auth headers."""
    headers, _ = await _create_test_user(client, admin_auth_header, "editor")
    return headers


@pytest.fixture
async def viewer_auth_header(
    client: AsyncClient, admin_auth_header: dict
) -> dict[str, str]:
    """Create a viewer user and return their auth headers."""
    headers, _ = await _create_test_user(client, admin_auth_header, "viewer")
    return headers


@pytest.fixture
async def test_db_session(client: AsyncClient):
    """Yield an async session from the test engine for direct DB operations.

    Uses the same session factory that the client fixture patches into the app,
    so records inserted here are visible to request handlers.
    """
    import app.core.db as db_module

    async with db_module.async_session() as session:
        yield session


# ---------------------------------------------------------------------------
# Isolation note (tech debt)
# ---------------------------------------------------------------------------
#
# The current fixture model creates a single test database per pytest-xdist
# WORKER per session and shares it across all tests on that worker. Isolation
# is enforced by:
#   1. Unique names (uuid4 suffixes + worker_id) in test data factories
#   2. Per-test cleanup via explicit DELETE / DROP TABLE in test teardown
#   3. Session-scoped roles and admin seeded once via _ensure_roles_and_admin
#
# A transaction-rollback-per-test model would be safer but is incompatible
# with the way request handlers call ``await session.commit()`` under the
# HTTP test client. Moving to per-test rollback requires either:
#   (a) Wrapping every request in a SAVEPOINT and intercepting handler commits
#       via a custom AsyncSession subclass, or
#   (b) TRUNCATE CASCADE on all user-level tables between tests.
#
# Both are large changes deferred to a dedicated PR. The opt-in ``clean_tables``
# fixture below is provided for tests that need extra determinism today.
#
# Concurrent pytest sessions AND parallel pytest-xdist workers are isolated by
# suffixing the configured ``POSTGRES_DB_TEST`` base name with the worker_id
# (``"master"`` when xdist is inactive, ``"gw0"`` / ``"gw1"`` / ... under
# ``-n auto``) plus an 8-char uuid hex. Each run drops only its own physical
# database during teardown, so background runs, interactive runs, and parallel
# xdist workers can target the same Postgres server without cross-contamination
# (TI-01, Phase 1075).


@pytest.fixture(autouse=True)
def _point_ogr2ogr_at_test_db(request, monkeypatch):
    """Redirect ``ogr2ogr``'s PG connection string to the test database.

    ``app.ingest.ogr.build_pg_conn_str()`` defaults to the dev/prod
    settings. Any test that invokes ``run_ogr2ogr`` /
    ``run_ogr2ogr_service`` without this redirect would write to the
    wrong database and collide with non-test data. The original fixture
    lived locally in ``test_ingest_column_preservation.py`` (K2-PRE) —
    lifting it to ``conftest.py`` behind the ``requires_ogr2ogr`` marker
    means any future test that opts in automatically inherits the
    safety redirect.

    Opt-in: only tests marked with ``@pytest.mark.requires_ogr2ogr``
    (or a class-level ``pytestmark``) trigger the monkeypatch. All
    other tests are unaffected.
    """
    if "requires_ogr2ogr" not in request.keywords:
        return

    from app.core.config import settings as _settings
    from app.processing.ingest import ogr as _ogr

    def _test_pg_conn_str() -> str:
        return (
            f"PG:host={_settings.postgres_host} "
            f"port={_settings.postgres_port} "
            f"dbname={_settings.postgres_db_test} "
            f"user={_settings.postgres_user} "
            f"password={_settings.postgres_password.get_secret_value()}"
        )

    monkeypatch.setattr(_ogr, "build_pg_conn_str", _test_pg_conn_str)


@pytest.fixture
def stac_visibility_force_5xx(monkeypatch):
    """SEC-FU-01: Force apply_visibility_filter to raise RuntimeError on every call.

    Monkeypatches ``app.modules.catalog.authorization.apply_visibility_filter``
    so that STAC item-read and search endpoints exercise the 5xx error path
    without requiring the database to fail.  Yields a ``SimpleNamespace(active=True)``
    handle so tests can assert the patch is in effect.

    Scoped to function level (default); ``monkeypatch`` auto-unwinds at teardown,
    so no production code path is affected outside the requesting test.

    Usage::

        def test_no_leak(client, stac_visibility_force_5xx):
            assert stac_visibility_force_5xx.active
            resp = client.get("/stac/items/...")
            assert resp.status_code >= 500

    Pattern mirrors ``monkeypatch.setattr(_ogr, "build_pg_conn_str", ...)`` above.
    """
    import types as _types
    import app.modules.catalog.authorization as _authorization
    import app.standards.stac.router as _stac_router

    def _force_raise(stmt, user, user_roles, record_cls, grant_cls=None):
        raise RuntimeError("forced 5xx for SEC-FU-01 regression test")

    # Patch the canonical module so direct imports from authorization also see the stub.
    monkeypatch.setattr(_authorization, "apply_visibility_filter", _force_raise)
    # Also patch the name already bound in the STAC router module's namespace,
    # because ``from app.modules.catalog.authorization import apply_visibility_filter``
    # creates a separate binding that a pure module-level patch would not reach.
    monkeypatch.setattr(_stac_router, "apply_visibility_filter", _force_raise)

    yield _types.SimpleNamespace(active=True)


@pytest.fixture
def saml_overlay_registered():
    """Programmatically register EnterpriseSamlExtension into the live extension
    registry for the duration of a single test. Restores prior state on
    teardown so other tests that expect community edition still see their
    default.

    The ``geolens_enterprise`` import is deferred (inside the fixture body)
    so test collection does not require the enterprise package to be
    installed -- collection still succeeds in community-only environments;
    tests that request this fixture are skipped when the overlay is absent.
    """
    from app.platform.extensions import _extensions, _routers

    saved_ext = dict(_extensions)
    saved_routers = list(_routers)
    try:
        # Deferred import so collection does not require the enterprise package
        saml_module = pytest.importorskip(
            "geolens_enterprise.auth.saml",
            reason="geolens_enterprise package is not installed",
        )
        saml_router_module = pytest.importorskip(
            "geolens_enterprise.auth.saml.router",
            reason="geolens_enterprise package is not installed",
        )

        ext = saml_module.EnterpriseSamlExtension()
        _extensions["auth"] = ext
        _extensions["identity"] = ext
        _routers.append(saml_router_module.router)
        yield ext
    finally:
        _extensions.clear()
        _extensions.update(saved_ext)
        _routers.clear()
        _routers.extend(saved_routers)


@pytest.fixture
async def clean_tables(test_db_session):
    """Opt-in fixture: truncate user-level tables after the test.

    Use this fixture in tests that need the test database reset to a known
    state afterwards (e.g., tests that assert on list sizes or cross-cutting
    counts). It runs TRUNCATE CASCADE on mutable tables in the ``catalog``
    and ``data`` schemas, leaving roles/admin seeded by the session fixture
    intact.

    Example::

        async def test_list_all_datasets(client, admin_auth_header, clean_tables):
            ...  # after this test, tables are truncated
    """
    yield

    # Truncate mutable catalog tables in dependency order (CASCADE handles FKs)
    tables_to_truncate = [
        "catalog.datasets",
        "catalog.records",
        "catalog.collections",
        "catalog.maps",
        "catalog.map_share_tokens",
        "catalog.api_keys",
    ]
    try:
        for table in tables_to_truncate:
            await test_db_session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
        await test_db_session.commit()
    except Exception:
        # Best-effort cleanup; don't mask test failures
        await test_db_session.rollback()
