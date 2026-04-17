import uuid

import pytest
import sqlalchemy
import structlog
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.providers.local import hash_password
from app.platform.cache import init_cache
from app.core.config import settings

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


@pytest.fixture(autouse=True, scope="session")
def _test_db_lifecycle():
    """Create, migrate, and tear down the test database once per session.

    Uses sync SQLAlchemy because CREATE/DROP DATABASE require AUTOCOMMIT
    isolation which is simpler with the synchronous driver.

    Gracefully skips DB setup when database host is unreachable (e.g. pure
    unit test runs outside Docker). Tests that require DB will fail with a
    clear connection error; DB-independent tests will run normally.
    """
    db_name = settings.postgres_db_test

    # --- Setup: create test database ---
    dev_engine = sqlalchemy.create_engine(
        settings.database_url_sync, isolation_level="AUTOCOMMIT"
    )
    try:
        with dev_engine.connect() as conn:
            # Drop if exists for a clean slate
            conn.execute(text(f"DROP DATABASE IF EXISTS {db_name}"))
            conn.execute(text(f"CREATE DATABASE {db_name}"))
        dev_engine.dispose()
    except Exception:
        # DB host unreachable — skip full setup; unit tests unaffected
        dev_engine.dispose()
        yield
        return

    # --- Init: extensions, schemas, roles ---
    test_engine_sync = sqlalchemy.create_engine(settings.test_database_url_sync)
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
    test_engine_sync.dispose()

    # --- Migrate: run alembic against the test database ---
    from alembic import command
    from alembic.config import Config as AlembicConfig

    alembic_cfg = AlembicConfig("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    command.upgrade(alembic_cfg, "head")

    yield

    # --- Teardown: drop the test database ---
    teardown_engine = sqlalchemy.create_engine(
        settings.database_url_sync, isolation_level="AUTOCOMMIT"
    )
    with teardown_engine.connect() as conn:
        # Terminate active connections before dropping
        conn.execute(
            text(
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid()"
            )
        )
        conn.execute(text(f"DROP DATABASE IF EXISTS {db_name}"))
    teardown_engine.dispose()


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

    test_engine = create_async_engine(
        settings.test_database_url,
        pool_size=5,
        max_overflow=2,
        pool_timeout=30,
        echo=False,
    )
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
    from app.main import app

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
        "/auth/login/",
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
    password = "testpass123"
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
# The current fixture model creates a single test database per pytest session
# and shares it across all tests. Isolation is enforced by:
#   1. Unique names (uuid4 suffixes) in test data factories
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
    from app.ingest import ogr as _ogr

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
