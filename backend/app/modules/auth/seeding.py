"""Boot-time seeding of the default roles and the first admin account."""

import structlog
from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.tenancy import is_multi_tenant
from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.providers.local import hash_password_async

logger = structlog.stdlib.get_logger(__name__)

# Advisory-lock key for boot-time seeding (pg_advisory_xact_lock); serializes
# seed_roles + seed_initial_admin so concurrent uvicorn workers don't race the
# SELECT-then-INSERT on a fresh DB. Any constant works; must be unique.
_SEED_LOCK_KEY = 0x6C656E73  # "lens"

DEFAULT_ROLES = [
    {"name": "admin", "description": "Full system access"},
    {"name": "editor", "description": "Can create and edit datasets"},
    {"name": "viewer", "description": "Read-only access to permitted datasets"},
]


async def seed_roles() -> None:
    """Ensure default roles exist in the database (defensive safety net).

    Concurrency-safe via _SEED_LOCK_KEY: without it, concurrent uvicorn
    workers on a fresh DB would race SELECT-then-INSERT on roles.name.
    """
    from app.core.db import async_session  # late-bind for tests

    async with async_session() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SEED_LOCK_KEY}
        )
        for role_data in DEFAULT_ROLES:
            result = await session.execute(
                # Select the scalar id, not the Role entity: Role.users
                # select-in loading would issue an unscoped catalog.users
                # query, which fails closed under FORCE RLS with no tenant.
                select(Role.id).where(Role.name == role_data["name"])
            )
            if result.scalar_one_or_none() is None:
                session.add(Role(**role_data))
                logger.info("Seeded role: %s", role_data["name"])
        await session.commit()


async def seed_initial_admin() -> None:
    """Create an initial admin user if none exist.

    Uses GEOLENS_ADMIN_USERNAME/_PASSWORD from settings. Concurrency-safe via
    the xact-scoped advisory lock: without it, concurrent uvicorn workers on
    a fresh DB would race the INSERT and the loser's UniqueViolationError
    would leave admin login 401 on every fresh install.
    """
    from app.core.db import async_session  # late-bind for tests

    async with async_session() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SEED_LOCK_KEY}
        )
        result = await session.execute(select(func.count()).select_from(User))
        user_count = result.scalar() or 0

        if user_count == 0:
            admin_user = User(
                username=settings.geolens_admin_username,
                password_hash=await hash_password_async(
                    settings.geolens_admin_password.get_secret_value()
                ),
                is_active=True,
            )
            session.add(admin_user)
            await session.flush()

            role_result = await session.execute(
                select(Role.id).where(Role.name == "admin")
            )
            admin_role_id = role_result.scalar_one()
            session.add(UserRole(user_id=admin_user.id, role_id=admin_role_id))

            await session.commit()
            logger.info(
                "Initial admin user created: %s", settings.geolens_admin_username
            )


async def seed_bootstrap_identity() -> None:
    """Seed global RBAC roles and, for single-tenant installs only, an admin.

    Multi-tenant admins are created via the Cloud signup transaction after
    tenant provisioning; a global NULL-tenant user is rejected by FORCE RLS.
    """
    await seed_roles()
    if is_multi_tenant():
        logger.info("Skipping global initial-admin seed in multi-tenant mode")
        return
    await seed_initial_admin()
