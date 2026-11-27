"""Dedicated asyncpg connection pool for tile queries.

Separate from the SQLAlchemy engine pool to prevent tile traffic
from starving API CRUD operations.
"""

import asyncpg
import structlog
from sqlalchemy.engine.url import make_url

from app.core.config import settings

logger = structlog.stdlib.get_logger(__name__)

_tile_pool: asyncpg.Pool | None = None

# Bounds one command. A tile request issues several on the connection it holds,
# so this is not a bound on how long any holder keeps one.
TILE_POOL_COMMAND_TIMEOUT_SECONDS = 10

# Chosen rather than derived, since nothing the pool declares bounds queue
# depth. Paired with the handler's `Retry-After: 2` so a shed caller retries
# inside a map viewer's patience. Also bounds asyncpg's connection release.
TILE_POOL_ACQUIRE_TIMEOUT_SECONDS = 3.0


def _validate_tile_database_isolation() -> None:
    """Require a distinct tile login whenever tenant isolation is active."""
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        return
    if not settings.tile_database_url_override:
        raise RuntimeError(
            "TILE_DATABASE_URL_OVERRIDE is required in multi-tenant mode; "
            "the tile pool must not reuse the API/worker login"
        )

    tile_url = make_url(settings.tile_database_url)
    runtime_url = make_url(settings.database_url)
    if tile_url.username == runtime_url.username:
        raise RuntimeError(
            "TILE_DATABASE_URL_OVERRIDE must use a dedicated Postgres login "
            "different from DATABASE_URL_OVERRIDE"
        )


def _parse_dsn() -> str:
    """Convert SQLAlchemy-style URL to asyncpg-compatible DSN.

    Uses ``sqlalchemy.engine.url.make_url`` so query parameters and special
    characters in passwords are preserved.

    Raises ``ValueError`` if ``settings.tile_database_url`` is unset, rather
    than an obscure AttributeError downstream.
    """
    raw = settings.tile_database_url
    if not raw:
        raise ValueError(
            "settings.tile_database_url is not configured; cannot init tile pool"
        )
    url = make_url(raw)
    # asyncpg expects the bare 'postgresql' scheme.
    url = url.set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def _get_ssl_arg():
    ssl_val = settings.database_connect_args.get("ssl")
    # asyncpg doesn't accept the string "prefer" -- pass None to let it negotiate
    if ssl_val == "prefer":
        return None
    return ssl_val


async def _assert_multi_tenant_tile_role(conn: asyncpg.Connection) -> None:
    """Verify the live tile login is a reader-only SET gateway consumer."""
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        return

    row = await conn.fetchrow(
        """
        SELECT
            session_user AS login_name,
            current_user AS effective_name,
            login_role.rolsuper OR effective_role.rolsuper AS is_superuser,
            login_role.rolbypassrls OR effective_role.rolbypassrls AS bypasses_rls,
            login_role.rolcreaterole OR effective_role.rolcreaterole AS creates_roles,
            login_role.rolcreatedb OR effective_role.rolcreatedb AS creates_databases,
            login_role.rolreplication OR effective_role.rolreplication AS replicates,
            EXISTS (
                SELECT 1
                FROM pg_roles powerful_role
                WHERE (
                    powerful_role.rolsuper
                    OR powerful_role.rolbypassrls
                    OR powerful_role.rolcreaterole
                    OR powerful_role.rolcreatedb
                    OR powerful_role.rolreplication
                )
                  AND pg_has_role(session_user, powerful_role.oid, 'MEMBER')
            ) AS can_assume_powerful_role,
            EXISTS (
                SELECT 1
                FROM pg_roles forbidden_role
                WHERE (
                    forbidden_role.rolname IN (
                        'geolens_tenant_provisioner',
                        'geolens_tenant_control',
                        'geolens_tenant_writer',
                        'geolens_tenant_sandbox',
                        'geolens_reader'
                    )
                    OR forbidden_role.rolname ~ '^geolens_writer_t_[0-9a-f_]+'
                )
                  AND pg_has_role(session_user, forbidden_role.oid, 'MEMBER')
            ) AS has_forbidden_membership,
            EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class protected_relation
                JOIN pg_catalog.pg_namespace protected_namespace
                  ON protected_namespace.oid = protected_relation.relnamespace
                WHERE protected_namespace.nspname = 'catalog'
                  AND protected_relation.relname = ANY(
                      ARRAY[
                          'users', 'records', 'datasets', 'maps',
                          'collections', 'embed_tokens'
                      ]
                  )
                  AND protected_relation.relkind IN ('r', 'p')
                  AND pg_catalog.pg_has_role(
                      session_user,
                      protected_relation.relowner,
                      'MEMBER'
                  )
            ) AS can_assume_catalog_table_owner,
            EXISTS (
                SELECT 1
                FROM pg_catalog.pg_namespace tenant_namespace
                WHERE tenant_namespace.nspname ~
                    '^data_t_[0-9a-f]{8}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{12}$'
                  AND pg_catalog.pg_has_role(
                      session_user,
                      tenant_namespace.nspowner,
                      'MEMBER'
                  )
            ) AS can_assume_tenant_schema_owner,
            pg_catalog.has_schema_privilege(
                session_user, 'catalog', 'CREATE'
            ) OR pg_catalog.has_schema_privilege(
                session_user, 'public', 'CREATE'
            ) AS can_create_in_protected_schema,
            EXISTS (
                SELECT 1 FROM pg_roles tile_gateway
                WHERE tile_gateway.rolname = 'geolens_tile_gateway'
                  AND pg_has_role(session_user, tile_gateway.oid, 'MEMBER')
            ) AS has_tile_gateway
        FROM pg_roles login_role
        JOIN pg_roles effective_role ON effective_role.rolname = current_user
        WHERE login_role.rolname = session_user
        """
    )
    if row is None:
        raise RuntimeError("Tile database role verification returned no role")

    unsafe = any(
        bool(row[field])
        for field in (
            "is_superuser",
            "bypasses_rls",
            "creates_roles",
            "creates_databases",
            "replicates",
            "can_assume_powerful_role",
            "has_forbidden_membership",
            "can_assume_catalog_table_owner",
            "can_assume_tenant_schema_owner",
            "can_create_in_protected_schema",
        )
    )
    if unsafe or not row["has_tile_gateway"]:
        raise RuntimeError(
            "TILE_DATABASE_URL_OVERRIDE must resolve to a least-privilege "
            "LOGIN whose only GeoLens data path is geolens_tile_gateway; "
            "SUPERUSER/BYPASSRLS/CREATEROLE/CREATEDB/REPLICATION and "
            "control/writer/sandbox memberships, protected-object ownership, "
            "and CREATE on catalog/public are forbidden "
            f"(session_user={row['login_name']!r}, "
            f"current_user={row['effective_name']!r})"
        )


