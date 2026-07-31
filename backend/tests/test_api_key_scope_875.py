"""fix(#875): per-key scopes — least-privilege machine credentials.

An API key impersonated its owner completely, so anyone building an
application on GeoLens had to embed a credential that could also mutate or
delete everything its owner could. The deprecated ``?api_key=`` query lane
makes that sharper: a credential in a URL lands in access logs and any
upstream proxy's logs, and a read-only one is far less dangerous there.

Enforcement is HTTP-method based at the key-resolution chokepoint, not
capability based. These tests pin the three things that can go wrong:
the refusal must be a 403 and not a fallthrough 401, existing keys must be
untouched, and the single #565 carve-out must stay a named route rather than
a "POST that looks like a read" category.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.modules.auth.dependencies import (
    _READ_ONLY_KEY_EXEMPT_ROUTES,
    _read_only_key_may_call,
)
from tests.conftest import get_auth_header
from tests.factories import create_dataset

ADMIN_USER = settings.geolens_admin_username
ADMIN_PASS = settings.geolens_admin_password.get_secret_value()


async def _get_admin(client: AsyncClient, headers: dict) -> uuid.UUID:
    return uuid.UUID((await client.get("/auth/me/", headers=headers)).json()["id"])


async def _mint(client: AsyncClient, headers: dict, **body) -> dict:
    resp = await client.post(
        "/auth/api-keys/", json={"name": "Scoped Key", **body}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Minting round-trips the scope, on both surfaces
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_self_service_mint_round_trips_read_only(client: AsyncClient):
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    data = await _mint(client, headers, scope="read_only")
    assert data["scope"] == "read_only"

    listing = await client.get("/auth/api-keys/", headers=headers)
    listed = {item["id"]: item for item in listing.json()["items"]}
    assert listed[data["id"]]["scope"] == "read_only"


@pytest.mark.anyio
async def test_self_service_mint_defaults_to_full(client: AsyncClient):
    """Omitting scope must keep the pre-#875 behaviour for every caller."""
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    data = await _mint(client, headers)
    assert data["scope"] == "full"


@pytest.mark.anyio
async def test_admin_mint_round_trips_read_only(client: AsyncClient):
    """The service-account key an admin mints for an application is the most
    likely key to want read_only, so leaving this surface unwired would invert
    the whole point."""
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    admin_id = (await client.get("/auth/me/", headers=headers)).json()["id"]

    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": admin_id, "name": "Service Account", "scope": "read_only"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["scope"] == "read_only"

    listing = await client.get("/admin/api-keys/", headers=headers)
    listed = {item["id"]: item for item in listing.json()["items"]}
    assert listed[resp.json()["id"]]["scope"] == "read_only"


@pytest.mark.anyio
async def test_admin_mint_defaults_to_full(client: AsyncClient):
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    admin_id = (await client.get("/auth/me/", headers=headers)).json()["id"]

    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": admin_id, "name": "Unscoped"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["scope"] == "full"


@pytest.mark.anyio
async def test_unknown_scope_is_rejected(client: AsyncClient):
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Bogus", "scope": "admin"},
        headers=headers,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["full", "read_only"])
async def test_scope_appears_in_the_audit_event(
    client: AsyncClient, test_db_session, scope
):
    from sqlalchemy import select

    from app.modules.audit.models import AuditLog

    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    data = await _mint(client, headers, scope=scope)

    row = (
        await test_db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "api_key.create",
                AuditLog.resource_id == uuid.UUID(data["id"]),
            )
        )
    ).scalar_one()
    assert row.details["scope"] == scope


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_read_only_key_authenticates_a_get(client: AsyncClient):
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers, scope="read_only"))["key"]

    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 200

    search_resp = await client.get(
        "/search/datasets", headers={"X-Api-Key": raw_key}, params={"q": "test"}
    )
    assert search_resp.status_code == 200


@pytest.mark.anyio
async def test_read_only_key_authenticates_the_deprecated_query_lane(
    client: AsyncClient,
):
    """The query lane is exactly where a read-only credential matters most:
    it is written into access logs and any upstream proxy's logs."""
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers, scope="read_only"))["key"]

    resp = await client.get(f"/auth/me/?api_key={raw_key}")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_read_only_key_is_refused_on_post_with_403_not_401(
    client: AsyncClient,
):
    """The failure mode matters. Returning None instead of raising would fall
    through to the anonymous/JWT path and surface a confusing 401."""
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers, scope="read_only"))["key"]

    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Escalation"},
        headers={"X-Api-Key": raw_key},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "This API key is read-only"


