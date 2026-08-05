"""Tests for sortable GET /admin/audit-logs/ (sort + order query params).

Every assertion is scoped to rows this test creates, via a unique token in the
`action` value that the endpoint's own search filter selects on. The per-worker
database is shared and most tests emit audit rows into it, so an assertion
about the whole list would be a claim about the worker rather than this test.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from httpx import AsyncClient

from app.modules.audit.service import (
    _audit_ordering,
    _audit_sort_columns,
    query_audit_logs,
)

PASSWORD = "TestPass1234!"  # SEC-S16: meets 12-char + 3-class policy


async def _log(
    session,
    *,
    action,
    resource_type="dataset",
    user_id=None,
    ip_address=None,
):
    from app.modules.audit.models import AuditLog

    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=uuid.uuid4(),
        ip_address=ip_address,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


def _actions(logs) -> list[str]:
    return [log.action for log in logs]


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


async def test_sort_by_action_orders_both_directions(test_db_session):
    """sort=action returns the scoped rows in alphabetical order."""
    token = f"asrt{uuid.uuid4().hex[:10]}"
    # Written in a deliberately non-alphabetical order, so a response that
    # merely preserved insertion order would fail this test.
    for suffix in ("mike", "alpha", "zulu"):
        await _log(test_db_session, action=f"{token}.{suffix}")

    asc, _ = await query_audit_logs(
        test_db_session, search=token, sort="action", order="asc"
    )
    desc, _ = await query_audit_logs(
        test_db_session, search=token, sort="action", order="desc"
    )

    assert _actions(asc) == [f"{token}.alpha", f"{token}.mike", f"{token}.zulu"]
    assert _actions(desc) == [f"{token}.zulu", f"{token}.mike", f"{token}.alpha"]


async def test_default_sort_is_unchanged_created_at_descending(test_db_session):
    """Omitting sort/order preserves the historical created_at DESC ordering."""
    token = f"asrt{uuid.uuid4().hex[:10]}"
    created = [
        (await _log(test_db_session, action=f"{token}.{n}")).id for n in range(3)
    ]

    logs, _ = await query_audit_logs(test_db_session, search=token)

    # Newest first: the reverse of the order they were written in.
    assert [log.id for log in logs] == list(reversed(created))


async def test_sort_by_username_orders_by_the_joined_users_row(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """sort=username orders on the joined account name, not on user_id."""
    token = f"asrt{uuid.uuid4().hex[:10]}"
    ids = {}
    for suffix in ("mike", "alpha", "zulu"):
        resp = await client.post(
            "/admin/users/",
            json={
                "username": f"{token}_{suffix}",
                "password": PASSWORD,
                "role": "viewer",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        ids[suffix] = uuid.UUID(resp.json()["id"])

    for suffix in ("mike", "alpha", "zulu"):
        await _log(test_db_session, action=f"{token}.evt", user_id=ids[suffix])

    logs, _ = await query_audit_logs(
        test_db_session, search=f"{token}.evt", sort="username", order="asc"
    )

    assert [log.user.username for log in logs] == [
        f"{token}_alpha",
        f"{token}_mike",
        f"{token}_zulu",
    ]


async def test_username_sort_does_not_break_the_username_search_filter(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Sorting by username must not change WHICH rows the search returns.

    The search filter reaches rows through two arms — the action text and a
    ``AuditLog.user_id.in_(select(User.id)...)`` sub-select on the username —
    and sorting by username adds a second reference to `users`. That is the
    kind of change that alters a result set rather than erroring, so this
    asserts set equality against the unsorted query instead of just a
    non-empty response.

    Honest limit: this does NOT discriminate the aliased ORDER BY join from a
    bare-entity one. Measured on 2026-08-05, both compile to identical SQL,
    because SQLAlchemy only auto-correlates a subquery when that leaves it
    another FROM. The alias in query_audit_logs is insurance against a future
    filter rewrite, and this test pins the property that would break.
    """
    token = f"asrt{uuid.uuid4().hex[:10]}"
    resp = await client.post(
        "/admin/users/",
        json={"username": f"{token}_actor", "password": PASSWORD, "role": "viewer"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    actor_id = uuid.UUID(resp.json()["id"])

    # One row reachable ONLY through the username arm of the search filter
    # (its action does not contain the token), plus one reachable only through
    # the action arm (it has no user at all).
    by_username = await _log(test_db_session, action="unrelated.evt", user_id=actor_id)
    by_action = await _log(test_db_session, action=f"{token}.evt")

    default_logs, default_total = await query_audit_logs(test_db_session, search=token)
    sorted_logs, sorted_total = await query_audit_logs(
        test_db_session, search=token, sort="username", order="asc"
    )

    # Guard against a vacuous pass: the search must really be reaching both
    # arms, or the correlation regression would have nothing to break.
    assert {by_username.id, by_action.id} <= {log.id for log in default_logs}
    assert {log.id for log in sorted_logs} == {log.id for log in default_logs}
    assert sorted_total == default_total


@pytest.mark.parametrize("order", ["asc", "desc"])
async def test_rows_without_a_user_sort_last_in_both_directions(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    order,
):
    """A row whose user was deleted (user_id NULL) stays at the bottom.

    Postgres puts NULLs first on DESC, which would fill the top of a
    descending "User" view with anonymous and orphaned rows.
    """
    token = f"asrt{uuid.uuid4().hex[:10]}"
    resp = await client.post(
        "/admin/users/",
        json={"username": f"{token}_actor", "password": PASSWORD, "role": "viewer"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    actor_id = uuid.UUID(resp.json()["id"])

    named = await _log(test_db_session, action=f"{token}.evt", user_id=actor_id)
    anonymous = await _log(test_db_session, action=f"{token}.evt", user_id=None)

    logs, _ = await query_audit_logs(
        test_db_session, search=f"{token}.evt", sort="username", order=order
    )
    positions = {log.id: i for i, log in enumerate(logs)}

    assert {named.id, anonymous.id} <= positions.keys()
    assert positions[named.id] < positions[anonymous.id], (
        f"{order}: a row with no user outranked one with a username"
    )


@pytest.mark.parametrize("order", ["asc", "desc"])
async def test_null_ip_address_sorts_last_in_both_directions(test_db_session, order):
    """ip_address is nullable (background jobs); nulls stay at the bottom."""
    token = f"asrt{uuid.uuid4().hex[:10]}"
    with_ip = await _log(
        test_db_session, action=f"{token}.evt", ip_address="203.0.113.7"
    )
    without_ip = await _log(test_db_session, action=f"{token}.evt", ip_address=None)

    logs, _ = await query_audit_logs(
        test_db_session, search=token, sort="ip_address", order=order
    )
    positions = {log.id: i for i, log in enumerate(logs)}

    assert {with_ip.id, without_ip.id} <= positions.keys()
    assert positions[with_ip.id] < positions[without_ip.id], (
        f"{order}: a NULL ip_address outranked a real one"
    )


async def test_sort_composes_with_the_resource_type_filter(test_db_session):
    """sort applies on top of the existing filters rather than replacing them."""
    token = f"asrt{uuid.uuid4().hex[:10]}"
    await _log(test_db_session, action=f"{token}.mike", resource_type="dataset")
    await _log(test_db_session, action=f"{token}.alpha", resource_type="dataset")
    await _log(test_db_session, action=f"{token}.zulu", resource_type="map")

    logs, total = await query_audit_logs(
        test_db_session,
        search=token,
        resource_type="dataset",
        sort="action",
        order="desc",
    )

    assert _actions(logs) == [f"{token}.mike", f"{token}.alpha"]
    assert total == 2


async def test_paging_a_non_unique_sort_key_never_repeats_a_row(test_db_session):
    """Paging by `resource_type` (identical for every row) yields each row once.

    OFFSET paging over a non-unique ORDER BY key is free to return a row on two
    consecutive pages; the id tiebreak makes the ordering total.
    """
    token = f"asrt{uuid.uuid4().hex[:10]}"
    expected = {
        (await _log(test_db_session, action=f"{token}.{n}")).id for n in range(6)
    }

    seen: list = []
    for skip in (0, 2, 4):
        logs, _ = await query_audit_logs(
            test_db_session,
            search=token,
            sort="resource_type",
            order="asc",
            skip=skip,
            limit=2,
        )
        seen.extend(log.id for log in logs)

    assert len(seen) == len(set(seen)), f"a row appeared on two pages: {seen}"
    assert set(seen) == expected


def test_ordering_clause_carries_a_unique_tiebreak_and_pins_nulls():
    """Assert the ORDER BY shape directly, because behaviour cannot prove it.

    The paging test above passes with or without the id tiebreak: at these row
    counts Postgres seq-scans and happens to return a stable order, so it
    cannot detect the regression it describes. Compiling the clause can.
    """
    from sqlalchemy.orm import aliased

    from app.modules.audit.models import AuditLog
    from app.modules.audit.service import _NULLABLE_AUDIT_SORT_COLUMNS
    from app.modules.auth.models import User

    sort_user = aliased(User, name="audit_sort_user")

    for field in _audit_sort_columns(sort_user):
        for order in ("asc", "desc"):
            clauses = _audit_ordering(field, order, sort_user)
            assert clauses[-1] is AuditLog.id, (
                f"{field}/{order} has no unique tiebreak: {[str(c) for c in clauses]}"
            )
            rendered = str(clauses[0]).upper()
            assert order.upper() in rendered, rendered
            if field in _NULLABLE_AUDIT_SORT_COLUMNS:
                assert "NULLS LAST" in rendered, f"{field}/{order}: {rendered}"
            else:
                assert "NULLS LAST" not in rendered, f"{field}/{order}: {rendered}"

    assert _NULLABLE_AUDIT_SORT_COLUMNS <= set(_audit_sort_columns(sort_user))


def test_resource_name_is_not_offered_as_a_sort_key():
    """resource_name is resolved per page after the query, so it cannot sort.

    Pinned as a test because the column IS in the response model, which makes
    adding it to the allowlist look harmless; it would order by nothing.
    """
    from sqlalchemy.orm import aliased

    from app.modules.auth.models import User

    assert "resource_name" not in _audit_sort_columns(aliased(User))


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bogus_sort",
    [
        "details",  # a real column, deliberately not sortable
        "resource_name",  # resolved after the query, not a column
        "action; DROP TABLE catalog.audit_logs",
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
        "/admin/audit-logs/",
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
        "/admin/audit-logs/",
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
    from sqlalchemy.orm import aliased

    from app.modules.auth.models import User

    fields = _audit_sort_columns(aliased(User))
    assert fields, "allowlist is empty; the tests above prove nothing"
    for field in fields:
        for order in ("asc", "desc"):
            resp = await client.get(
                "/admin/audit-logs/",
                params={"sort": field, "order": order, "limit": 1},
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, f"{field}/{order} -> {resp.text}"


async def test_service_layer_rejects_unmapped_sort_key(test_db_session):
    """The service refuses an unmapped key even if the router is bypassed."""
    with pytest.raises(ValueError, match="Unsupported sort field"):
        await query_audit_logs(test_db_session, sort="details")
    with pytest.raises(ValueError, match="Unsupported sort order"):
        await query_audit_logs(test_db_session, order="sideways")


def test_export_endpoint_takes_no_sort_parameters():
    """fix(#1204): the CSV export shares the list's FILTERS, not its ordering.

    Asserted rather than merely commented, so a later change that wires sort
    into the export has to delete this test and say why.

    Reads the route table through _iter_api_routes: fastapi 0.140 keeps
    included-router routes nested, so scanning app.routes directly finds
    neither endpoint and every assertion below would be vacuous.
    """
    from app.api.main import _iter_api_routes, app

    params = {
        ctx.path: {p.name for p in ctx.route.dependant.query_params}
        for ctx in _iter_api_routes(app)
        if ctx.path in ("/admin/audit-logs/", "/admin/audit-logs/export/{format}")
    }
    assert set(params) == {
        "/admin/audit-logs/",
        "/admin/audit-logs/export/{format}",
    }, f"route probe found {sorted(params)}"

    listing, export = (
        params["/admin/audit-logs/"],
        params["/admin/audit-logs/export/{format}"],
    )
    # Positive control: the two endpoints really do share their filters, so
    # "the export lacks sort" is a fact about ordering and not about the probe.
    assert {"search", "action", "user_id"} <= listing & export
    assert {"sort", "order"} <= listing
    assert not {"sort", "order"} & export
