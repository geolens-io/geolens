"""Tests for sortable GET /admin/share-tokens/ (sort + order query params).

Every assertion is scoped to maps this test creates, via a unique token in the
map name that the endpoint's own search filter selects on. The per-worker
database is shared and other tests publish maps into it, so an assertion about
the whole list would be a claim about the worker rather than about this test.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from httpx import AsyncClient

from tests.factories import create_map_via_api

PASSWORD = "TestPass1234!"  # SEC-S16: meets 12-char + 3-class policy


async def _publish(client: AsyncClient, headers: dict, name: str) -> str:
    """Create a map, publish it, and return its id. No share link is minted."""
    created = await create_map_via_api(client, headers, name=name)
    map_id = created["id"]
    resp = await client.put(
        f"/maps/{map_id}", json={"visibility": "public"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return map_id


async def _list(client: AsyncClient, headers: dict, *, search: str, **params) -> dict:
    resp = await client.get(
        "/admin/share-tokens/",
        params={"search": search, "limit": 200, **params},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _names(payload: dict) -> list[str]:
    return [row["map_name"] for row in payload["tokens"]]


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sort_by_map_name_orders_both_directions(
    client: AsyncClient, admin_auth_header: dict
):
    """sort=map_name returns the scoped maps in alphabetical order."""
    token = f"msrt{uuid.uuid4().hex[:10]}"
    # Published in a deliberately non-alphabetical order.
    for suffix in ("mike", "alpha", "zulu"):
        await _publish(client, admin_auth_header, f"{token}_{suffix}")

    asc = _names(
        await _list(
            client, admin_auth_header, search=token, sort="map_name", order="asc"
        )
    )
    desc = _names(
        await _list(
            client, admin_auth_header, search=token, sort="map_name", order="desc"
        )
    )

    assert asc == [f"{token}_alpha", f"{token}_mike", f"{token}_zulu"]
    assert desc == [f"{token}_zulu", f"{token}_mike", f"{token}_alpha"]


@pytest.mark.anyio
async def test_default_sort_is_unchanged_created_at_descending(
    client: AsyncClient, admin_auth_header: dict
):
    """Omitting sort/order preserves the historical created_at DESC ordering."""
    token = f"msrt{uuid.uuid4().hex[:10]}"
    created = [
        await _publish(client, admin_auth_header, f"{token}_{n}") for n in range(3)
    ]

    payload = await _list(client, admin_auth_header, search=token)

    # Newest first: the reverse of publication order.
    assert [row["map_id"] for row in payload["tokens"]] == list(reversed(created))


async def _add_embed_token(session, map_id: str, *, is_active: bool) -> None:
    """Attach one embed token to a map, bypassing the edition-gated mint API.

    At most ONE ACTIVE token per map: `uq_embed_tokens_one_active_per_map` is a
    partial unique index on map_id WHERE is_active. The listing's count filters
    on is_active, so embed_token_count is only ever 0 or 1 — the sort separates
    "has a live embed" from "does not" rather than ranking volumes.
    """
    import uuid as _uuid
    from datetime import datetime, timedelta, timezone

    from app.modules.embed_tokens.models import EmbedToken

    raw = _uuid.uuid4().hex
    session.add(
        EmbedToken(
            map_id=_uuid.UUID(map_id),
            token_hash=raw + raw[:24],
            token_hint=raw[:8],
            scoped_dataset_ids=[],
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            is_active=is_active,
        )
    )
    await session.commit()


@pytest.mark.anyio
async def test_sort_by_embed_count_treats_no_tokens_as_zero(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A map with no active embed token sorts as 0, not as a NULL at one end.

    The count comes from a LEFT JOIN against an aggregate subquery filtered to
    active tokens, so the raw value is NULL — not 0 — both for a map that never
    had an embed token and for one whose only token is revoked. The listing
    COALESCEs it for display and the ordering uses that same expression;
    ordering by the raw aggregate would put those maps at an end of their own,
    leading the DESC view above the map that actually has a live embed.
    """
    token = f"msrt{uuid.uuid4().hex[:10]}"
    never_id = await _publish(client, admin_auth_header, f"{token}_never")
    revoked_id = await _publish(client, admin_auth_header, f"{token}_revoked")
    active_id = await _publish(client, admin_auth_header, f"{token}_active")
    await _add_embed_token(test_db_session, revoked_id, is_active=False)
    await _add_embed_token(test_db_session, active_id, is_active=True)

    asc = await _list(
        client, admin_auth_header, search=token, sort="embed_token_count", order="asc"
    )
    desc = await _list(
        client, admin_auth_header, search=token, sort="embed_token_count", order="desc"
    )

    # Guard against a vacuous pass: the NULL-backed zeroes must really read 0
    # in the payload, and the counts must actually differ across the fixtures.
    assert [r["embed_token_count"] for r in asc["tokens"]] == [0, 0, 1], asc["tokens"]
    assert [r["embed_token_count"] for r in desc["tokens"]] == [1, 0, 0]
    # The two zeroes tie, so only the counted row's position is deterministic.
    assert asc["tokens"][-1]["map_id"] == active_id
    assert desc["tokens"][0]["map_id"] == active_id
    assert {r["map_id"] for r in asc["tokens"][:2]} == {never_id, revoked_id}


