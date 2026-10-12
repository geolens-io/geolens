"""Failed sign-ins are throttled per username; successful ones never count."""

import asyncio
import uuid

import pytest
from httpx import AsyncClient, Response
from limits import RateLimitItemPerMinute
from sqlalchemy import func, select

from app.modules.auth import router as auth_router
from app.platform.ratelimit import FailureThrottle, limiter

PASSWORD = "TestPass1234!"


@pytest.fixture
def throttle(monkeypatch: pytest.MonkeyPatch):
    """A two-failure budget on a live limiter, with the per-address cap out of the way."""
    budget = FailureThrottle(
        f"login-failures-{uuid.uuid4().hex}", RateLimitItemPerMinute(2, 15)
    )
    monkeypatch.setattr(auth_router, "_LOGIN_FAILURES", budget)
    monkeypatch.setattr(auth_router, "get_cached_login_rate_limit", lambda: 1000)
    original = limiter.enabled
    limiter.enabled = True
    try:
        yield budget
    finally:
        limiter.enabled = original
        limiter._storage.reset()


async def _username(client: AsyncClient, admin_auth_header: dict) -> str:
    username = f"limited_{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": PASSWORD, "role": "viewer"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    return username


async def _login(client: AsyncClient, username: str, password: str) -> Response:
    return await client.post(
        "/auth/login", data={"username": username, "password": password}
    )


@pytest.mark.anyio
async def test_failures_lock_the_username_and_successes_do_not(
    client: AsyncClient, admin_auth_header: dict, throttle
):
    """Two failures refuse the username, whatever its case, until the window ends."""
    username = await _username(client, admin_auth_header)
    bystander = await _username(client, admin_auth_header)

    for _ in range(3):
        assert (await _login(client, username, PASSWORD)).status_code == 200

    for _ in range(2):
        assert (await _login(client, username, "wrong-password")).status_code == 401

    refused = await _login(client, username, PASSWORD)
    assert refused.status_code == 429, refused.text
    assert 0 < int(refused.headers["Retry-After"]) <= 15 * 60
    assert (await _login(client, username.upper(), PASSWORD)).status_code == 429

    assert (await _login(client, bystander, PASSWORD)).status_code == 200


@pytest.mark.anyio
async def test_spellings_the_database_folds_together_share_a_budget(
    client: AsyncClient, admin_auth_header: dict, test_db_session, throttle
):
    """Two spellings of one account that only the database lower-cases alike spend one budget."""
    folded = await test_db_session.scalar(select(func.lower("\u0130")))
    if folded != "i" or "\u0130".lower() == "i":
        pytest.skip("the test database does not fold dotted capital I to i")
    username = await _username(client, admin_auth_header)
    variant = username.replace("i", "\u0130", 1)
    assert variant != username

    assert (await _login(client, username, "wrong-password")).status_code == 401
    assert (await _login(client, variant, "wrong-password")).status_code == 401
    assert (await _login(client, username, PASSWORD)).status_code == 429


@pytest.mark.anyio
async def test_concurrent_failures_cannot_overrun_the_budget(
    client: AsyncClient, throttle
):
    """Wrong-password attempts sent at once still get only the budget's two tries."""
    username = f"absent_{uuid.uuid4().hex[:8]}"
    responses = await asyncio.gather(
        *(_login(client, username, "wrong-password") for _ in range(6))
    )
    statuses = sorted(resp.status_code for resp in responses)
    assert statuses == [401, 401, 429, 429, 429, 429]


def test_an_unreachable_store_falls_back_to_counting_in_memory(throttle):
    """A store error moves the count to the in-memory fallback instead of failing the request."""

    class Unreachable:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise ConnectionError("store down")

            return fail

    real = limiter._limiter
    limiter._limiter = Unreachable()
    try:
        key = uuid.uuid4().hex
        assert throttle.acquire(key) is None
        assert throttle.acquire(key) is None
        assert throttle.acquire(key) is not None
    finally:
        limiter._limiter = real
        limiter._storage_dead = False