@pytest.mark.anyio
async def test_read_only_key_is_refused_on_delete(client: AsyncClient):
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    victim = await _mint(client, headers)
    raw_key = (await _mint(client, headers, scope="read_only"))["key"]

    resp = await client.delete(
        f"/auth/api-keys/{victim['id']}", headers={"X-Api-Key": raw_key}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "This API key is read-only"

    # And the target key is still there.
    listing = await client.get("/auth/api-keys/", headers=headers)
    assert victim["id"] in {item["id"] for item in listing.json()["items"]}


@pytest.mark.anyio
async def test_read_only_key_is_refused_on_an_optional_auth_post(
    client: AsyncClient,
):
    """A scope violation must not degrade to anonymous on optional-auth routes
    either — that would silently downgrade the caller to the public view
    instead of telling them why the request failed.

    POST /tiles/tokens/ resolves via get_optional_user and answers anonymous
    callers with 200, so it is the sharpest case: without the raise, a
    read_only key would get a quietly narrower result instead of a refusal.
    """
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers, scope="read_only"))["key"]

    resp = await client.post(
        "/tiles/tokens/",
        json={"dataset_ids": [str(uuid.uuid4())]},
        headers={"X-Api-Key": raw_key},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "This API key is read-only"


@pytest.mark.anyio
async def test_full_key_still_reaches_the_optional_auth_post(client: AsyncClient):
    """The paired control: the refusal above is the scope, not the route."""
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers))["key"]

    resp = await client.post(
        "/tiles/tokens/",
        json={"dataset_ids": [str(uuid.uuid4())]},
        headers={"X-Api-Key": raw_key},
    )
    # The batch never fails on a per-dataset error, so an unknown id still
    # answers 200 — what matters is that the credential was not refused.
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_full_key_is_unchanged_on_read_and_write(client: AsyncClient):
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers, scope="full"))["key"]

    me_resp = await client.get("/auth/me/", headers={"X-Api-Key": raw_key})
    assert me_resp.status_code == 200

    created = await client.post(
        "/auth/api-keys/",
        json={"name": "Minted By A Full Key"},
        headers={"X-Api-Key": raw_key},
    )
    assert created.status_code == 201


@pytest.mark.anyio
async def test_key_predating_the_migration_resolves_as_full(
    client: AsyncClient, test_db_session
):
    """The server_default is what makes this backward compatible. Simulate a
    pre-0031 row by clearing the column to its default."""
    from sqlalchemy import text, update

    from app.modules.auth.models import ApiKey

    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    data = await _mint(client, headers, scope="read_only")

    await test_db_session.execute(
        update(ApiKey)
        .where(ApiKey.id == uuid.UUID(data["id"]))
        .values(scope=text("DEFAULT"))
    )
    await test_db_session.commit()

    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Backfilled Key Still Writes"},
        headers={"X-Api-Key": data["key"]},
    )
    assert resp.status_code == 201


@pytest.mark.anyio
async def test_usage_is_recorded_before_the_scope_refusal(
    client: AsyncClient, test_db_session
):
    """Deliberate ordering: the key DID authenticate, so last_used_at moves
    even when the request is refused on what it asked to do. A client
    hammering writes with a read-only key must not look dormant."""
    from sqlalchemy import select

    from app.modules.auth.models import ApiKey

    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    data = await _mint(client, headers, scope="read_only")

    async def _last_used():
        await test_db_session.commit()  # see the side session's write
        return (
            await test_db_session.execute(
                select(ApiKey.last_used_at).where(ApiKey.id == uuid.UUID(data["id"]))
            )
        ).scalar_one()

    assert await _last_used() is None

    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Refused"},
        headers={"X-Api-Key": data["key"]},
    )
    assert resp.status_code == 403
    assert await _last_used() is not None


# ---------------------------------------------------------------------------
# The #565 carve-out
# ---------------------------------------------------------------------------