@pytest.mark.anyio
@pytest.mark.parametrize("order", ["asc", "desc"])
async def test_maps_without_an_expiry_sort_last_in_both_directions(
    client: AsyncClient, admin_auth_header: dict, enterprise_edition, order
):
    """expires_at is null for never-expiring links AND for maps with no link.

    Postgres puts NULLs first on DESC, which would fill the top of a
    descending "Expires" view with every map that has no expiry at all.
    """
    token = f"msrt{uuid.uuid4().hex[:10]}"
    dated_id = await _publish(client, admin_auth_header, f"{token}_dated")
    share = await client.post(f"/maps/{dated_id}/share/", headers=admin_auth_header)
    assert share.status_code in (200, 201), share.text
    patch = await client.patch(
        f"/maps/{dated_id}/share/",
        json={"expires_at": "2030-06-01T00:00:00Z"},
        headers=admin_auth_header,
    )
    assert patch.status_code == 200, patch.text
    # No share link at all, so expires_at is null through the outer join.
    await _publish(client, admin_auth_header, f"{token}_nolink")

    payload = await _list(
        client, admin_auth_header, search=token, sort="expires_at", order=order
    )
    rows = payload["tokens"]

    # Only meaningful if the scoped set really mixes a null and a non-null.
    assert any(r["expires_at"] is None for r in rows), rows
    assert any(r["expires_at"] is not None for r in rows), rows

    first_null = next(i for i, r in enumerate(rows) if r["expires_at"] is None)
    assert all(r["expires_at"] is None for r in rows[first_null:]), (
        f"{order}: a non-null expires_at followed a null one: {rows}"
    )


