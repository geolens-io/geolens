"""#1518 structural guard: the optional-identity failure mode is decided, not inherited.

An anonymous-capable endpoint has to answer a question no route decorator asks
it: what happens when the caller DID supply a credential and it does not
resolve — expired, revoked, or mistyped? There are only two answers, and before
#1518 the codebase gave both. ``get_optional_user_or_401`` returned 401 and
reached 8 handlers (the OGC and STAC detail routes, because those were the
routers in scope for fix(#401)); the other 58 took the plain dependency and
silently continued as anonymous, returning 200 and the public subset. The split
was never designed. It was inherited from which router got patched.

The rule is now fail-closed by default: ``get_optional_user`` itself refuses a
supplied-but-unresolvable credential, so every site inherits it, and
``get_optional_user_fail_open`` is the one sanctioned way out. This module is
what stops the split re-forming — it walks the real FastAPI route table and
fails when a handler uses the fail-open dependency without an ALLOWLIST entry
carrying a justification.

Vacuity is the failure mode a test like this dies of, so three separate floors
guard against it:

- ``test_route_walk_sees_the_full_route_table`` pins a route-count floor. On
  fastapi 0.140 ``app.routes`` holds only the ~89 top-level entries while the
  real table has ~486 APIRoute contexts, and a walk that regressed to the lazy
  top level would let every assertion below pass while asserting nothing.
- ``test_the_fail_closed_dependency_is_the_default`` pins a floor on the
  handlers reaching the fail-closed dependency, so a rename that made the
  detection match nothing fails loudly instead of reporting an empty
  (conveniently compliant) fail-open set.
- ``test_the_two_dependencies_actually_differ`` executes both dependencies
  against an unresolvable credential. Without it the allowlist could stay
  exact while the two names had drifted into the same behaviour, which is the
  bug this file exists to prevent, wearing a compliant shape.

The allowlist is asserted exact in both directions, so an entry cannot go stale
when a handler is renamed, guarded differently, or deleted.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

import pytest
from fastapi import HTTPException, Request
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import get_auth_header

ADMIN_USER = settings.geolens_admin_username
ADMIN_PASS = settings.geolens_admin_password.get_secret_value()

# A credential that cannot resolve to anything, in every transport the API
# accepts. Deliberately not a syntactically valid JWT: #1518 is about the
# credential that FAILS to resolve, and the reason it fails must not matter.
UNRESOLVABLE = "not-a-real-credential-1518"


# ---------------------------------------------------------------------------
# The named exceptions to the fail-closed rule
# ---------------------------------------------------------------------------

# Keyed by "<module>.<qualname>", valued by (category, justification). A
# handler here is one where refusing an unresolvable credential is WORSE than
# serving the request anonymously — not one where 401 is merely inconvenient.
# Adding an entry is a review decision; the exact-in-both-directions assertion
# below is what makes it one.
#
# There are exactly two categories, and they are not equivalent:
#
# RECOVERY   — the endpoint's job IS to recover from a dead credential, so the
#              rule cannot apply to it at all without being circular.
# CAPABILITY — the endpoint can be authorized by something other than the
#              caller's identity. The rule is not waived, only RESEQUENCED: the
#              handler must still apply it on the path where no capability
#              authorized the request. ``test_capability_entries_reapply_the_rule``
#              enforces that, so the category is evidence rather than a waiver.
#              Without that test a CAPABILITY label would be a way to opt out of
#              #1518 by writing a word in a dict, which is worse than the 8/58
#              split it replaced, because it would look reviewed.
RECOVERY = "RECOVERY"
CAPABILITY = "CAPABILITY"

FAIL_OPEN_ALLOWLIST: dict[str, tuple[str, str]] = {
    "app.modules.auth.router.logout": (
        RECOVERY,
        "The credential logout is being asked to discard is frequently the one "
        "that expired, so refusing the call because it did not resolve makes "
        "the dead session permanent — the user cannot clear it and the browser "
        "keeps replaying it. The handler is not fail-open in effect: it falls "
        "back to the refresh cookie and then a body token (fix(#1446)) and "
        "raises its own 401 when NOTHING presented resolves, so an entirely "
        "credential-less caller is still refused. See app/modules/auth/router.py.",
    ),
    "app.modules.catalog.features.router.get_features_geojson_z_endpoint": (
        CAPABILITY,
        "Accepts X-Embed-Token as an independent capability (fix(#390)). The "
        "embed branch runs first; reject_unresolvable_credentials is applied on "
        "the `not embed_ok` path, so a stale bearer alongside a VALID embed "
        "token is served and the same bearer alongside an invalid or absent one "
        "is refused.",
    ),
    "app.modules.catalog.maps.router_sharing.get_shared_map_endpoint": (
        CAPABILITY,
        "Accepts X-Embed-Token to widen the layer scope (fix(#394) SH-01). "
        "get_shared_map now reports whether that capability authorized anything, "
        "and the handler applies the rule when it did not. The share token in "
        "the path selects the map but does not vouch for a dead session bearer, "
        "so it is not the capability for this purpose.",
    ),
    "app.processing.tiles.router.get_tile_tokens_batch": (
        CAPABILITY,
        "Accepts X-Embed-Token as a per-dataset fallback (fix(#394) SH-04). The "
        "capability authorizes a SCOPE, so whether it authorized THIS request is "
        "only known after the id loop; the rule is applied after it when nothing "
        "in the batch was authorized by the token.",
    ),
    "app.processing.tiles.router.tile_endpoint": (
        CAPABILITY,
        "Vector tiles are authorized by X-Embed-Token or by a signed template, "
        "neither of which depends on who is asking. Both arms are evaluated in "
        "_authorize_vector_tile_request, which applies the rule once both have "
        "declined.",
    ),
    "app.processing.tiles.router.cluster_tile_endpoint": (
        CAPABILITY,
        "Same capability arms and the same shared decision point as "
        "tile_endpoint (_authorize_vector_tile_request).",
    ),
    "app.processing.tiles.router.raster_tile_proxy": (
        CAPABILITY,
        "Raster tiles are authorized by X-Embed-Token or by a signed template. "
        "The decision is centralised in _resolve_raster_access, reached through "
        "raster_auth_check, which applies the rule on the arm where neither "
        "capability authorized.",
    ),
    "app.processing.tiles.router.raster_auth_check": (
        CAPABILITY,
        "The in-process auth resolver raster_tile_proxy calls, and a mounted "
        "route in its own right. Same decision point (_resolve_raster_access).",
    ),
}


# ---------------------------------------------------------------------------
# Route-table walk
# ---------------------------------------------------------------------------


def _dependency_uses(dependant, target) -> bool:
    """Whether a FastAPI dependency tree calls ``target``.

    Mirrors ``_dependency_uses`` in app/api/main.py, which decides the same
    question for the generated OpenAPI security contract. The two must agree:
    a dependency the schema treats as anonymous-capable and this test treats
    as absent would document one contract and enforce another.
    """
    if dependant.call is target:
        return True
    return any(_dependency_uses(child, target) for child in dependant.dependencies)


@lru_cache(maxsize=1)
def _walk_optional_auth_routes() -> tuple[
    int, dict[str, frozenset[str]], dict[str, str]
]:
    """Walk the flattened route table once.

    Returns ``(api_route_context_count, handlers_by_dependency, paths)``, where
    ``handlers_by_dependency`` maps "fail_closed"/"fail_open" to the set of
    "<module>.<qualname>" handler keys reaching that dependency, and ``paths``
    maps each such key to one representative route path for the failure text.
    Cached so the tests below share one walk.

    The app import stays function-local: at module scope it would run FastAPI
    app assembly during collection even when this file is deselected.
    """
    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import app
    from app.modules.auth.dependencies import (
        get_optional_user,
        get_optional_user_fail_open,
    )

    targets = {
        "fail_closed": get_optional_user,
        "fail_open": get_optional_user_fail_open,
    }
    found: dict[str, set[str]] = {name: set() for name in targets}
    paths: dict[str, str] = {}

    context_count = 0
    for ctx in iter_route_contexts(app.routes):
        route = ctx.route
        if not isinstance(route, APIRoute):
            continue
        context_count += 1
        fn = route.endpoint
        key = f"{fn.__module__}.{fn.__qualname__}"
        for name, target in targets.items():
            if _dependency_uses(route.dependant, target):
                found[name].add(key)
                paths.setdefault(key, ctx.path or route.path)
    return (
        context_count,
        {name: frozenset(keys) for name, keys in found.items()},
        paths,
    )


@pytest.mark.architecture
def test_route_walk_sees_the_full_route_table() -> None:
    """Vacuity guard: the walk must see the flattened table, not the lazy top level.

    ``include_router`` is lazy on fastapi 0.140, so ``app.routes`` alone holds
    ~89 entries while the real table has ~486 APIRoute contexts. If a future
    fastapi change stops ``iter_route_contexts`` flattening, an empty-ish walk
    would satisfy every allowlist assertion below by finding nothing at all.
    """
    context_count, _found, _paths = _walk_optional_auth_routes()
    assert context_count > 200, (
        f"route walk saw only {context_count} APIRoute contexts — expected the "
        "flattened table (>200). fastapi's lazy include_router behavior has "
        "likely changed; fix the walk before trusting anything in this module."
    )


@pytest.mark.architecture
def test_the_fail_closed_dependency_is_the_default() -> None:
    """Vacuity guard: the fail-closed dependency must still be the common case.

    The allowlist test below reports a violation only for handlers it FINDS on
    the fail-open dependency. If the walk stopped matching either dependency —
    a rename, a wrapper inserted between the route and the dependency, a
    changed ``Depends`` shape — it would report an empty set and pass. A floor
    on the fail-closed side makes that failure loud, and pins the #1518
    inversion itself: fail-closed is the default, not the exception.
    """
    _count, found, _paths = _walk_optional_auth_routes()
    assert len(found["fail_closed"]) >= 50, (
        f"only {len(found['fail_closed'])} handlers reach get_optional_user "
        "(expected >=50). Either the dependency was renamed or the route walk "
        "no longer resolves it — fix the detection before trusting the "
        "fail-open allowlist."
    )
    assert len(found["fail_closed"]) > len(found["fail_open"]), (
        "the fail-open exception list has overtaken the fail-closed default. "
        "#1518 exists because the failure mode was decided by accident; if "
        "most anonymous-capable handlers now opt out, the rule is not the "
        "rule and this file is documenting a fiction."
    )


@pytest.mark.architecture
def test_fail_open_handlers_are_allowlisted() -> None:
    """#1518: a handler may only fail open with a reviewed justification.

    Both directions are asserted, so an entry cannot go stale when a handler
    is renamed, moved back to the fail-closed dependency, or deleted.
    """
    _count, found, paths = _walk_optional_auth_routes()
    fail_open = found["fail_open"]

    missing = sorted(fail_open - set(FAIL_OPEN_ALLOWLIST))
    if missing:
        details = "\n".join(f"  {paths.get(key, '?')}\n    {key}" for key in missing)
        pytest.fail(
            "#1518 violation: route handler(s) depend on "
            "get_optional_user_fail_open without an allowlist entry. A "
            "supplied-but-unresolvable credential is silently downgraded to "
            "anonymous there, so the caller gets 200 and the public subset "
            "with no way to tell a broken credential from an empty catalog. "
            "Use get_optional_user (the fail-closed default) — or, if the "
            "endpoint genuinely must serve a caller whose credential is dead, "
            "add it to FAIL_OPEN_ALLOWLIST in this file with the category and "
            "the reason.\n" + details
        )

    stale = sorted(set(FAIL_OPEN_ALLOWLIST) - fail_open)
    assert not stale, (
        "Stale FAIL_OPEN_ALLOWLIST entries — these handlers no longer use "
        "get_optional_user_fail_open, or were renamed or removed. Delete them "
        "so the list stays exact:\n"
        + "\n".join(f"  {key}: {FAIL_OPEN_ALLOWLIST[key][0]}" for key in stale)
    )


@pytest.mark.architecture
def test_every_allowlist_entry_has_a_known_category() -> None:
    """A typo in the category would silently skip the obligation test below."""
    unknown = {
        key: category
        for key, (category, _why) in FAIL_OPEN_ALLOWLIST.items()
        if category not in {RECOVERY, CAPABILITY}
    }
    assert not unknown, (
        f"unknown fail-open categories: {unknown}. Use RECOVERY or CAPABILITY; "
        "an unrecognized one would not be checked by "
        "test_capability_entries_reapply_the_rule."
    )


def _calls_reject_helper(fn: object, *, depth: int = 3) -> bool:
    """Whether ``fn`` reaches a call to ``reject_unresolvable_credentials``.

    Follows calls into functions defined in ``app.`` modules, because the tile
    handlers do not apply the rule inline — the decision is centralised in
    ``_authorize_vector_tile_request`` and ``_resolve_raster_access``, and
    ``raster_tile_proxy`` reaches the latter through ``raster_auth_check``, two
    hops away. A check that only read the handler's own body would report a
    violation for correct code, and the obvious fix for that (matching the name
    anywhere in the module text) would pass for a handler that never calls it.

    Matched as an AST Call rather than a substring so a mention in a comment or
    a docstring cannot satisfy the obligation.
    """
    import ast
    import inspect
    import textwrap

    seen: set[int] = set()

    def visit(target: object, remaining: int) -> bool:
        if remaining < 0 or id(target) in seen:
            return False
        seen.add(id(target))
        unwrapped = _unwrap_callable(target)
        try:
            source = textwrap.dedent(inspect.getsource(unwrapped))
        except (OSError, TypeError):
            return False
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return False

        callees: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name == "reject_unresolvable_credentials":
                return True
            if name:
                callees.append(name)

        module_globals = getattr(
            __import__(unwrapped.__module__, fromlist=["*"]), "__dict__", {}
        )
        for name in callees:
            candidate = module_globals.get(name)
            if candidate is None or not callable(candidate):
                continue
            candidate_module = (
                getattr(_unwrap_callable(candidate), "__module__", "") or ""
            )
            if not candidate_module.startswith("app."):
                continue
            if visit(candidate, remaining - 1):
                return True
        return False

    return visit(fn, depth)


def _unwrap_callable(fn: object) -> object:
    """Strip decorator wrappers (slowapi's ``@limiter`` most importantly).

    Mirrors ``_unwrap`` in tests/test_rule1_structural.py. Reading the wrapper
    instead of the handler is how this scope was under-counted twice: the
    decorated tile routes report the wrapper's tiny body, which mentions none of
    the authorization the real handler performs.
    """
    seen: set[int] = set()
    while hasattr(fn, "__wrapped__") and id(fn) not in seen:
        seen.add(id(fn))
        fn = fn.__wrapped__  # type: ignore[union-attr]
    return fn


@pytest.mark.architecture
def test_capability_entries_reapply_the_rule() -> None:
    """A CAPABILITY entry must still apply the rule where no capability won.

    This is the load-bearing half of the category. RECOVERY genuinely opts out
    of #1518; CAPABILITY only reorders it, and the difference is invisible in
    the allowlist itself. Without this test, "CAPABILITY" would be a word that
    turns the fail-closed rule off — the 8-vs-58 split again, with a comment
    explaining why it is fine.
    """
    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import app

    handlers: dict[str, object] = {}
    for ctx in iter_route_contexts(app.routes):
        route = ctx.route
        if not isinstance(route, APIRoute):
            continue
        fn = route.endpoint
        handlers[f"{fn.__module__}.{fn.__qualname__}"] = fn

    capability_keys = sorted(
        key
        for key, (category, _why) in FAIL_OPEN_ALLOWLIST.items()
        if category == CAPABILITY
    )
    assert capability_keys, (
        "no CAPABILITY entries found — if the category is gone, delete this "
        "test rather than letting it pass by checking nothing."
    )

    missing = []
    for key in capability_keys:
        fn = handlers.get(key)
        if fn is None:
            missing.append(f"{key} (not found in the route table)")
        elif not _calls_reject_helper(fn):
            missing.append(key)

    assert not missing, (
        "CAPABILITY entries that never re-apply the fail-closed rule:\n"
        + "\n".join(f"  {key}" for key in missing)
        + "\n\nA CAPABILITY handler takes get_optional_user_fail_open so it can "
        "evaluate its capability FIRST, not so it can skip the rule. It must "
        "call reject_unresolvable_credentials on the path where no capability "
        "authorized the request, or an unresolvable credential is silently "
        "downgraded to anonymous there — which is #1518."
    )


# ---------------------------------------------------------------------------
# The dependencies themselves
# ---------------------------------------------------------------------------


def _request_with(headers: list[tuple[bytes, bytes]], query: bytes = b"") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "query_string": query,
        }
    )


async def test_the_two_dependencies_actually_differ(test_db_session) -> None:
    """Counterfactual: the allowlist means nothing if both names behave alike.

    Executed rather than inspected, because "calls a different helper" is not
    the property that matters — "answers differently for the same request" is.
    """
    from app.modules.auth.dependencies import (
        get_optional_user,
        get_optional_user_fail_open,
        get_optional_user_no_security_schema,
    )

    credentialed = _request_with([(b"x-api-key", UNRESOLVABLE.encode())])

    with pytest.raises(HTTPException) as excinfo:
        await get_optional_user(credentialed, None, test_db_session)
    assert excinfo.value.status_code == 401

    # The no-schema variant exists to keep bearer security markers off public
    # operations (fix(#430)), NOT to opt out of the failure-mode rule. It
    # delegates, so it must answer identically — a future edit that pointed it
    # at the raw resolver would reintroduce the #1518 split on the STAC public
    # routes without tripping the allowlist above.
    with pytest.raises(HTTPException) as excinfo:
        await get_optional_user_no_security_schema(credentialed, test_db_session)
    assert excinfo.value.status_code == 401

    assert (
        await get_optional_user_fail_open(credentialed, None, test_db_session) is None
    )

    # Both halves: a credential-less caller is anonymous either way. A test
    # that only pinned the 401 would pass against a dependency that had simply
    # broken and refused everything.
    anonymous = _request_with([])
    assert await get_optional_user(anonymous, None, test_db_session) is None
    assert await get_optional_user_fail_open(anonymous, None, test_db_session) is None
    assert (
        await get_optional_user_no_security_schema(anonymous, test_db_session) is None
    )


# ---------------------------------------------------------------------------
# Observable behaviour on a previously fail-open endpoint
# ---------------------------------------------------------------------------


class TestPreviouslyFailOpenEndpoint:
    """``GET /collections`` — the endpoint #1518 measured against the demo.

    It answered 200 for a garbage key before this change, which is the silent
    scope reduction the issue describes: the caller gets the public subset and
    cannot tell it apart from a catalog that holds nothing more.
    """

    async def test_unresolvable_api_key_header_is_refused(self, client: AsyncClient):
        resp = await client.get("/collections", headers={"X-Api-Key": UNRESOLVABLE})
        assert resp.status_code == 401

    async def test_unresolvable_api_key_query_param_is_refused(
        self, client: AsyncClient
    ):
        """The deprecated ?api_key= lane answers the same way (#821, #1518).

        Both transports agreeing is load-bearing: the issue measured them
        against each other first, precisely to rule out a transport bug.
        """
        resp = await client.get(f"/collections?api_key={UNRESOLVABLE}")
        assert resp.status_code == 401

    async def test_unresolvable_bearer_token_is_refused(self, client: AsyncClient):
        resp = await client.get(
            "/collections", headers={"Authorization": f"Bearer {UNRESOLVABLE}"}
        )
        assert resp.status_code == 401

    async def test_a_credentialless_request_still_gets_the_public_subset(
        self, client: AsyncClient
    ):
        """The other half. Without it, an endpoint that had simply broken and
        started refusing everything would pass the three tests above."""
        resp = await client.get("/collections")
        assert resp.status_code == 200
        assert "collections" in resp.json()

    async def test_a_working_credential_still_gets_through(self, client: AsyncClient):
        """The third half: the rule must key on RESOLVABILITY, not on the mere
        presence of a credential."""
        headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
        resp = await client.get("/collections", headers=headers)
        assert resp.status_code == 200


class TestLogoutKeepsWorkingWithADeadAccessToken:
    """The allowlist entry, proven rather than asserted.

    A status-code check alone cannot prove this: logout raises its OWN 401
    when nothing resolves, so a garbage bearer with no other credential
    answers 401 whether or not the exception is in place. The presented
    refresh token is what separates the two — it makes the call succeed under
    the exception and fail without it.
    """

    async def test_a_stale_access_token_can_still_present_a_refresh_token(
        self, client: AsyncClient
    ):
        login = await client.post(
            "/auth/login", data={"username": ADMIN_USER, "password": ADMIN_PASS}
        )
        assert login.status_code == 200
        refresh_token = login.json()["refresh_token"]

        resp = await client.post(
            "/auth/logout/",
            headers={"Authorization": f"Bearer {UNRESOLVABLE}"},
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 204, (
            "logout refused a caller whose access token had died while their "
            "refresh credential was still valid — the #1518 fail-closed rule "
            "reached an endpoint whose job is to recover from exactly that "
            "state. See FAIL_OPEN_ALLOWLIST in this file."
        )

    async def test_logout_still_refuses_a_caller_with_nothing_valid(
        self, client: AsyncClient
    ):
        """The exception is fail-OPEN on the dependency, not unauthenticated.

        Without this half the allowlist entry would read as a hole.
        """
        resp = await client.post(
            "/auth/logout/", headers={"Authorization": f"Bearer {UNRESOLVABLE}"}
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# The CAPABILITY truth table, driven end to end
# ---------------------------------------------------------------------------


class TestCapabilityOutranksADeadCredential:
    """``GET /maps/shared/{token}`` with an embed token — the codex P2 pairing.

    The frontend produces it: ``getSharedMap()`` sends ``X-Embed-Token`` through
    ``apiFetch``, which also attaches whatever bearer the auth store persisted.
    A viewer whose session died last night therefore arrives with a dead bearer
    and a live capability.

    All four rows are here on purpose. Rows 1 and 2 differ only in whether the
    capability is valid, and a change that simply skipped the rule whenever an
    embed header was PRESENT would pass row 1 while silently reopening #1518 —
    that is precisely the header-presence proxy this design rejected. Row 2 is
    what proves the hole was not widened.
    """

    @staticmethod
    async def _setup(client: AsyncClient, admin_auth_header: dict, test_db_session):
        """A map with a private layer, a share link, and a valid embed token."""
        from tests.test_embed_tokens import (
            _create_map_with_layer,
            _create_private_dataset,
        )
        from tests.factories import get_user_id

        user_id = await get_user_id(test_db_session, ADMIN_USER)
        dataset = await _create_private_dataset(test_db_session, created_by=user_id)
        map_obj, _layer = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )

        # The map itself must be public to be shared; its LAYER stays private,
        # which is the whole point — that layer is what the embed token's scope
        # unlocks and what an anonymous caller does not get.
        map_obj.visibility = "public"
        test_db_session.add(map_obj)
        await test_db_session.commit()

        share = await client.post(
            f"/maps/{map_obj.id}/share/", json={}, headers=admin_auth_header
        )
        assert share.status_code in (200, 201), share.text
        share_token = share.json()["token"]

        embed = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/", json={}, headers=admin_auth_header
        )
        assert embed.status_code == 201, embed.text
        return share_token, embed.json()["raw_token"], dataset

    async def test_row1_dead_bearer_with_a_valid_capability_is_served(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The capability authorized the request, so the dead bearer is noise."""
        share_token, embed_token, dataset = await self._setup(
            client, admin_auth_header, test_db_session
        )

        resp = await client.get(
            f"/maps/shared/{share_token}",
            headers={
                "Authorization": f"Bearer {UNRESOLVABLE}",
                "X-Embed-Token": embed_token,
            },
        )
        assert resp.status_code == 200, resp.text
        # Served ON the capability: the scoped private layer is present, which
        # an anonymous caller does not get.
        layer_ids = {layer["dataset_id"] for layer in resp.json()["layers"]}
        assert str(dataset.id) in layer_ids, (
            "the embed token's scoped private layer is missing, so the request "
            "was not actually served on the capability"
        )

    async def test_row2_dead_bearer_with_an_invalid_capability_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """No capability authorized, so the credential really was load-bearing.

        The row that proves this is a resequencing and not a hole. If the
        implementation keyed on the PRESENCE of ``X-Embed-Token`` rather than on
        its validity, this would return 200 and anyone holding a dead API key
        could suppress the 401 with a junk header.
        """
        share_token, _embed_token, _dataset = await self._setup(
            client, admin_auth_header, test_db_session
        )

        resp = await client.get(
            f"/maps/shared/{share_token}",
            headers={
                "Authorization": f"Bearer {UNRESOLVABLE}",
                "X-Embed-Token": "et_not-a-real-embed-token",
            },
        )
        assert resp.status_code == 401, resp.text

    async def test_row2b_dead_bearer_with_no_capability_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The plain #1518 case on a CAPABILITY handler, unchanged by the category."""
        share_token, _embed_token, _dataset = await self._setup(
            client, admin_auth_header, test_db_session
        )

        resp = await client.get(
            f"/maps/shared/{share_token}",
            headers={"Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        assert resp.status_code == 401, resp.text

    async def test_row3_no_bearer_with_a_valid_capability_is_served(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Unchanged behaviour: the embed viewer that never had a session."""
        share_token, embed_token, dataset = await self._setup(
            client, admin_auth_header, test_db_session
        )

        resp = await client.get(
            f"/maps/shared/{share_token}",
            headers={"X-Embed-Token": embed_token},
        )
        assert resp.status_code == 200, resp.text
        layer_ids = {layer["dataset_id"] for layer in resp.json()["layers"]}
        assert str(dataset.id) in layer_ids

    async def test_row4_no_credential_at_all_keeps_the_anonymous_path(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Unchanged behaviour: a credential-less caller still gets the map.

        Without this row a handler that had simply started refusing everything
        would satisfy the two 401 rows above.
        """
        share_token, _embed_token, dataset = await self._setup(
            client, admin_auth_header, test_db_session
        )

        resp = await client.get(f"/maps/shared/{share_token}")
        assert resp.status_code == 200, resp.text
        # ...but without the private layer the capability would have unlocked.
        layer_ids = {layer["dataset_id"] for layer in resp.json()["layers"]}
        assert str(dataset.id) not in layer_ids


class TestCapabilityOnAPublicOnlyTileTokenBatch:
    """``POST /tiles/tokens/`` — the shape the shared-map table cannot see.

    The two endpoints reach the capability by opposite routes. On
    ``/maps/shared/{token}`` the embed scope is resolved unconditionally, so a
    public map still exercises it. Here the embed check lives in the fallback
    arm for a dataset whose NORMAL access was refused, so a batch of public
    datasets never reaches it — ``_enforce_tile_token_access`` simply succeeds.

    A shared map of public datasets is the ordinary embed, so this is the common
    case rather than a corner: the first fix rejected a valid scoped
    ``X-Embed-Token`` there whenever a stale bearer rode along, which is the bug
    this PR exists to remove (codex P2 at ec1332583).
    """

    @staticmethod
    async def _setup(client: AsyncClient, admin_auth_header: dict, test_db_session):
        """A map whose only layer is a PUBLIC published dataset, plus tokens."""
        from tests.factories import create_dataset, get_user_id
        from tests.test_embed_tokens import _create_map_with_layer

        user_id = await get_user_id(test_db_session, ADMIN_USER)
        dataset = await create_dataset(
            test_db_session,
            created_by=user_id,
            name="Public Embed Batch DS",
            visibility="public",
            record_status="published",
            geometry_type="Point",
            feature_count=1,
            column_info=[
                {"name": "gid", "type": "integer"},
                {"name": "geom", "type": "geometry"},
            ],
        )
        map_obj, _layer = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )
        embed = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/", json={}, headers=admin_auth_header
        )
        assert embed.status_code == 201, embed.text
        assert str(dataset.id) in embed.json()["scoped_dataset_ids"]
        return dataset, embed.json()["raw_token"]

    async def test_row1_dead_bearer_with_a_valid_capability_is_served(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The row codex found. Red before the fix: 401 for a valid capability."""
        dataset, embed_token = await self._setup(
            client, admin_auth_header, test_db_session
        )

        resp = await client.post(
            "/tiles/tokens/",
            json={"dataset_ids": [str(dataset.id)]},
            headers={
                "Authorization": f"Bearer {UNRESOLVABLE}",
                "X-Embed-Token": embed_token,
            },
        )
        assert resp.status_code == 200, resp.text
        assert str(dataset.id) in resp.json()["tokens"]

    async def test_row2_dead_bearer_with_an_invalid_capability_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The row that proves the fix did not become "a header was sent"."""
        dataset, _embed_token = await self._setup(
            client, admin_auth_header, test_db_session
        )

        resp = await client.post(
            "/tiles/tokens/",
            json={"dataset_ids": [str(dataset.id)]},
            headers={
                "Authorization": f"Bearer {UNRESOLVABLE}",
                "X-Embed-Token": "et_not-a-real-embed-token",
            },
        )
        assert resp.status_code == 401, resp.text

    async def test_row2b_dead_bearer_with_no_capability_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset, _embed_token = await self._setup(
            client, admin_auth_header, test_db_session
        )

        resp = await client.post(
            "/tiles/tokens/",
            json={"dataset_ids": [str(dataset.id)]},
            headers={"Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        assert resp.status_code == 401, resp.text

    async def test_row3_no_bearer_with_a_valid_capability_is_served(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        dataset, embed_token = await self._setup(
            client, admin_auth_header, test_db_session
        )

        resp = await client.post(
            "/tiles/tokens/",
            json={"dataset_ids": [str(dataset.id)]},
            headers={"X-Embed-Token": embed_token},
        )
        assert resp.status_code == 200, resp.text
        assert str(dataset.id) in resp.json()["tokens"]

    async def test_row4_no_credential_at_all_keeps_the_anonymous_path(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Public datasets are mintable anonymously; that must not change."""
        dataset, _embed_token = await self._setup(
            client, admin_auth_header, test_db_session
        )

        resp = await client.post(
            "/tiles/tokens/", json={"dataset_ids": [str(dataset.id)]}
        )
        assert resp.status_code == 200, resp.text
        assert str(dataset.id) in resp.json()["tokens"]


# ---------------------------------------------------------------------------
# The published contract
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _schema() -> dict:
    from app.api.main import app

    return app.openapi()


def _optional_auth_operations() -> dict[str, dict]:
    """Every schema operation whose route reaches an optional-auth dependency."""
    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import _dependency_uses, _route_operation, app
    from app.modules.auth.dependencies import (
        get_optional_user,
        get_optional_user_fail_open,
        get_optional_user_no_security_schema,
    )

    targets = {
        get_optional_user,
        get_optional_user_fail_open,
        get_optional_user_no_security_schema,
    }
    schema = _schema()
    found: dict[str, dict] = {}
    for ctx in iter_route_contexts(app.routes):
        route = ctx.route
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        if not _dependency_uses(route.dependant, targets):
            continue
        for method in route.methods or ():
            operation = _route_operation(schema, ctx, method)
            if operation is not None:
                found[f"{method} {ctx.path or route.path}"] = operation
    return found


@pytest.mark.architecture
def test_optional_auth_operations_document_the_401() -> None:
    """#1518 made 401 normal runtime behaviour; the schema has to say so.

    SDK error unions are generated from these blocks, so an undocumented 401 is
    one a typed client cannot represent (codex P2 on #1524).
    """
    operations = _optional_auth_operations()
    assert len(operations) >= 50, (
        f"only {len(operations)} optional-auth operations found — the walk or "
        "the dependency detection has broken, and an empty set would satisfy "
        "the assertion below by checking nothing."
    )

    missing = sorted(
        key for key, op in operations.items() if "401" not in op.get("responses", {})
    )
    assert not missing, (
        "optional-auth operations that can return 401 but do not document it:\n"
        + "\n".join(f"  {key}" for key in missing)
    )


@pytest.mark.architecture
def test_no_security_schema_ops_get_401_without_security() -> None:
    """Documenting the status must not stamp auth back onto public operations.

    ``get_optional_user_no_security_schema`` exists so genuinely public STAC
    operations carry no bearer markers in generated clients (fix(#430)). A 401
    RESPONSE is not a security REQUIREMENT, and this is the test that keeps the
    two from being conflated — without it, moving the 401 into
    ``_normalize_security_contract`` (the obvious place) would quietly
    reintroduce the markers #430 removed.
    """
    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import _dependency_uses, _route_operation, app
    from app.modules.auth.dependencies import (
        get_optional_user_no_security_schema,
    )

    schema = _schema()
    checked = 0
    for ctx in iter_route_contexts(app.routes):
        route = ctx.route
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        if not _dependency_uses(
            route.dependant, {get_optional_user_no_security_schema}
        ):
            continue
        for method in route.methods or ():
            operation = _route_operation(schema, ctx, method)
            if operation is None:
                continue
            checked += 1
            path = ctx.path or route.path
            assert "401" in operation.get("responses", {}), (
                f"{method} {path} can 401 but does not document it"
            )
            for alternative in operation.get("security", []):
                assert not any(
                    key in alternative
                    for key in ("OAuth2PasswordBearer", "ApiKeyHeader", "ApiKeyQuery")
                ), (
                    f"{method} {path} gained a credential security requirement. "
                    "The 401 response must be documented WITHOUT marking these "
                    "public operations as authenticated (fix(#430))."
                )

    assert checked > 0, (
        "no get_optional_user_no_security_schema operations found — this test "
        "would pass by checking nothing."
    )


class TestEveryNoCapabilityExitAppliesTheRule:
    """One row per no-capability EXIT CLASS, not per handler (codex P2 round 3).

    The first two rounds applied the rule at one exit point per handler and
    tested the success and plain-invalid rows, so whole classes of exit went
    unexamined: a capability that DECLINED, a signed template that was missing
    or wrong, and a resource that was absent or revoked. Each of those answered
    403/404/410 to a caller whose credential was dead, so a refresh-on-401
    client never fired — the silent-credential-failure #1518 exists to remove,
    wearing a resource-status code.

    The classes, and the handler each is exercised through:

    1. capability DECLINED        — invalid embed token          (vector tiles, raster tiles, features)
    2. signed template MISSING    — non-public tile, no sig       (vector tiles)
    3. signed template INVALID    — non-public tile, bad sig      (vector tiles)
    4. resource ABSENT            — no such dataset               (vector tiles, raster tiles, features)
    5. resource REVOKED           — expired share link            (EXEMPT, see below)
    6. dataset SHAPE refused      — cluster tiles on a non-point  (cluster tiles)

    Round 4 filled in the two handlers the table named but never exercised —
    the class-1 row claimed "tiles" while only features and the shared map were
    asserted, and no row touched the raster routes at all even though the
    raster proxy is one of the two sites codex reported. Class 4 on the vector
    tile path and class 6 were found by walking the exits: both ran BEFORE
    ``_authorize_vector_tile_request``, so the rule never reached them, and the
    raster sibling already answered 401 for the same request shape.

    Round 4 also took the shared map back OUT of classes 4 and 5, which round 3
    had put in. The test for an exit has to ask whether a credential could have
    changed that exit's answer, and on a missing or revoked share link it could
    not: the lookup takes no user at all. Turning those into 401s refused a
    caller for a failure that was not theirs and cost the viewer the one error
    message that tells them what to do about it. The rule still applies to that
    endpoint's SUCCESS arm, where identity really does decide the response, and
    ``TestCapabilityOutranksADeadCredential`` row 2b is what keeps the exemption
    from widening into a waiver.

    Every row sends a dead bearer, because that is the only caller whose answer
    changes. A caller with no credential still gets the resource answer, which
    the paired assertions below pin so the rule cannot be mistaken for a blanket
    refusal.

    The 401s assert ``WWW-Authenticate: Bearer`` as well as the status. That
    header is what makes the answer actionable — it is the rest of the API's
    contract for "your credential did not resolve", and a 401 without it reads
    to a client as an unrecoverable refusal rather than a reason to refresh.
    """

    @staticmethod
    async def _public_dataset(test_db_session):
        from tests.factories import create_dataset, get_user_id

        user_id = await get_user_id(test_db_session, ADMIN_USER)
        return await create_dataset(
            test_db_session,
            created_by=user_id,
            name="Exit Class DS",
            visibility="public",
            record_status="published",
            geometry_type="Point",
            feature_count=1,
            column_info=[
                {"name": "gid", "type": "integer"},
                {"name": "geom", "type": "geometry"},
            ],
        )

    @staticmethod
    async def _public_raster_dataset(test_db_session):
        """A raster dataset complete enough for _resolve_raster_meta to succeed.

        The asset row matters: without it the resolver 404s "No raster asset"
        and the class-1 rows would pass on the class-4 exit instead of the one
        they name.
        """
        from tests.factories import create_raster_dataset, get_user_id

        user_id = await get_user_id(test_db_session, ADMIN_USER)
        return await create_raster_dataset(
            test_db_session,
            created_by=user_id,
            name="Exit Class Raster DS",
            visibility="public",
            record_status="published",
            create_raster_asset=True,
        )

    @staticmethod
    def _assert_credential_refusal(resp) -> None:
        """A 401 that a refresh-on-401 client can act on."""
        assert resp.status_code == 401, resp.text
        assert resp.headers.get("WWW-Authenticate") == "Bearer", (
            "the credential refusal must carry the challenge header the rest of "
            f"the API sends; got {dict(resp.headers)}"
        )

    # -- class 1: the capability declined -----------------------------------

    async def test_class1_features_invalid_embed_token(
        self, client: AsyncClient, test_db_session
    ):
        dataset = await self._public_dataset(test_db_session)
        resp = await client.get(
            f"/datasets/{dataset.id}/features.geojson",
            headers={
                "Authorization": f"Bearer {UNRESOLVABLE}",
                "X-Embed-Token": "et_not-a-real-token",
            },
        )
        assert resp.status_code == 401, resp.text

    async def test_class1_shared_map_invalid_embed_token_on_missing_link(
        self, client: AsyncClient
    ):
        """Declined capability AND an absent resource: the RESOURCE answer wins.

        The share token is a capability that addresses the resource, and no
        credential could have made this link exist, so there is nothing for the
        rule to refuse. See the handler comment in router_sharing.py, and
        test_row2b_dead_bearer_with_no_capability_is_refused for the arm where a
        dead bearer on a LIVE link still earns the 401.
        """
        resp = await client.get(
            "/maps/shared/no-such-share-token",
            headers={
                "Authorization": f"Bearer {UNRESOLVABLE}",
                "X-Embed-Token": "et_not-a-real-token",
            },
        )
        assert resp.status_code == 404, resp.text

    async def test_class1_vector_tile_invalid_embed_token(
        self, client: AsyncClient, test_db_session
    ):
        """The tile half of class 1, which the table named but never asserted."""
        dataset = await self._public_dataset(test_db_session)
        headers = {"X-Embed-Token": "et_not-a-real-token"}

        # Credential-less: the declined capability is still a 403 about the token.
        anon = await client.get(
            f"/tiles/data.{dataset.table_name}/10/0/0.pbf", headers=headers
        )
        assert anon.status_code == 403, anon.text

        resp = await client.get(
            f"/tiles/data.{dataset.table_name}/10/0/0.pbf",
            headers={**headers, "Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        self._assert_credential_refusal(resp)

    async def test_class1_raster_proxy_invalid_embed_token(
        self, client: AsyncClient, test_db_session
    ):
        """One of the two sites codex reported, and the one no row reached."""
        dataset = await self._public_raster_dataset(test_db_session)
        headers = {"X-Embed-Token": "et_not-a-real-token"}

        anon = await client.get(
            f"/tiles/raster-proxy/{dataset.id}/0/0/0.png", headers=headers
        )
        assert anon.status_code == 403, anon.text

        resp = await client.get(
            f"/tiles/raster-proxy/{dataset.id}/0/0/0.png",
            headers={**headers, "Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        self._assert_credential_refusal(resp)

    async def test_class1_raster_auth_check_invalid_embed_token(
        self, client: AsyncClient, test_db_session
    ):
        """The mounted auth-check route is its own allowlist entry, so its own row."""
        dataset = await self._public_raster_dataset(test_db_session)
        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers={
                "X-Embed-Token": "et_not-a-real-token",
                "Authorization": f"Bearer {UNRESOLVABLE}",
            },
        )
        self._assert_credential_refusal(resp)

    # -- classes 2 and 3: the signed template ------------------------------

    async def test_class2_vector_tile_non_public_without_a_signature(
        self, client: AsyncClient, test_db_session
    ):
        """A non-public tile with no signed template: 403 before, 401 now."""
        from tests.factories import create_dataset, get_user_id

        user_id = await get_user_id(test_db_session, ADMIN_USER)
        dataset = await create_dataset(
            test_db_session,
            created_by=user_id,
            name="Exit Class Private DS",
            visibility="private",
            record_status="published",
            geometry_type="Point",
            feature_count=1,
        )
        resp = await client.get(
            f"/tiles/data.{dataset.table_name}/10/0/0.pbf",
            headers={"Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        assert resp.status_code == 401, resp.text

    async def test_class3_vector_tile_non_public_with_a_bad_signature(
        self, client: AsyncClient, test_db_session
    ):
        from tests.factories import create_dataset, get_user_id

        user_id = await get_user_id(test_db_session, ADMIN_USER)
        dataset = await create_dataset(
            test_db_session,
            created_by=user_id,
            name="Exit Class Private DS 2",
            visibility="private",
            record_status="published",
            geometry_type="Point",
            feature_count=1,
        )
        resp = await client.get(
            f"/tiles/data.{dataset.table_name}/10/0/0.pbf"
            f"?sig=deadbeef&exp=9999999999&scope={dataset.table_name}",
            headers={"Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        assert resp.status_code == 401, resp.text

    # -- class 4: the resource is absent ------------------------------------

    async def test_class4_features_absent_dataset(self, client: AsyncClient):
        """Not named by codex — found by walking the exits (fourth site)."""
        import uuid as _uuid

        resp = await client.get(
            f"/datasets/{_uuid.uuid4()}/features.geojson",
            headers={"Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        assert resp.status_code == 401, resp.text

    async def test_class4_shared_map_absent_link(self, client: AsyncClient):
        """The exemption, pinned so it cannot be flipped back without argument.

        An absent share link answers 404 to every caller alike, so the credential
        rule has nothing to add. What keeps this honest is that the SAME endpoint
        does refuse a dead bearer on a live link (row 2b).
        """
        resp = await client.get(
            "/maps/shared/no-such-share-token",
            headers={"Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        assert resp.status_code == 404, resp.text

    async def test_class4_vector_tile_absent_dataset(self, client: AsyncClient):
        """Not named by codex — the tile path resolves the table BEFORE authorizing.

        The URL carries a table name, not a dataset id, so the capability arms
        cannot run until the lookup succeeds and the lookup's own 404 was reached
        with the rule never applied. The raster route already answered 401 for
        the same request shape, which is the per-router split #1518 removes.
        """
        table = f"no_such_tile_table_{uuid.uuid4().hex[:8]}"

        anon = await client.get(f"/tiles/data.{table}/10/0/0.pbf")
        assert anon.status_code == 404, anon.text

        resp = await client.get(
            f"/tiles/data.{table}/10/0/0.pbf",
            headers={"Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        self._assert_credential_refusal(resp)

    async def test_class4_cluster_tile_absent_dataset(self, client: AsyncClient):
        """cluster_tile_endpoint is a separate route on the same lookup."""
        table = f"no_such_cluster_table_{uuid.uuid4().hex[:8]}"

        anon = await client.get(f"/tiles/clusters/data.{table}/10/0/0.pbf")
        assert anon.status_code == 404, anon.text

        resp = await client.get(
            f"/tiles/clusters/data.{table}/10/0/0.pbf",
            headers={"Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        self._assert_credential_refusal(resp)

    async def test_class4_raster_tile_absent_dataset(self, client: AsyncClient):
        """The raster half of class 4, on both mounted routes."""
        absent = uuid.uuid4()

        anon = await client.get(f"/tiles/raster-proxy/{absent}/0/0/0.png")
        assert anon.status_code == 404, anon.text

        proxy = await client.get(
            f"/tiles/raster-proxy/{absent}/0/0/0.png",
            headers={"Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        self._assert_credential_refusal(proxy)

        auth_check = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(absent)},
            headers={"Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        self._assert_credential_refusal(auth_check)

    # -- class 5: the resource is revoked -----------------------------------

    async def test_class5_shared_map_revoked_link(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        from tests.factories import get_user_id
        from tests.test_embed_tokens import _create_map_with_layer

        dataset = await self._public_dataset(test_db_session)
        user_id = await get_user_id(test_db_session, ADMIN_USER)
        map_obj, _layer = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )
        map_obj.visibility = "public"
        test_db_session.add(map_obj)
        await test_db_session.commit()

        share = await client.post(
            f"/maps/{map_obj.id}/share/", json={}, headers=admin_auth_header
        )
        assert share.status_code in (200, 201), share.text
        token = share.json()["token"]

        revoke = await client.delete(
            f"/maps/{map_obj.id}/share/", headers=admin_auth_header
        )
        assert revoke.status_code == 204, revoke.text

        # A credential-less caller learns the link is gone...
        anon = await client.get(f"/maps/shared/{token}")
        assert anon.status_code in (404, 410), anon.text

        # ...and so does a caller whose credential happens to be dead. The 410
        # is the answer the viewer can act on, and the frontend has a card for
        # it (PublicViewerPage.tsx:84); a 401 would replace "ask the owner for a
        # new link" with "your session expired", which is both wrong and, with
        # useSharedMap's retry: false, final.
        resp = await client.get(
            f"/maps/shared/{token}",
            headers={"Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        assert resp.status_code == anon.status_code, resp.text

    # -- class 6: the dataset is the wrong shape for the route ---------------

    async def test_class6_cluster_tile_non_point_dataset(
        self, client: AsyncClient, test_db_session
    ):
        """Also not named by codex, and the reason it is NOT a request-shape 400.

        The 400s this suite deliberately leaves alone — a bad tile format, an
        out-of-range zoom, a sigma of zero — are properties of the REQUEST and
        answer every caller identically. "This dataset is not point geometry" is
        a property of the RESOURCE, so it belongs on the far side of the
        authorization gate for the same reason features.geojson's "Dataset has
        no geometry" does. Moving it there is also what stops an unauthorized
        caller learning a private dataset exists and what geometry it holds.
        """
        from tests.factories import create_dataset, get_user_id

        user_id = await get_user_id(test_db_session, ADMIN_USER)
        dataset = await create_dataset(
            test_db_session,
            created_by=user_id,
            name="Exit Class Polygon DS",
            visibility="public",
            record_status="published",
            geometry_type="Polygon",
            feature_count=1,
        )

        # A credential-less caller still gets the shape answer.
        anon = await client.get(f"/tiles/clusters/data.{dataset.table_name}/10/0/0.pbf")
        assert anon.status_code == 400, anon.text

        resp = await client.get(
            f"/tiles/clusters/data.{dataset.table_name}/10/0/0.pbf",
            headers={"Authorization": f"Bearer {UNRESOLVABLE}"},
        )
        self._assert_credential_refusal(resp)

    # -- the other half: no credential keeps the resource answer -------------

    async def test_credentialless_callers_still_get_the_resource_answer(
        self, client: AsyncClient, test_db_session
    ):
        """Without this, a handler that simply refused everything would pass."""
        import uuid as _uuid

        absent = await client.get(f"/datasets/{_uuid.uuid4()}/features.geojson")
        assert absent.status_code == 404, absent.text

        missing_link = await client.get("/maps/shared/no-such-share-token")
        assert missing_link.status_code == 404, missing_link.text

        # This fixture creates the catalog rows but no backing PostGIS table, so
        # the honest answer here is 503 "Dataset table is unavailable". What the
        # assertion is for is that it is a RESOURCE answer and not the credential
        # refusal — a 200 for an anonymous caller is pinned on a real dataset by
        # TestPreviouslyFailOpenEndpoint above.
        dataset = await self._public_dataset(test_db_session)
        ok = await client.get(f"/datasets/{dataset.id}/features.geojson")
        assert ok.status_code != 401, ok.text


@pytest.mark.architecture
def test_capability_declines_route_through_the_helper() -> None:
    """No bare 403 may remain on a capability path in the tile authorizers.

    The previous structural test could only require that a CAPABILITY handler
    CALLS ``reject_unresolvable_credentials`` somewhere reachable — it could not
    check that the call is on every no-capability path, which is exactly how
    three exit classes shipped uncovered (codex P2 round 3).

    Routing the declines through ``capability_declined`` makes that checkable:
    the ordering is a property of the call rather than of where a line sits, so
    this test can require that the two centralised authorizers raise no 403 of
    their own. Adding a new capability arm with a bare ``raise`` fails here
    instead of silently skipping the rule.
    """
    import ast
    import inspect
    import textwrap

    from app.processing.tiles.router import (
        _authorize_vector_tile_request,
        _resolve_raster_access,
    )

    offenders: list[str] = []
    for fn in (_authorize_vector_tile_request, _resolve_raster_access):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            func = node.exc.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name != "HTTPException":
                continue
            code = ""
            for keyword in node.exc.keywords:
                if keyword.arg == "status_code":
                    code = ast.unparse(keyword.value)
            if "403" in code:
                offenders.append(f"{fn.__name__} line {node.lineno}: {code}")

    assert not offenders, (
        "capability declines must go through capability_declined() so the "
        "#1518 credential rule runs before the 403:\n"
        + "\n".join(f"  {o}" for o in offenders)
    )