def test_safe_methods_pass_on_any_route():
    for method in ("GET", "HEAD", "OPTIONS"):
        assert _read_only_key_may_call(method, "/api/datasets/") is True


def test_unsafe_methods_are_refused_off_the_exempt_list():
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert _read_only_key_may_call(method, "/api/datasets/") is False


def test_the_carve_out_is_a_named_method_and_route():
    """Decided in #875 and #565: a read_only key MAY call the SELECT-only
    sandbox endpoint, because it is a read. The exemption is an exact
    (method, route template) pair so nothing inherits it by resembling one."""
    assert _READ_ONLY_KEY_EXEMPT_ROUTES == frozenset(
        {
            ("POST", "/api/query/"),
            ("POST", "/api/query"),
            ("POST", "/stac/search"),
        }
    )
    assert _read_only_key_may_call("POST", "/api/query/") is True
    # ROUTE-01's dual-shape decorator registers both spellings of the same
    # handler, so both are exempt.
    assert _read_only_key_may_call("POST", "/api/query") is True
    # A neighbour that merely looks like it inherits nothing.
    assert _read_only_key_may_call("POST", "/api/query/run") is False
    # Exempting the PATH would have carried a future destructive method with
    # it; the pair is what stops that.
    assert _read_only_key_may_call("DELETE", "/api/query/") is False
    assert _read_only_key_may_call("PUT", "/api/query/") is False
    assert _read_only_key_may_call("DELETE", "/api/query") is False


def test_an_unresolvable_route_fails_closed():
    """When Starlette cannot give a template the value is a placeholder, which
    is in no exemption set."""
    assert _read_only_key_may_call("POST", "<unmatched-route>") is False


def test_565_route_is_not_mounted_yet():
    """The carve-out is a hook, not a live exemption. #565 has not landed, so
    nothing is exempt today.

    Whoever lands POST /api/query/ owns deleting this test and asserting the
    live behaviour instead — which is the point of it being here.

    Uses ``iter_route_contexts`` rather than scanning ``app.routes``: on
    fastapi 0.140 ``include_router`` is lazy, so ``app.routes`` holds only the
    top-level entries and a plain scan silently sees a fraction of the API
    (same trap documented in test_rule1_structural.py).
    """
    from fastapi.routing import iter_route_contexts

    from app.api.main import app

    mounted = {ctx.path for ctx in iter_route_contexts(app.routes)}
    assert "/api/query/" not in mounted, (
        "POST /api/query/ now exists. Replace this test with the live "
        "assertions: a read_only key succeeds on it, and still gets 403 on "
        "another POST."
    )


# ---------------------------------------------------------------------------
# fix(#875 codex r1): "safe method" is not the same as "no side effect"
# ---------------------------------------------------------------------------

# GET handlers that touch a write marker but are NOT writes a read_only key
# should be refused, each with the reason. Asserted exact in both directions
# below, so a new one has to be classified rather than silently inherited.
_BENIGN_WRITING_GET_ROUTES: dict[str, str] = {
    # Owner-gated READS. They call check_dataset_write_access to decide who may
    # see the answer; neither writes anything.
    "/audit/datasets/{dataset_id}/column-ddl": "owner-gated read, no write",
    "/layers/{dataset_id}/columns/{column_name}/references": (
        "owner-gated read, no write"
    ),
    # Reads that commit an AUDIT row for having been read. The commit records
    # the read; it does not change the resource, and refusing them would refuse
    # the reads this feature exists to serve.
    "/admin/audit-logs/export/{format}": "commits an audit row for the export",
    "/admin/users/export.csv": "commits an audit row for the export",
    "/config-ops/export": "commits an audit row for the export",
    "/config-ops/export/": "commits an audit row for the export",
    "/datasets/{dataset_id}": "commits an audit row for the read",
    "/datasets/{dataset_id}/download/cog": "commits an audit row for the read",
    "/datasets/{dataset_id}/export": "commits an audit row for the read",
    "/jobs/{job_id}": "commits an audit row for the read",
    # Browser OAuth redirect legs. An API key never drives these: they are
    # entered from a browser and carry no X-Api-Key.
    "/auth/oauth/{provider_slug}/login": "browser OAuth leg, not an API-key path",
    "/auth/oauth/{provider_slug}/callback": "browser OAuth leg, not an API-key path",
}


