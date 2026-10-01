"""Password hashing and verification leave the event loop free.

bcrypt is CPU-bound and takes a sizeable fraction of a second per call. These
tests gate the hasher on an event that only a coroutine on the event loop can
set. On a worker thread the call is released almost at once; on the loop
thread nothing else can run, so the gate times out and records that the loop
never got a turn.
"""

from __future__ import annotations

import ast
import asyncio
import threading
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.persistent_config import REGISTRATION_ENABLED
from app.modules.auth.providers import local

from .conftest import _create_test_user

pytestmark = pytest.mark.anyio

_T = TypeVar("_T")
_GATE_TIMEOUT_SECONDS = 5
# tests/factories.py creates every test user with this password.
_FACTORY_PASSWORD = "TestPass1234!"
_NEW_PASSWORD = "Another-Strong-Pass-42"


class _LoopGate:
    def __init__(self) -> None:
        self._pending: list[threading.Event] = []
        self.released_by_loop: list[bool] = []

    def wrap(self, fn: Callable[..., _T]) -> Callable[..., _T]:
        def gated(*args: Any, **kwargs: Any) -> _T:
            event = threading.Event()
            self._pending.append(event)
            self.released_by_loop.append(event.wait(timeout=_GATE_TIMEOUT_SECONDS))
            return fn(*args, **kwargs)

        return gated

    async def run(self, awaitable: Awaitable[_T]) -> _T:
        task = asyncio.ensure_future(awaitable)
        while not task.done():
            while self._pending:
                self._pending.pop().set()
            await asyncio.sleep(0.001)
        return task.result()


@pytest.fixture
def gate_hasher(monkeypatch):
    """Return a function that gates hash and verify from the moment it is called,
    so fixtures and setup requests hash at full speed."""

    def install() -> _LoopGate:
        gate = _LoopGate()
        for name in ("hash", "verify"):
            original = getattr(local.password_hash, name)
            monkeypatch.setattr(local.password_hash, name, gate.wrap(original))
        return gate

    return install


async def test_login_with_an_unknown_username_leaves_the_loop_free(
    client: AsyncClient, gate_hasher
):
    gate = gate_hasher()

    resp = await gate.run(
        client.post(
            "/auth/login",
            data={"username": f"nobody_{uuid.uuid4().hex}", "password": "guess"},
        )
    )

    assert resp.status_code == 401, resp.text
    assert gate.released_by_loop == [True]


async def test_login_with_a_valid_password_leaves_the_loop_free(
    client: AsyncClient, gate_hasher
):
    gate = gate_hasher()

    resp = await gate.run(
        client.post(
            "/auth/login",
            data={
                "username": settings.geolens_admin_username,
                "password": settings.geolens_admin_password.get_secret_value(),
            },
        )
    )

    assert resp.status_code == 200, resp.text
    assert gate.released_by_loop == [True]


async def test_change_password_leaves_the_loop_free(
    client: AsyncClient, admin_auth_header: dict, gate_hasher
):
    headers, _ = await _create_test_user(client, admin_auth_header, "viewer")
    gate = gate_hasher()

    resp = await gate.run(
        client.post(
            "/auth/change-password/",
            json={
                "current_password": _FACTORY_PASSWORD,
                "new_password": _NEW_PASSWORD,
            },
            headers=headers,
        )
    )

    assert resp.status_code == 204, resp.text
    assert gate.released_by_loop == [True, True]


async def test_registration_leaves_the_loop_free(
    client: AsyncClient, gate_hasher, monkeypatch
):
    monkeypatch.setattr(REGISTRATION_ENABLED, "get", AsyncMock(return_value=True))
    gate = gate_hasher()

    resp = await gate.run(
        client.post(
            "/auth/register/",
            json={
                "username": f"signup_{uuid.uuid4().hex[:8]}",
                "password": _NEW_PASSWORD,
            },
        )
    )

    assert resp.status_code == 201, resp.text
    assert gate.released_by_loop == [True]


async def test_admin_user_creation_leaves_the_loop_free(
    client: AsyncClient, admin_auth_header: dict, gate_hasher
):
    gate = gate_hasher()

    resp = await gate.run(
        client.post(
            "/admin/users/",
            json={
                "username": f"created_{uuid.uuid4().hex[:8]}",
                "password": _NEW_PASSWORD,
                "role": "viewer",
            },
            headers=admin_auth_header,
        )
    )

    assert resp.status_code == 201, resp.text
    assert gate.released_by_loop == [True]


async def test_admin_password_reset_leaves_the_loop_free(
    client: AsyncClient, admin_auth_header: dict, gate_hasher
):
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")
    gate = gate_hasher()

    resp = await gate.run(
        client.post(
            f"/admin/users/{user_id}/reset-password/",
            json={"password": _NEW_PASSWORD},
            headers=admin_auth_header,
        )
    )

    assert resp.status_code == 200, resp.text
    assert gate.released_by_loop == [True]


def test_no_coroutine_calls_the_blocking_password_primitives():
    """Covers the callers the request tests above do not drive, such as the
    startup admin seed and identity-provider account conversion."""
    app_root = Path(__file__).resolve().parents[1] / "app"
    blocking = {"hash_password", "verify_password"}
    offenders = []
    for path in sorted(app_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for func in ast.walk(tree):
            if not isinstance(func, ast.AsyncFunctionDef):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                callee = node.func
                name = getattr(callee, "id", None) or getattr(callee, "attr", None)
                if name in blocking:
                    offenders.append(f"{path.relative_to(app_root)}:{node.lineno}")

    assert offenders == []
