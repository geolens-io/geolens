#!/usr/bin/env python3
"""Print a single-use link that remembers one browser for one account.

When an account has refused password sign-in from unknown clients after
repeated failures, a browser that opens this link is treated as one the
account has signed in with before. It still needs the password. The link
works once, within 10 minutes.

Usage:
    docker compose exec api /app/.venv/bin/python -m scripts.trust_login_device <username>

In multi-tenant mode add ``--tenant <tenant id>`` and open the link on that
tenant's own address.

Exits 1 when no account has that username, and 2 on a usage error.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import text

_TENANT_EXISTS = text("SELECT id FROM catalog.tenants WHERE id = :tenant_id")
_TRUST_PATH = "/auth/device-trust"
# The API's mount point when no public URL is configured.
_DEFAULT_API_PATH = "/api"


async def _registered_tenant(db_module, tenant: str) -> str | None:
    """The canonical id of ``tenant`` if the tenant registry, which has no RLS, holds it."""
    try:
        tenant_id = uuid.UUID(tenant)
    except ValueError:
        return None
    async with db_module.async_session() as db:
        if await db.scalar(_TENANT_EXISTS, {"tenant_id": tenant_id}) is None:
            return None
    return str(tenant_id)


async def _api_base(db, tenant: str | None) -> str:
    """The configured public API URL, or the bare mount path.

    A tenant's device cookie only works on that tenant's own host, which the
    fleet-wide URL is not, so a tenant's link is always the bare path.
    """
    from app.core.public_urls import PublicUrlNotConfiguredError, get_public_api_url

    if tenant is not None:
        return _DEFAULT_API_PATH
    try:
        return await get_public_api_url(db, for_external_use=True)
    except PublicUrlNotConfiguredError:
        return _DEFAULT_API_PATH


async def _run(username: str, tenant: str | None) -> int:
    import app.core.db as db_module
    from app.core.db.tenant_session import tenant_job_context
    from app.core.tenancy import is_multi_tenant
    from app.modules.auth.login_throttle import create_trust_token

    if is_multi_tenant() != (tenant is not None):
        print(
            "Pass --tenant in multi-tenant mode, and only there: each tenant's "
            "accounts are separate.",
            file=sys.stderr,
        )
        return 2
    if tenant is not None:
        registered = await _registered_tenant(db_module, tenant)
        if registered is None:
            print(f"Unknown tenant: {tenant}", file=sys.stderr)
            return 2
        tenant = registered
    with tenant_job_context(tenant):
        async with db_module.async_session() as db:
            token = await create_trust_token(db, username)
            if token is None:
                print(f"No account has the username {username!r}.", file=sys.stderr)
                return 1
            base = await _api_base(db, tenant)
            await db.commit()
    print(f"{base}{_TRUST_PATH}?token={token}")
    if tenant is not None:
        print("Put the tenant's own address in front of the path.", file=sys.stderr)
    elif base.startswith("/"):
        print(
            "No public URL is configured: put this GeoLens's address in front of "
            "the path.",
            file=sys.stderr,
        )
    print(
        "Open this link in the browser to remember, within 10 minutes. It works "
        "once and only lets that browser try the account's password.",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print a single-use link that remembers a browser for one account."
    )
    parser.add_argument("username", help="The account's username.")
    parser.add_argument(
        "--tenant", help="The account's tenant; required in multi-tenant mode."
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.username, args.tenant))


if __name__ == "__main__":
    raise SystemExit(main())
