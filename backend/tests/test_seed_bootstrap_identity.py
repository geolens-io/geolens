import uuid
from unittest.mock import AsyncMock

import pytest


class _ExistingRoleResult:
    def scalar_one_or_none(self):
        return uuid.uuid4()


class _RecordingSeedSession:
    def __init__(self) -> None:
        self.statements = []

    async def execute(self, statement, _parameters=None):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return object()  # pg_advisory_xact_lock result is not consumed
        return _ExistingRoleResult()

    def add(self, _value) -> None:
        raise AssertionError("default roles should already exist in this regression")

    async def commit(self) -> None:
        return None


class _SeedSessionContext:
    def __init__(self, session: _RecordingSeedSession) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return None


@pytest.mark.asyncio
async def test_seed_roles_selects_scalars_without_loading_unscoped_users(monkeypatch):
    """Hosted boot must not trigger Role.users select-in loading before tenancy."""
    from app.api import main
    from app.modules.auth.models import Role

    session = _RecordingSeedSession()
    monkeypatch.setattr(
        main,
        "async_session",
        lambda: _SeedSessionContext(session),
    )

    await main.seed_roles()

    role_selects = session.statements[1:]
    assert len(role_selects) == len(main.DEFAULT_ROLES)
    for statement in role_selects:
        descriptions = statement.column_descriptions
        assert len(descriptions) == 1
        assert descriptions[0]["expr"] is Role.id


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
