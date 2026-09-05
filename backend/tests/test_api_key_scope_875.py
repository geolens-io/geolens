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
    _query_key_may_authenticate,
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
    pre-0032 row by clearing the column to its default."""
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


# Exemptions for routes that do not exist yet. Everything NOT listed here has
# to resolve in the live route table, which is what makes the spelling of a
# real entry verifiable instead of self-asserted.
#
# fix(#875 codex r2): the original entries were spelled `/api/query/`. The app
# sets `root_path="/api"` and a route template never includes an ASGI
# root_path, so those could never match — and because the check fails closed,
# a read_only key would have been refused on the one endpoint the maintainer
# decision says it may call, silently.
#
# feat(#565): POST /query/ is mounted now, so its pair moved out of here and
# under the live resolution check below. Empty until the next pre-announced
# carve-out.
_PENDING_EXEMPT_ROUTES: frozenset[tuple[str, str]] = frozenset()


def _mounted_route_pairs() -> set[tuple[str, str]]:
    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import app

    return {
        (method, ctx.path)
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.route, APIRoute)
        for method in (ctx.route.methods or set())
    }


def test_no_exemption_carries_the_root_path_prefix():
    """The bug class that shipped: an exemption spelled with `/api`.

    `root_path="/api"` is set on the app and starlette strips it before
    matching, so no route template ever begins with it. An entry that does can
    never match, and the check fails closed, so it would defeat the carve-out
    without failing anything.
    """
    from app.api.main import app

    root = app.root_path
    assert root, "root_path is what makes this test meaningful"
    offenders = sorted(
        pair for pair in _READ_ONLY_KEY_EXEMPT_ROUTES if pair[1].startswith(root + "/")
    )
    assert not offenders, (
        f"route templates never include the ASGI root_path {root!r}; "
        f"these entries can never match: {offenders}"
    )


def test_every_live_exemption_resolves_in_the_route_table():
    """A non-pending exemption must name a route that actually exists.

    This is the assertion the old test lacked: it compared the module's
    literal against the same literal written out again, so it passed whatever
    the string said.
    """
    mounted = _mounted_route_pairs()
    live = _READ_ONLY_KEY_EXEMPT_ROUTES - _PENDING_EXEMPT_ROUTES
    unresolved = sorted(pair for pair in live if pair not in mounted)
    assert not unresolved, (
        "exempted routes that do not exist; fix the spelling or add them to "
        f"_PENDING_EXEMPT_ROUTES with the issue that will land them: {unresolved}"
    )
    assert live, "at least one exemption should be live, or this proves nothing"


def test_pending_exemptions_are_still_pending():
    """When #565 lands, this fails and forces the entry to be verified.

    Moving it out of the pending list is what puts it under the resolution
    check above, which is the only place the real template gets confirmed.
    """
    mounted = _mounted_route_pairs()
    landed = sorted(pair for pair in _PENDING_EXEMPT_ROUTES if pair in mounted)
    assert not landed, (
        "these routes now exist; drop them from _PENDING_EXEMPT_ROUTES so the "
        f"resolution check covers them: {landed}"
    )
    assert _PENDING_EXEMPT_ROUTES <= _READ_ONLY_KEY_EXEMPT_ROUTES


def test_the_carve_out_is_a_named_method_and_route():
    """Decided in #875 and #565: a read_only key MAY call the SELECT-only
    sandbox endpoint, because it is a read. The exemption is an exact
    (method, route template) pair so nothing inherits it by resembling one."""
    assert _READ_ONLY_KEY_EXEMPT_ROUTES == frozenset(
        {
            ("POST", "/query/"),
            ("POST", "/query"),
            ("POST", "/stac/search"),
        }
    )
    # Driven from the ROUTE TABLE rather than from a literal: this pair is
    # mounted, so True here means the real endpoint is reachable.
    assert ("POST", "/stac/search") in _mounted_route_pairs()
    assert _read_only_key_may_call("POST", "/stac/search") is True
    # A neighbour that merely looks like it inherits nothing.
    assert _read_only_key_may_call("POST", "/query/run") is False
    # The dead spelling this fix removed must stay dead.
    assert _read_only_key_may_call("POST", "/api/query/") is False
    # Exempting the PATH would have carried a future destructive method with
    # it; the pair is what stops that.
    assert _read_only_key_may_call("DELETE", "/query/") is False
    assert _read_only_key_may_call("PUT", "/query/") is False
    assert _read_only_key_may_call("DELETE", "/stac/search") is False


def test_an_unresolvable_route_fails_closed():
    """When Starlette cannot give a template the value is a placeholder, which
    is in no exemption set."""
    assert _read_only_key_may_call("POST", "<unmatched-route>") is False


def test_565_route_is_mounted_in_both_shapes():
    """feat(#565): the carve-out is live. Both exempted templates resolve.

    Replaces the pre-landing ``test_565_route_is_not_mounted_yet`` hook, per
    its own instructions. The trailing-slash form is the canonical
    registration; the bare form is ROUTE-01's hidden alias.
    """
    mounted = _mounted_route_pairs()
    assert ("POST", "/query/") in mounted
    assert ("POST", "/query") in mounted


@pytest.mark.anyio
async def test_read_only_key_carve_out_works_in_both_directions(
    client: AsyncClient, test_db_session
):
    """feat(#565): the live assertion the pre-landing hook demanded.

    A read_only key SUCCEEDS on POST /query/ (a read in POST clothing), and
    the very same key still gets 403 on another POST — so the carve-out is the
    named route, not a general write path for read-only credentials.
    """
    from sqlalchemy import text

    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    admin_id = await _get_admin(client, headers)
    raw_key = (await _mint(client, headers, scope="read_only"))["key"]

    tbl = f"scope565_{uuid.uuid4().hex[:8]}"
    await test_db_session.execute(text(f"CREATE TABLE data.{tbl} (gid int)"))
    await test_db_session.execute(text(f"INSERT INTO data.{tbl} VALUES (7)"))
    await test_db_session.commit()
    await create_dataset(test_db_session, created_by=admin_id, table_name=tbl)

    resp = await client.post(
        "/query/",
        json={"sql": f"SELECT gid FROM data.{tbl}", "restrict_tables": [tbl]},
        headers={"X-Api-Key": raw_key},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"] == [[7]]

    refused = await client.post(
        "/auth/api-keys/",
        json={"name": "Still refused"},
        headers={"X-Api-Key": raw_key},
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "This API key is read-only"


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
    assert ("POST", "/stac/search") in _mounted_route_pairs()
    assert _read_only_key_may_call("POST", "/stac/search") is True
    assert _read_only_key_may_call("DELETE", "/stac/search") is False


# ---------------------------------------------------------------------------
# fix(#1845): the deprecated ?api_key= transport carries reads only
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_full_key_still_reads_through_the_query_lane(client: AsyncClient):
    """The control. The lane exists for clients that cannot set headers, and
    every one of them issues a GET."""
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers))["key"]

    assert (await client.get(f"/auth/me/?api_key={raw_key}")).status_code == 200

    listing = await client.get("/collections", params={"api_key": raw_key})
    assert listing.status_code == 200


@pytest.mark.anyio
async def test_a_full_key_cannot_mint_another_key_through_the_query_lane(
    client: AsyncClient,
):
    """A URL-borne credential minting a fresh credential is the sharpest shape
    of the finding: the leaked value outlives its own rotation."""
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers))["key"]

    before = len((await client.get("/auth/api-keys/", headers=headers)).json()["items"])

    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Minted From A URL"},
        params={"api_key": raw_key},
    )
    assert resp.status_code == 401, resp.text

    after = (await client.get("/auth/api-keys/", headers=headers)).json()["items"]
    assert len(after) == before
    assert "Minted From A URL" not in {item["name"] for item in after}


@pytest.mark.anyio
async def test_a_full_key_cannot_delete_through_the_query_lane(client: AsyncClient):
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    victim = await _mint(client, headers)
    raw_key = (await _mint(client, headers))["key"]

    resp = await client.delete(
        f"/auth/api-keys/{victim['id']}", params={"api_key": raw_key}
    )
    assert resp.status_code == 401, resp.text

    listing = await client.get("/auth/api-keys/", headers=headers)
    assert victim["id"] in {item["id"] for item in listing.json()["items"]}


@pytest.mark.anyio
async def test_a_full_key_cannot_patch_through_the_query_lane(
    client: AsyncClient, test_db_session
):
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers))["key"]
    admin = await _get_admin(client, headers)
    dataset = await create_dataset(
        test_db_session, created_by=admin, name="Query Lane Patch"
    )

    resp = await client.patch(
        f"/datasets/{dataset.id}",
        json={"title": "Renamed From A URL"},
        params={"api_key": raw_key},
    )
    assert resp.status_code == 401, resp.text

    unchanged = await client.get(f"/datasets/{dataset.id}", headers=headers)
    assert unchanged.json()["title"] != "Renamed From A URL"


@pytest.mark.anyio
async def test_the_same_key_still_patches_through_the_header(
    client: AsyncClient, test_db_session
):
    """The paired control: the refusal is the transport, not the key and not
    the route. Header clients see no change at all."""
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers))["key"]
    admin = await _get_admin(client, headers)
    dataset = await create_dataset(
        test_db_session, created_by=admin, name="Header Lane Patch"
    )

    resp = await client.patch(
        f"/datasets/{dataset.id}",
        json={"title": "Renamed From A Header"},
        headers={"X-Api-Key": raw_key},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Renamed From A Header"


@pytest.mark.anyio
async def test_a_refused_query_key_answers_as_if_it_were_absent(client: AsyncClient):
    """Treated as absent, not as a distinct refusal.

    A dedicated error would tell whoever picked the URL out of a log that the
    value in it is a live key. The anonymous answer for the same request is
    what they get instead.
    """
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers))["key"]

    with_key = await client.post(
        "/auth/api-keys/", json={"name": "X"}, params={"api_key": raw_key}
    )
    without_key = await client.post("/auth/api-keys/", json={"name": "X"})
    assert with_key.status_code == without_key.status_code
    assert with_key.json() == without_key.json()

    junk = await client.post(
        "/auth/api-keys/", json={"name": "X"}, params={"api_key": "not-a-key"}
    )
    assert junk.status_code == without_key.status_code


# ---------------------------------------------------------------------------
# The transport gate, walked against the live route table
# ---------------------------------------------------------------------------


def test_no_mutating_route_in_the_table_accepts_a_url_borne_key():
    """The gate #875 got for scopes, applied to the transport.

    Walks every mounted (method, path) pair rather than naming endpoints, so a
    new mutation route cannot quietly join the lane by being added later.
    """
    accepted = {
        (method, path)
        for method, path in _mounted_route_pairs()
        if method not in ("GET", "HEAD", "OPTIONS")
        and _query_key_may_authenticate(method, path)
    }
    assert not accepted, sorted(accepted)


def test_the_query_lane_does_not_inherit_the_read_only_scope_exemptions():
    """``_READ_ONLY_KEY_EXEMPT_ROUTES`` is about what a scoped key may do; this
    is about what a credential written into a URL may do. The two POSTs there
    are reads an owner chose to make with a credential they control, and the
    clients this lane exists for issue GETs, so the exemption stops here."""
    assert _READ_ONLY_KEY_EXEMPT_ROUTES
    for method, path in _READ_ONLY_KEY_EXEMPT_ROUTES:
        assert _read_only_key_may_call(method, path) is True
        assert _query_key_may_authenticate(method, path) is False


def test_the_query_lane_reuses_the_writing_get_classification():
    """One definition of "this GET is really a write", not two."""
    from app.modules.auth.dependencies import _READ_ONLY_KEY_WRITING_GET_ROUTES

    assert _READ_ONLY_KEY_WRITING_GET_ROUTES
    for route, trigger in _READ_ONLY_KEY_WRITING_GET_ROUTES.items():
        assert _query_key_may_authenticate("GET", route, {trigger: "true"}) is False
        assert _query_key_may_authenticate("GET", route, {}) is True


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_safe_methods_still_pass_the_transport_gate(method: str):
    assert _query_key_may_authenticate(method, "/datasets/") is True


def test_an_unresolvable_route_fails_closed_on_the_transport_gate():
    """Same fail-closed shape as the scope gate: an unmatched template is in no
    exemption list, and a mutation on one is refused."""
    assert _query_key_may_authenticate("POST", "<unmatched-route>") is False
    assert _query_key_may_authenticate("GET", "<unmatched-route>") is True


# ---------------------------------------------------------------------------
# fix(#1845): the refusal warning is throttled, not one line per request
# ---------------------------------------------------------------------------


@pytest.fixture
def _clean_query_lane_log_state():
    from app.modules.auth import dependencies

    dependencies._query_lane_log_last.clear()
    yield dependencies
    dependencies._query_lane_log_last.clear()


def test_the_refusal_warning_is_written_once_per_route_per_interval(
    _clean_query_lane_log_state,
):
    """An anonymous caller decides how often the refusal path runs, so an
    unthrottled warning would let whoever holds the URL choose how many log
    lines an operator stores."""
    deps = _clean_query_lane_log_state

    assert deps._should_log_query_lane_refusal("/datasets/") is True
    assert deps._should_log_query_lane_refusal("/datasets/") is False
    assert deps._should_log_query_lane_refusal("/datasets/") is False

    # A different route is its own budget: the volume is bounded by the route
    # table, which is fixed at deploy time.
    assert deps._should_log_query_lane_refusal("/maps/") is True
    assert deps._should_log_query_lane_refusal("/maps/") is False


def test_the_refusal_warning_resumes_after_the_interval(
    _clean_query_lane_log_state, monkeypatch
):
    """Throttled, not silenced: a client still stuck on the query lane keeps
    showing up in the log."""
    deps = _clean_query_lane_log_state

    clock = {"now": 1_000.0}
    monkeypatch.setattr(deps, "monotonic", lambda: clock["now"])

    assert deps._should_log_query_lane_refusal("/datasets/") is True
    clock["now"] += deps._QUERY_LANE_LOG_INTERVAL_SECONDS - 0.01
    assert deps._should_log_query_lane_refusal("/datasets/") is False
    clock["now"] += 0.02
    assert deps._should_log_query_lane_refusal("/datasets/") is True


def test_the_throttle_key_space_is_the_route_table(_clean_query_lane_log_state):
    """Keyed by the matched route TEMPLATE, never by anything caller-supplied.

    `_route_template` answers `<unmatched-route>` for anything it cannot
    resolve, so a caller cannot grow this dict by varying a path segment. The
    same reasoning `_route_template`'s own docstring gives for logging it.
    """
    deps = _clean_query_lane_log_state

    for _ in range(50):
        deps._should_log_query_lane_refusal("<unmatched-route>")
    assert set(deps._query_lane_log_last) == {"<unmatched-route>"}


@pytest.mark.anyio
async def test_a_refused_query_key_still_logs_the_first_time(
    client: AsyncClient, _clean_query_lane_log_state
):
    """End to end: the refusal that the throttle governs is still emitted."""
    deps = _clean_query_lane_log_state
    headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    raw_key = (await _mint(client, headers))["key"]

    resp = await client.post(
        "/auth/api-keys/", json={"name": "Throttle Probe"}, params={"api_key": raw_key}
    )
    assert resp.status_code == 401, resp.text
    assert set(deps._query_lane_log_last), (
        "the refusal did not reach the throttled warning"
    )
    for route in deps._query_lane_log_last:
        assert raw_key not in route