@pytest.mark.anyio
async def test_sort_by_creator_orders_on_the_joined_username(
    client: AsyncClient, admin_auth_header: dict
):
    """sort=creator orders on the joined account name, not on created_by."""
    token = f"msrt{uuid.uuid4().hex[:10]}"
    names = []
    for suffix in ("mike", "alpha"):
        username = f"{token}_{suffix}"
        resp = await client.post(
            "/admin/users/",
            json={"username": username, "password": PASSWORD, "role": "editor"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        login = await client.post(
            "/auth/login", data={"username": username, "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        await _publish(client, headers, f"{token}_by_{suffix}")
        names.append(username)

    payload = await _list(
        client, admin_auth_header, search=token, sort="creator", order="asc"
    )

    assert [row["created_by"] for row in payload["tokens"]] == sorted(names)


@pytest.mark.anyio
async def test_sort_composes_with_the_status_filter(
    client: AsyncClient, admin_auth_header: dict
):
    """sort applies on top of the status filter rather than replacing it."""
    token = f"msrt{uuid.uuid4().hex[:10]}"
    for suffix in ("mike", "alpha"):
        map_id = await _publish(client, admin_auth_header, f"{token}_{suffix}")
        share = await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)
        assert share.status_code in (200, 201), share.text
    # A published map with no link: excluded by status=active regardless of sort.
    await _publish(client, admin_auth_header, f"{token}_nolink")

    payload = await _list(
        client,
        admin_auth_header,
        search=token,
        status="active",
        sort="map_name",
        order="desc",
    )

    assert _names(payload) == [f"{token}_mike", f"{token}_alpha"]
    assert payload["total"] == 2


@pytest.mark.anyio
async def test_paging_a_non_unique_sort_key_never_repeats_a_row(
    client: AsyncClient, admin_auth_header: dict
):
    """Paging by embed count (0 for every row) yields each map once.

    OFFSET paging over a non-unique ORDER BY key is free to return a row on two
    consecutive pages; the Map.id tiebreak makes the ordering total.
    """
    token = f"msrt{uuid.uuid4().hex[:10]}"
    expected = {
        await _publish(client, admin_auth_header, f"{token}_{n}") for n in range(6)
    }

    seen: list[str] = []
    for skip in (0, 2, 4):
        resp = await client.get(
            "/admin/share-tokens/",
            params={
                "search": token,
                "sort": "embed_token_count",
                "order": "asc",
                "skip": skip,
                "limit": 2,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        seen.extend(row["map_id"] for row in resp.json()["tokens"])

    assert len(seen) == len(set(seen)), f"a row appeared on two pages: {seen}"
    assert set(seen) == expected


def test_ordering_clause_carries_a_unique_tiebreak_and_pins_nulls():
    """Assert the ORDER BY shape directly, because behaviour cannot prove it.

    The paging test above passes with or without the id tiebreak: at these row
    counts Postgres seq-scans and happens to return a stable order, so it
    cannot detect the regression it describes. Compiling the clause can.

    The helper takes the share alias and embed-count expression as arguments
    (both are per-call constructs), so this passes the unaliased model and a
    bare literal — enough to compile a clause and read its decorations.
    """
    from sqlalchemy import literal_column

    from app.modules.catalog.maps.models import Map, MapShareToken
    from app.modules.catalog.maps.service_public import (
        _NULLABLE_SHARE_TOKEN_SORT_FIELDS,
        _share_token_ordering,
    )

    fields = ("map_name", "created_at", "creator", "expires_at", "embed_token_count")
    for field in fields:
        for order in ("asc", "desc"):
            clauses = _share_token_ordering(
                field,
                order,
                share=MapShareToken,
                embed_count=literal_column("embed_count"),
            )
            assert clauses[-1] is Map.id, (
                f"{field}/{order} has no unique tiebreak: {[str(c) for c in clauses]}"
            )
            rendered = str(clauses[0]).upper()
            assert order.upper() in rendered, rendered
            if field in _NULLABLE_SHARE_TOKEN_SORT_FIELDS:
                assert "NULLS LAST" in rendered, f"{field}/{order}: {rendered}"
            else:
                assert "NULLS LAST" not in rendered, f"{field}/{order}: {rendered}"

    assert _NULLABLE_SHARE_TOKEN_SORT_FIELDS <= set(fields)


def test_link_status_is_not_offered_as_a_sort_key():
    """Link status is derived in Python, so the database cannot order by it.

    Pinned as a test because the column IS in the response, which makes adding
    it to the allowlist look harmless; it would need a CASE the query lacks.
    """
    from sqlalchemy import literal_column

    from app.modules.catalog.maps.models import MapShareToken
    from app.modules.catalog.maps.service_public import _share_token_ordering

    for field in ("link_status", "is_active", "status"):
        with pytest.raises(ValueError, match="Unsupported sort field"):
            _share_token_ordering(
                field,
                "asc",
                share=MapShareToken,
                embed_count=literal_column("embed_count"),
            )


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bogus_sort",
    [
        "basemap_style",  # a real Map column, deliberately not sortable
        "link_status",  # derived in Python after the query
        "map_name; DROP TABLE catalog.maps",
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
        "/admin/share-tokens/",
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
        "/admin/share-tokens/",
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
    from typing import get_args

    from app.modules.admin.schemas import ShareTokenSortField

    fields = get_args(ShareTokenSortField)
    assert fields, "allowlist is empty; the tests above prove nothing"
    for field in fields:
        for order in ("asc", "desc"):
            resp = await client.get(
                "/admin/share-tokens/",
                params={"sort": field, "order": order, "limit": 1},
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, f"{field}/{order} -> {resp.text}"


@pytest.mark.anyio
async def test_service_layer_rejects_unmapped_sort_key(test_db_session):
    """The service refuses an unmapped key even if the router is bypassed."""
    from app.modules.catalog.maps.service import list_share_tokens

    with pytest.raises(ValueError, match="Unsupported sort field"):
        await list_share_tokens(test_db_session, sort="basemap_style")
    with pytest.raises(ValueError, match="Unsupported sort order"):
        await list_share_tokens(test_db_session, order="sideways")