async def _init_tile_connection(conn: asyncpg.Connection) -> None:
    """Validate every newly opened physical tile connection."""
    await _assert_multi_tenant_tile_role(conn)


async def _set_local_reader_role(conn: asyncpg.Connection) -> None:
    # One round trip on success; the savepoint keeps a refused SET LOCAL from
    # aborting the tile transaction.
    try:
        await conn.execute(
            "SAVEPOINT tile_reader_role; "
            "SET LOCAL ROLE geolens_reader; "
            "RELEASE SAVEPOINT tile_reader_role"
        )
    except asyncpg.PostgresError as exc:
        await conn.execute("ROLLBACK TO SAVEPOINT tile_reader_role")
        logger.warning(
            "Tile request could not SET LOCAL ROLE geolens_reader; "
            "running as the pool login",
            error=str(exc),
        )


async def init_tile_pool() -> asyncpg.Pool:
    """Create the dedicated tile connection pool."""
    global _tile_pool

    _validate_tile_database_isolation()
    dsn = _parse_dsn()
    ssl = _get_ssl_arg()

    kwargs: dict = {
        "dsn": dsn,
        "min_size": settings.tile_pool_min_size,
        "max_size": settings.tile_pool_max_size,
        "command_timeout": TILE_POOL_COMMAND_TIMEOUT_SECONDS,
        "init": _init_tile_connection,
    }

    if ssl is not None:
        kwargs["ssl"] = ssl

    # An external pooler can't share prepared statements across connections.
    if settings.db_use_external_pooler:
        kwargs["statement_cache_size"] = 0

    _tile_pool = await asyncpg.create_pool(**kwargs)
    logger.info(
        "Tile connection pool initialized",
        min_size=settings.tile_pool_min_size,
        max_size=settings.tile_pool_max_size,
    )
    return _tile_pool


async def close_tile_pool() -> None:
    """Close the tile connection pool."""
    global _tile_pool
    if _tile_pool:
        await _tile_pool.close()
        _tile_pool = None
        logger.info("Tile connection pool closed")


def get_tile_pool() -> asyncpg.Pool:
    """Return the tile connection pool. Raises RuntimeError if not initialized."""
    if _tile_pool is None:
        raise RuntimeError("Tile pool not initialized. Call init_tile_pool() first.")
    return _tile_pool


async def set_tenant_role_for_tile_request(
    conn: asyncpg.Connection, tenant_id: str | None
) -> None:
    """Bind the tile request's read-only role inside its transaction.

    Must be called after the request transaction begins. Every binding is
    ``SET LOCAL``, so it ends with that transaction and never outlives it on
    the server connection, which a transaction-mode pooler may hand to an API
    or worker client next.

    single_tenant: ``SET LOCAL ROLE geolens_reader``. ``scripts/init-db.sh``
    creates that role with SELECT on the ``data`` schema only, so tile SQL
    can't write or read the catalog. Where the role is missing or the login
    can't assume it, the bind is rolled back to a savepoint, a warning is
    logged and the tile runs as the pool login.

    multi_tenant with a tenant: issues
        SET LOCAL ROLE geolens_reader_t_{tid}
        SET LOCAL search_path = data_t_{tid}, public, pg_catalog
    and fails the request if either fails. The explicit schema
    qualification in the query (``tenant_data_schema(tid).table``) is the
    primary isolation control; search_path is defense-in-depth.

    multi_tenant with ``tenant_id`` None: no-op.
    """
    from app.core.db.tenant_schema import tenant_data_schema, tenant_reader_role
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        await _set_local_reader_role(conn)
        return
    if tenant_id is None:
        return

    role = tenant_reader_role(tenant_id)
    schema = tenant_data_schema(tenant_id)
    try:
        await conn.execute(f"SET LOCAL ROLE {role}")
        await conn.execute(f"SET LOCAL search_path = {schema}, public, pg_catalog")
    except asyncpg.PostgresError as exc:
        # A failed role/search_path bind must fail the request rather than
        # continue under the pool's session role, which would bypass both
        # per-tenant isolation layers.
        raise RuntimeError(
            f"Tile pool: SET LOCAL ROLE {role!r} failed — "
            "cannot serve tile without per-tenant role binding"
        ) from exc
