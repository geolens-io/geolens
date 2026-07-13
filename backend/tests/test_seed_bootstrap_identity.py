from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_multi_tenant_seeds_roles_but_never_global_admin(monkeypatch):
    from app.api import main

    seed_roles = AsyncMock()
    seed_admin = AsyncMock()
    monkeypatch.setattr(main, "seed_roles", seed_roles)
    monkeypatch.setattr(main, "seed_initial_admin", seed_admin)
    monkeypatch.setattr(main, "is_multi_tenant", lambda: True)

    await main.seed_bootstrap_identity()

    seed_roles.assert_awaited_once_with()
    seed_admin.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_tenant_preserves_role_then_admin_seed(monkeypatch):
    from app.api import main

    calls: list[str] = []

    async def seed_roles() -> None:
        calls.append("roles")

    async def seed_admin() -> None:
        calls.append("admin")

    monkeypatch.setattr(main, "seed_roles", seed_roles)
    monkeypatch.setattr(main, "seed_initial_admin", seed_admin)
    monkeypatch.setattr(main, "is_multi_tenant", lambda: False)

    await main.seed_bootstrap_identity()

    assert calls == ["roles", "admin"]
