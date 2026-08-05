"""Tests for sortable GET /admin/users/ (sort + order query params).

Every assertion here is scoped to users the test itself creates, via a unique
search token in the username. The per-worker database is shared and dozens of
other tests mint accounts into it, so an assertion about the *whole* list would
be a claim about the worker rather than about this test.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from httpx import AsyncClient

PASSWORD = "TestPass1234!"  # SEC-S16: meets 12-char + 3-class policy


async def _create_user(
    client: AsyncClient,
    admin_headers: dict,
    username: str,
    *,
    email: str | None = None,
    role: str = "viewer",
) -> str:
    """Create a user with an exact username and return its id."""
    body: dict = {"username": username, "password": PASSWORD, "role": role}
    if email is not None:
        body["email"] = email
    resp = await client.post("/admin/users/", json=body, headers=admin_headers)
    assert resp.status_code == 201, f"Create {username} failed: {resp.text}"
    return resp.json()["id"]


async def _list(
    client: AsyncClient,
    admin_headers: dict,
    *,
    search: str,
    **params: object,
) -> dict:
    resp = await client.get(
        "/admin/users/",
        params={"search": search, "limit": 200, **params},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _usernames(payload: dict) -> list[str]:
    return [u["username"] for u in payload["users"]]


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sort_by_username_orders_both_directions(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """sort=username returns the scoped users in alphabetical order."""
    token = f"srt{uuid.uuid4().hex[:10]}"
    # Created in an order that is deliberately NOT alphabetical, so a response
    # that merely preserved insertion order would fail this test.
    for suffix in ("mike", "alpha", "zulu"):
        await _create_user(client, admin_auth_header, f"{token}_{suffix}")

    asc = _usernames(
        await _list(
            client, admin_auth_header, search=token, sort="username", order="asc"
        )
    )
    desc = _usernames(
        await _list(
            client, admin_auth_header, search=token, sort="username", order="desc"
        )
    )

    assert asc == [f"{token}_alpha", f"{token}_mike", f"{token}_zulu"]
    assert desc == [f"{token}_zulu", f"{token}_mike", f"{token}_alpha"]


@pytest.mark.anyio
async def test_default_sort_is_unchanged_created_at_ascending(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Omitting sort/order preserves the historical created_at ASC ordering."""
    token = f"srt{uuid.uuid4().hex[:10]}"
    created = [
        await _create_user(client, admin_auth_header, f"{token}_{suffix}")
        for suffix in ("zulu", "mike", "alpha")  # reverse-alphabetical on purpose
    ]

    payload = await _list(client, admin_auth_header, search=token)

    assert [u["id"] for u in payload["users"]] == created


