"""Enable/force tenant RLS using the deployment's privileged migrator role."""

import asyncio

from app.core.db.rls import apply_tenancy_rls_from_engine


async def main() -> None:
    """Prepare RLS flags; runtime-role safety is checked by API/worker boot."""
    await apply_tenancy_rls_from_engine(verify_runtime_role=False)


if __name__ == "__main__":
    asyncio.run(main())