def _get_routes_with_write_markers() -> dict[str, set[str]]:
    """GET routes whose handler source shows a write guard or a commit.

    Source inspection, one level deep, same shape and same limits as
    test_rule1_structural.py: a write reached through a service helper is
    invisible here. It is a tripwire for the obvious cases, not a proof.
    """
    import inspect

    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import app

    found: dict[str, set[str]] = {}
    for ctx in iter_route_contexts(app.routes):
        route = ctx.route
        if not isinstance(route, APIRoute) or "GET" not in (route.methods or set()):
            continue
        fn = route.endpoint
        while hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        try:
            source = inspect.getsource(fn)
        except (OSError, TypeError):  # pragma: no cover - defensive
            continue
        markers = set()
        if "check_dataset_write_access" in source:
            markers.add("write_guard")
        if "db.commit(" in source or "session.commit(" in source:
            markers.add("commit")
        if markers:
            found.setdefault(ctx.path, set()).update(markers)
    return found


def test_every_writing_get_route_is_classified():
    """A GET that writes has to be named, in one bucket or the other.

    The whole method rule rests on GET being safe. It mostly is, and where it
    is not — `?refresh=true` on the validate route recomputes the quality score
    with a full table scan and persists it — the method check is the only place
    that can refuse it, because `check_dataset_write_access` sees the owner
    identity the key resolved to and cannot tell a read_only key apart.
    """
    from app.modules.auth.dependencies import _READ_ONLY_KEY_WRITING_GET_ROUTES

    found = set(_get_routes_with_write_markers())
    classified = set(_READ_ONLY_KEY_WRITING_GET_ROUTES) | set(
        _BENIGN_WRITING_GET_ROUTES
    )

    unclassified = found - classified
    assert not unclassified, (
        "these GET routes write or gate on write access and are classified "
        "neither as read-only-refused nor as benign; decide which, in "
        f"_READ_ONLY_KEY_WRITING_GET_ROUTES or _BENIGN_WRITING_GET_ROUTES: "
        f"{sorted(unclassified)}"
    )

    stale = classified - found
    assert not stale, (
        f"classified GET routes that no longer write; drop them: {sorted(stale)}"
    )


@pytest.mark.anyio
async def test_read_only_key_is_refused_on_the_writing_get_variant(
    client: AsyncClient, test_db_session
):
    """?refresh=true persists a recomputed quality score."""
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers, scope="read_only"))["key"]
    admin = await _get_admin(client, headers)
    dataset = await create_dataset(
        test_db_session, created_by=admin, name="Scope Validate"
    )

    resp = await client.get(
        f"/datasets/{dataset.id}/validate/",
        params={"refresh": "true"},
        headers={"X-Api-Key": raw_key},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "This API key is read-only"


@pytest.mark.anyio
async def test_read_only_key_still_reads_the_cached_validation(
    client: AsyncClient, test_db_session
):
    """The paired control: only the write variant is refused, so the ordinary
    read of the same route is untouched."""
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers, scope="read_only"))["key"]
    admin = await _get_admin(client, headers)
    dataset = await create_dataset(
        test_db_session, created_by=admin, name="Scope Validate Cached"
    )

    resp = await client.get(
        f"/datasets/{dataset.id}/validate/", headers={"X-Api-Key": raw_key}
    )
    assert resp.status_code == 200


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", "", "maybe"])
def test_a_write_triggering_query_value_fails_closed(value):
    assert (
        _read_only_key_may_call(
            "GET", "/datasets/{dataset_id}/validate/", {"refresh": value}
        )
        is False
    )


@pytest.mark.parametrize("value", ["false", "0", "off", "no", "F", " False "])
def test_an_explicitly_false_query_value_still_reads(value):
    assert (
        _read_only_key_may_call(
            "GET", "/datasets/{dataset_id}/validate/", {"refresh": value}
        )
        is True
    )


def test_the_stac_search_carve_out_is_required_by_the_acceptance_criteria():
    """ "That key can ... hit OGC/STAC endpoints" is an acceptance criterion,
    and POST /stac/search is the standard's JSON-body search surface."""
    assert _read_only_key_may_call("POST", "/stac/search") is True
    assert _read_only_key_may_call("DELETE", "/stac/search") is False