@pytest.mark.anyio
async def test_null_last_login_sorts_last_in_both_directions(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Never-logged-in accounts stay at the bottom on ASC and DESC alike.

    Postgres puts NULLs first on DESC by default, which would float every
    never-logged-in account to the top of a "most recent login" view.
    """
    token = f"srt{uuid.uuid4().hex[:10]}"
    logged_in = f"{token}_seen"
    await _create_user(client, admin_auth_header, logged_in)
    await _create_user(client, admin_auth_header, f"{token}_never")

    # Give exactly one of them a last_login_at by authenticating as them.
    resp = await client.post(
        "/auth/login",
        data={"username": logged_in, "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text

    for order in ("asc", "desc"):
        payload = await _list(
            client, admin_auth_header, search=token, sort="last_login_at", order=order
        )
        rows = payload["users"]
        # Guard against a vacuous pass: this only tests anything if the scoped
        # set really does contain both a null and a non-null last_login_at.
        assert any(r["last_login_at"] is None for r in rows), rows
        assert any(r["last_login_at"] is not None for r in rows), rows

        first_null = next(i for i, r in enumerate(rows) if r["last_login_at"] is None)
        assert all(r["last_login_at"] is None for r in rows[first_null:]), (
            f"{order}: a non-null last_login_at followed a null one: {rows}"
        )


@pytest.mark.anyio
async def test_sort_composes_with_status_and_search_filters(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """sort applies on top of the status filter rather than replacing it."""
    token = f"srt{uuid.uuid4().hex[:10]}"
    for suffix in ("mike", "alpha", "zulu"):
        await _create_user(client, admin_auth_header, f"{token}_{suffix}")

    payload = await _list(
        client,
        admin_auth_header,
        search=token,
        status="active",
        sort="username",
        order="desc",
    )

    assert _usernames(payload) == [
        f"{token}_zulu",
        f"{token}_mike",
        f"{token}_alpha",
    ]
    assert all(u["status"] == "active" for u in payload["users"])
    assert payload["total"] == 3


@pytest.mark.anyio
async def test_paging_a_non_unique_sort_key_never_repeats_a_row(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Paging by `status` (identical for every row) yields each user once.

    OFFSET paging over a non-unique ORDER BY key is free to return a row on
    two consecutive pages; the id tiebreak makes the ordering total.
    """
    token = f"srt{uuid.uuid4().hex[:10]}"
    expected = {
        await _create_user(client, admin_auth_header, f"{token}_{n}") for n in range(6)
    }

    seen: list[str] = []
    for skip in (0, 2, 4):
        resp = await client.get(
            "/admin/users/",
            params={
                "search": token,
                "sort": "status",
                "order": "asc",
                "skip": skip,
                "limit": 2,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        seen.extend(u["id"] for u in resp.json()["users"])

    assert len(seen) == len(set(seen)), f"a row appeared on two pages: {seen}"
    assert set(seen) == expected


def test_ordering_clause_carries_a_unique_tiebreak_and_pins_nulls():
    """Assert the ORDER BY shape directly, because behaviour cannot prove it.

    The paging test above passes with or without the id tiebreak: at these row
    counts Postgres seq-scans and happens to return a stable order, so it
    cannot detect the regression it describes. Compiling the clause can.
    """
    from app.modules.auth.models import User
    from app.modules.admin.service import USER_SORT_COLUMNS, AdminService

    for field in USER_SORT_COLUMNS:
        for order in ("asc", "desc"):
            clauses = AdminService._user_ordering(field, order)
            assert clauses[-1] is User.id, (
                f"{field}/{order} has no unique tiebreak: {[str(c) for c in clauses]}"
            )
            assert order.upper() in str(clauses[0]).upper(), str(clauses[0])

    nulls_last_asc = str(AdminService._user_ordering("last_login_at", "asc")[0])
    nulls_last_desc = str(AdminService._user_ordering("last_login_at", "desc")[0])
    assert "NULLS LAST" in nulls_last_asc.upper(), nulls_last_asc
    assert "NULLS LAST" in nulls_last_desc.upper(), nulls_last_desc

    # A non-nullable column should not carry the NULLS LAST decoration.
    assert (
        "NULLS LAST"
        not in str(AdminService._user_ordering("username", "asc")[0]).upper()
    )


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bogus_sort",
    [
        "password_hash",  # a real column, deliberately not sortable
        "roles",  # not a column at all
        "username; DROP TABLE catalog.users",
        "(SELECT 1)",
        "",
    ],
)
@pytest.mark.anyio
async def test_unknown_sort_field_is_refused_not_executed(
    client: AsyncClient,
    admin_auth_header: dict,
    bogus_sort: str,
):
    """A sort field outside the allowlist is a 422, never a silent default."""
    resp = await client.get(
        "/admin/users/",
        params={"sort": bogus_sort, "limit": 1},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, f"{bogus_sort!r} -> {resp.status_code} {resp.text}"


@pytest.mark.parametrize("bogus_order", ["sideways", "ASC; --", "1"])
@pytest.mark.anyio
async def test_unknown_sort_order_is_refused(
    client: AsyncClient,
    admin_auth_header: dict,
    bogus_order: str,
):
    """A direction outside asc/desc is a 422."""
    resp = await client.get(
        "/admin/users/",
        params={"order": bogus_order, "limit": 1},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, f"{bogus_order!r} -> {resp.status_code}"


@pytest.mark.anyio
async def test_every_advertised_sort_field_is_accepted(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """The refusal tests above must not be passing by refusing everything."""
    from app.modules.admin.service import USER_SORT_COLUMNS

    assert USER_SORT_COLUMNS, "allowlist is empty; the tests below prove nothing"
    for field in USER_SORT_COLUMNS:
        for order in ("asc", "desc"):
            resp = await client.get(
                "/admin/users/",
                params={"sort": field, "order": order, "limit": 1},
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, f"{field}/{order} -> {resp.text}"


@pytest.mark.anyio
async def test_service_layer_rejects_unmapped_sort_key(test_db_session):
    """The service refuses an unmapped key even if the router is bypassed."""
    from app.modules.admin.service import AdminService

    service = AdminService(test_db_session)
    with pytest.raises(ValueError, match="Unsupported sort field"):
        await service.list_users(sort="password_hash")
    with pytest.raises(ValueError, match="Unsupported sort order"):
        await service.list_users(order="sideways")
