"""fix(#1548 review P2): the #1531 domain-lock fix, measured under the SHIPPED
configuration rather than a corrected one.

#1531 taught the API-layer allowlist to accept this deployment's own origin, so
that an embed shell's subresource requests — which carry the SHELL's origin,
never the embedder's — stop being denied. The origin it compares against comes
from ``PUBLIC_APP_URL``, and that setting has a default which is wrong for
almost every real install: ``docker-compose.yml`` and ``docker-compose.prod.yml``
both inject ``${PUBLIC_APP_URL:-http://localhost:8080}``, and ``.env.example``
ships the line commented out. A self-hoster reached at https://maps.example.com
who never set it therefore resolves a self-origin of ``http://localhost:8080``,
matches nothing, and gets the pre-#1531 behaviour: an embed that loads and stays
empty, with nothing said at the moment the lock was turned on.

Every other test of this feature configures ``PUBLIC_APP_URL`` to a real
hostname first — necessary hygiene, since the localhost bypass would otherwise
be free to take credit for the fix, but it also configures the remaining bug
away. This file deliberately does the opposite: it pins ``PUBLIC_APP_URL`` to
the value compose actually injects and drives the real routers against a real
database, so the shipped default is under test rather than assumed.

The unset case converges here too: with no ``PUBLIC_APP_URL`` at all,
``resolve_public_app_url`` falls through to ``_DEFAULT_PUBLIC_APP_URL``, which
is the same ``http://localhost:8080``.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import public_urls
from app.core.config import settings
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.embed_tokens import service as embed_service
from app.modules.embed_tokens.models import EmbedToken

from tests.factories import create_dataset, get_user_id

# What compose injects when the operator never sets PUBLIC_APP_URL.
COMPOSE_DEFAULT_APP_URL = "http://localhost:8080"
# Where the deployment is actually reached.
SELF_HOSTED_ORIGIN = "https://maps.example.com"
# What the operator puts in allowed_origins: their customer's site.
CUSTOMER_ORIGIN = "https://customer.example.com"


@pytest.fixture
def enterprise_edition(monkeypatch):
    """Domain locking is an advanced-sharing control."""
    from app.core.edition import init_edition

    monkeypatch.delenv("GEOLENS_EDITION", raising=False)
    init_edition(["enterprise"])
    yield
    init_edition([])


@pytest.fixture
def public_app_url(monkeypatch):
    """Set the deployment's configured public app URL, the way an operator does.

    The 60s module-global ``_PUBLIC_URL_CACHE`` is cleared on both sides: it is
    memoized per process, so without this a value primed by an earlier test
    would decide this one's outcome — the exact order-dependence that hid the
    other half of this review.
    """

    def _set(value: str | None) -> None:
        monkeypatch.setattr(settings, "public_app_url", value)
        monkeypatch.setattr(settings, "public_api_url", None)
        monkeypatch.setattr(settings, "public_base_url", None)
        public_urls.invalidate_public_url_cache()

    yield _set
    public_urls.invalidate_public_url_cache()


def _browser_at(origin: str) -> MagicMock:
    """A request from a browser sitting on ``origin``.

    ``client.host`` is a container bridge IP, not loopback: in the shipped
    stack nginx proxies to the api service, so the H-31 loopback bypass is out
    of reach for every real browser request.
    """
    request = MagicMock()
    request.headers = {"origin": origin}
    request.client = SimpleNamespace(host="172.18.0.5")
    request.state = SimpleNamespace()
    return request


async def _create_map(
    session: AsyncSession, *, created_by: uuid.UUID, with_layer: bool = False
) -> Map:
    """Insert a Map, optionally with one layer.

    ``with_layer`` matters for POST: ``create_embed_token`` rejects a layerless
    map with 400 "Map has no layers to scope" BEFORE minting anything, so a POST
    test on a bare map would be refused whether or not the new gate exists — and
    an assertion that no token was written would hold vacuously.
    """
    map_obj = Map(
        name=f"Shipped default {uuid.uuid4().hex[:6]}",
        description="#1548 review P2",
        visibility="public",
        created_by=created_by,
    )
    session.add(map_obj)
    await session.flush()

    if with_layer:
        dataset = await create_dataset(
            session,
            created_by=created_by,
            name=f"Shipped default DS {uuid.uuid4().hex[:6]}",
            visibility="private",
            description="#1548 review P2",
            geometry_type="Point",
            feature_count=1,
            column_info=[
                {"name": "gid", "type": "integer"},
                {"name": "geom", "type": "geometry"},
            ],
        )
        session.add(MapLayer(map_id=map_obj.id, dataset_id=dataset.id, sort_order=0))
        await session.flush()

    await session.refresh(map_obj)
    return map_obj


async def _existing_token(
    session: AsyncSession,
    *,
    map_id: uuid.UUID,
    created_by: uuid.UUID,
    allowed_origins: list[str] | None = None,
) -> tuple[EmbedToken, str]:
    """Insert an EmbedToken directly, bypassing the router's new gate.

    Stands in for a token minted before this fix existed. Returns the row and
    its raw token.
    """
    raw = secrets.token_urlsafe(32)
    token = EmbedToken(
        map_id=map_id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        token_hint=raw[:8],
        scoped_dataset_ids=[],
        allowed_origins=allowed_origins,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        is_active=True,
        created_by=created_by,
    )
    session.add(token)
    await session.flush()
    await session.refresh(token)
    return token, raw


# ---------------------------------------------------------------------------
# The bug: what the shipped default does to an already-issued lock
# ---------------------------------------------------------------------------


async def test_the_shipped_default_really_denies_the_shell(
    test_db_session: AsyncSession, public_app_url, enterprise_edition
):
    """The measurement the corrected-config suites cannot make.

    A real database, the real ``get_configured_public_app_url`` stack, and
    ``PUBLIC_APP_URL`` exactly as compose leaves it. The request is the one
    #1531 taught the check to accept — the embed shell's own — and it is still
    denied, because the origin it is compared against is localhost. This is the
    empty embed, reproduced.
    """
    public_app_url(COMPOSE_DEFAULT_APP_URL)

    allowed = await embed_service._request_origin_is_allowed(
        test_db_session, _browser_at(SELF_HOSTED_ORIGIN), [CUSTOMER_ORIGIN]
    )
    assert allowed is False


async def test_the_same_shell_request_is_accepted_once_the_url_is_set(
    test_db_session: AsyncSession, public_app_url, enterprise_edition
):
    """Counterpart to the test above: the request never changes, only the
    configuration does. Without this pair, the denial above could be caused by
    anything at all and the message would be pointing at the wrong knob."""
    public_app_url(SELF_HOSTED_ORIGIN)

    allowed = await embed_service._request_origin_is_allowed(
        test_db_session, _browser_at(SELF_HOSTED_ORIGIN), [CUSTOMER_ORIGIN]
    )
    assert allowed is True


# ---------------------------------------------------------------------------
# The fix: the operator is told, at the moment they turn the lock on
# ---------------------------------------------------------------------------


async def test_post_refuses_a_domain_lock_under_the_shipped_default(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    public_app_url,
    enterprise_edition,
):
    public_app_url(COMPOSE_DEFAULT_APP_URL)
    user_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_map(test_db_session, created_by=user_id, with_layer=True)
    await test_db_session.commit()

    resp = await client.post(
        f"/maps/{map_obj.id}/embed-tokens/",
        json={"allowed_origins": [CUSTOMER_ORIGIN]},
        headers={**admin_auth_header, "Origin": SELF_HOSTED_ORIGIN},
    )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "PUBLIC_APP_URL" in detail, "name the variable to set"
    assert COMPOSE_DEFAULT_APP_URL in detail, "name what it resolved to"
    assert SELF_HOSTED_ORIGIN in detail, "name where the request arrived"


async def test_the_refused_post_leaves_no_token_behind(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    public_app_url,
    enterprise_edition,
):
    """Fail before the mutation, not after it. A 422 with a live token row on
    the other side would be the same silent embed plus a confusing message."""
    from sqlalchemy import select

    public_app_url(COMPOSE_DEFAULT_APP_URL)
    user_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_map(test_db_session, created_by=user_id, with_layer=True)
    await test_db_session.commit()

    await client.post(
        f"/maps/{map_obj.id}/embed-tokens/",
        json={"allowed_origins": [CUSTOMER_ORIGIN]},
        headers={**admin_auth_header, "Origin": SELF_HOSTED_ORIGIN},
    )

    rows = (
        (
            await test_db_session.execute(
                select(EmbedToken).where(EmbedToken.map_id == map_obj.id)
            )
        )
        .scalars()
        .all()
    )
    assert list(rows) == []


async def test_patch_refuses_a_domain_lock_under_the_shipped_default(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    public_app_url,
    enterprise_edition,
):
    """The path the builder actually takes: it creates the token unlocked, then
    PATCHes the origins on as the operator adds them."""
    public_app_url(COMPOSE_DEFAULT_APP_URL)
    user_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_map(test_db_session, created_by=user_id)
    token, _raw = await _existing_token(
        test_db_session, map_id=map_obj.id, created_by=user_id
    )
    await test_db_session.commit()

    resp = await client.patch(
        f"/maps/{map_obj.id}/embed-tokens/{token.id}/",
        json={"allowed_origins": [CUSTOMER_ORIGIN]},
        headers={**admin_auth_header, "Origin": SELF_HOSTED_ORIGIN},
    )

    assert resp.status_code == 422, resp.text
    assert "PUBLIC_APP_URL" in resp.json()["detail"]

    await test_db_session.refresh(token)
    assert token.allowed_origins is None, "the refused lock must not be stored"


async def test_patch_succeeds_once_public_app_url_names_the_real_origin(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    public_app_url,
    enterprise_edition,
):
    """The remediation the 422 prints, carried out. Same request, same map, same
    origins — only PUBLIC_APP_URL changed."""
    public_app_url(SELF_HOSTED_ORIGIN)
    user_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_map(test_db_session, created_by=user_id)
    token, _raw = await _existing_token(
        test_db_session, map_id=map_obj.id, created_by=user_id
    )
    await test_db_session.commit()

    resp = await client.patch(
        f"/maps/{map_obj.id}/embed-tokens/{token.id}/",
        json={"allowed_origins": [CUSTOMER_ORIGIN]},
        headers={**admin_auth_header, "Origin": SELF_HOSTED_ORIGIN},
    )

    assert resp.status_code == 200, resp.text
    await test_db_session.refresh(token)
    assert token.allowed_origins == [CUSTOMER_ORIGIN]


async def test_clearing_a_lock_is_allowed_under_the_shipped_default(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    public_app_url,
    enterprise_edition,
):
    """The operator's way out.

    Removing the LAST origin sends ``allowed_origins: null``, which the gate
    never refuses — so an operator who cannot change PUBLIC_APP_URL right now is
    never stuck with a lock they can neither enforce nor remove.
    """
    public_app_url(COMPOSE_DEFAULT_APP_URL)
    user_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_map(test_db_session, created_by=user_id)
    token, _raw = await _existing_token(
        test_db_session,
        map_id=map_obj.id,
        created_by=user_id,
        allowed_origins=[CUSTOMER_ORIGIN],
    )
    await test_db_session.commit()

    resp = await client.patch(
        f"/maps/{map_obj.id}/embed-tokens/{token.id}/",
        json={"allowed_origins": None},
        headers={**admin_auth_header, "Origin": SELF_HOSTED_ORIGIN},
    )

    assert resp.status_code == 200, resp.text
    await test_db_session.refresh(token)
    assert token.allowed_origins is None


# ---------------------------------------------------------------------------
# Ordering: existence is settled before the deployment-level precondition
# ---------------------------------------------------------------------------


async def test_patch_404s_a_missing_token_instead_of_naming_public_app_url(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    public_app_url,
    enterprise_edition,
):
    """fix(#1548 review r2): the gate answers a question about the DEPLOYMENT,
    not about this token. Asked before existence, it told the owner of a stale
    token id to go and reconfigure their server, when the real answer is that
    their token is gone. A stale id in an open builder tab and a concurrent
    revoke both reach this.
    """
    public_app_url(COMPOSE_DEFAULT_APP_URL)
    user_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_map(test_db_session, created_by=user_id)
    await test_db_session.commit()

    resp = await client.patch(
        f"/maps/{map_obj.id}/embed-tokens/{uuid.uuid4()}/",
        json={"allowed_origins": [CUSTOMER_ORIGIN]},
        headers={**admin_auth_header, "Origin": SELF_HOSTED_ORIGIN},
    )

    assert resp.status_code == 404, resp.text
    detail = resp.json()["detail"]
    assert detail == "Embed token not found"
    assert "PUBLIC_APP_URL" not in detail, (
        "a caller whose token does not exist must not be sent to reconfigure "
        "the deployment"
    )


async def test_patch_404s_a_revoked_token_instead_of_naming_public_app_url(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    public_app_url,
    enterprise_edition,
):
    """The concurrent-revocation half of the same path: the row is there, but
    ``is_active`` is False, so the write would have returned None and 404'd."""
    public_app_url(COMPOSE_DEFAULT_APP_URL)
    user_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_map(test_db_session, created_by=user_id)
    token, _raw = await _existing_token(
        test_db_session, map_id=map_obj.id, created_by=user_id
    )
    token.is_active = False
    await test_db_session.commit()

    resp = await client.patch(
        f"/maps/{map_obj.id}/embed-tokens/{token.id}/",
        json={"allowed_origins": [CUSTOMER_ORIGIN]},
        headers={**admin_auth_header, "Origin": SELF_HOSTED_ORIGIN},
    )

    assert resp.status_code == 404, resp.text
    assert "PUBLIC_APP_URL" not in resp.json()["detail"]


async def test_a_token_on_another_map_is_not_found_rather_than_refused(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    public_app_url,
    enterprise_edition,
):
    """The existence check is scoped by map_id, exactly as the write is, so a
    real token id addressed through the wrong map takes the 404 too."""
    public_app_url(COMPOSE_DEFAULT_APP_URL)
    user_id = await get_user_id(test_db_session, "admin")
    owning_map = await _create_map(test_db_session, created_by=user_id)
    other_map = await _create_map(test_db_session, created_by=user_id)
    token, _raw = await _existing_token(
        test_db_session, map_id=owning_map.id, created_by=user_id
    )
    await test_db_session.commit()

    resp = await client.patch(
        f"/maps/{other_map.id}/embed-tokens/{token.id}/",
        json={"allowed_origins": [CUSTOMER_ORIGIN]},
        headers={**admin_auth_header, "Origin": SELF_HOSTED_ORIGIN},
    )

    assert resp.status_code == 404, resp.text
    assert "PUBLIC_APP_URL" not in resp.json()["detail"]


async def test_an_existing_token_still_gets_the_refusal(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    public_app_url,
    enterprise_edition,
):
    """The other side of the ordering: reordering must not have turned the
    refusal off for the token it is actually meant for. Without this pair, a
    gate deleted outright would pass all three 404 tests above."""
    public_app_url(COMPOSE_DEFAULT_APP_URL)
    user_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_map(test_db_session, created_by=user_id)
    token, _raw = await _existing_token(
        test_db_session, map_id=map_obj.id, created_by=user_id
    )
    await test_db_session.commit()

    resp = await client.patch(
        f"/maps/{map_obj.id}/embed-tokens/{token.id}/",
        json={"allowed_origins": [CUSTOMER_ORIGIN]},
        headers={**admin_auth_header, "Origin": SELF_HOSTED_ORIGIN},
    )

    assert resp.status_code == 422, resp.text
    assert "PUBLIC_APP_URL" in resp.json()["detail"]


def test_the_precondition_never_precedes_authorization_or_existence():
    """Structural pin on the ordering, for both handlers.

    Both orderings read as reasonable in isolation, which is what made this one
    easy to miss, so assert the sequence rather than trusting a reviewer to
    re-derive it. In each handler that gates, every authorization and existence
    check must appear BEFORE assert_domain_lock_is_enforceable.

    POST legitimately has no token-existence check: it is creating the token.
    Its map lookup and ownership check are still required to come first.
    """
    import ast
    import inspect

    from app.modules.embed_tokens import router as embed_router

    tree = ast.parse(inspect.getsource(embed_router))
    must_precede = {
        "get_map",
        "check_map_ownership",
        "get_active_embed_token",
    }

    checked: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        calls = [
            (call.func.id, call.lineno)
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        ]
        gate = [
            line for name, line in calls if name == "assert_domain_lock_is_enforceable"
        ]
        if not gate:
            continue
        checked.append(node.name)
        for name, line in calls:
            if name in must_precede:
                assert line < gate[0], (
                    f"{node.name}: {name}() runs at line {line}, after the "
                    f"domain-lock precondition at line {gate[0]}. A precondition "
                    "about the DEPLOYMENT must never answer ahead of whether the "
                    "caller is allowed to be here or whether the resource exists."
                )

    assert sorted(checked) == [
        "create_embed_token_endpoint",
        "update_embed_token_endpoint",
    ], f"gated handlers changed; ordering unchecked for some: {sorted(checked)}"
    assert "get_active_embed_token" in inspect.getsource(
        embed_router.update_embed_token_endpoint
    ), "the PATCH handler must settle token existence itself, before the gate"


@pytest.mark.parametrize("token_exists", [True, False], ids=["exists", "missing"])
async def test_neither_status_is_reachable_without_ownership(
    client: AsyncClient,
    admin_auth_header: dict,
    editor_auth_header: dict,
    test_db_session: AsyncSession,
    public_app_url,
    enterprise_edition,
    token_exists,
):
    """Ordering existence first DOES make the status distinguish a token that
    exists (422) from one that does not (404) — before the reorder both were
    422. That is not a disclosure, and this is the reason why: ``check_map_
    ownership`` 403s everyone but the map's owner and admins, so neither status
    is reachable without already being able to GET /maps/{id}/embed-tokens/ and
    read the list directly. The sibling revoke endpoint has always 404'd a
    missing token on the same terms.

    Asserted for both existence states, since a 403 that only held in one of
    them would be the leak this rules out.
    """
    public_app_url(COMPOSE_DEFAULT_APP_URL)
    user_id = await get_user_id(test_db_session, "admin")
    map_obj = await _create_map(test_db_session, created_by=user_id)
    if token_exists:
        token, _raw = await _existing_token(
            test_db_session, map_id=map_obj.id, created_by=user_id
        )
        token_id = token.id
    else:
        token_id = uuid.uuid4()
    await test_db_session.commit()

    resp = await client.patch(
        f"/maps/{map_obj.id}/embed-tokens/{token_id}/",
        json={"allowed_origins": [CUSTOMER_ORIGIN]},
        headers={**editor_auth_header, "Origin": SELF_HOSTED_ORIGIN},
    )

    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert "PUBLIC_APP_URL" not in detail
    assert "Embed token not found" not in detail


# ---------------------------------------------------------------------------
# r9: a value that passes validation but is not what the browser will present
# ---------------------------------------------------------------------------


async def test_an_api_derived_app_url_cannot_authorize_a_domain_lock(
    test_db_session: AsyncSession, public_app_url, enterprise_edition, monkeypatch
):
    """fix(#1548 review r9): a split app/API deployment.

    With only ``PUBLIC_API_URL`` set, ``get_public_app_url`` derives an app URL
    from it by stripping the ``/api`` suffix. That is a real, non-loopback host
    — so the shape rule passes and the loopback rule passes — but it is the API
    host, not the one the embed shell is served from. Trusting it issued a lock
    whose every subsequent request came from somewhere else.
    """
    public_app_url(None)
    monkeypatch.setattr(settings, "public_api_url", "https://api.example.com/api")
    public_urls.invalidate_public_url_cache()

    # The resolver still derives one — that behaviour is deliberate elsewhere.
    assert await public_urls.get_public_app_url(test_db_session) == (
        "https://api.example.com"
    )
    # The domain lock does not see it.
    assert await public_urls.get_configured_public_app_url(test_db_session) is None
    assert (
        await embed_service._request_origin_is_allowed(
            test_db_session, _browser_at(SELF_HOSTED_ORIGIN), [CUSTOMER_ORIGIN]
        )
        is False
    )

    with pytest.raises(embed_service.DomainLockNotEnforceableError) as exc:
        await embed_service.assert_domain_lock_is_enforceable(
            test_db_session, _browser_at(SELF_HOSTED_ORIGIN), [CUSTOMER_ORIGIN]
        )
    assert "PUBLIC_APP_URL" in str(exc.value)


async def test_tile_config_reports_only_an_explicitly_configured_app_url(
    client: AsyncClient, test_db_session: AsyncSession, public_app_url, monkeypatch
):
    """The same value reaches the frontend's share builder through tile-config,
    so the derivation had to be closed on that path too — otherwise /m/ and
    /card links point at the API host."""
    public_app_url(None)
    monkeypatch.setattr(settings, "public_api_url", "https://api.example.com/api")
    public_urls.invalidate_public_url_cache()

    resp = await client.get("/settings/tile-config/")
    assert resp.status_code == 200, resp.text
    assert resp.json()["public_app_url"] is None

    public_app_url(SELF_HOSTED_ORIGIN)
    resp = await client.get("/settings/tile-config/")
    assert resp.json()["public_app_url"] == SELF_HOSTED_ORIGIN


async def test_a_unicode_hostname_is_refused_rather_than_translated(
    test_db_session: AsyncSession, public_app_url, enterprise_edition
):
    """fix(#1548 review r10): IDN is refused, not approximated.

    An earlier round converted the host with Python's built-in ``idna`` codec so
    it would match what the browser sends. That codec is IDNA2003: it maps
    ``faß.de`` to ``fass.de``, while browsers follow WHATWG/UTS #46 and send
    ``xn--fa-hia.de``. A near match is worse than none — it denies every request
    while looking correct — so the value is refused and the operator supplies
    the punycode form, which is unambiguous and is what the browser sends.
    """
    public_app_url("https://faß.de")

    assert await public_urls.get_configured_public_app_url(test_db_session) is None
    with pytest.raises(embed_service.DomainLockNotEnforceableError) as exc:
        await embed_service.assert_domain_lock_is_enforceable(
            test_db_session, _browser_at(SELF_HOSTED_ORIGIN), [CUSTOMER_ORIGIN]
        )
    assert "PUBLIC_APP_URL" in str(exc.value)

    # The punycode spelling is accepted and matches the browser byte for byte.
    public_app_url("https://xn--fa-hia.de")
    assert (
        await embed_service._request_origin_is_allowed(
            test_db_session, _browser_at("https://xn--fa-hia.de"), [CUSTOMER_ORIGIN]
        )
        is True
    )


async def test_a_backslash_cannot_smuggle_a_second_host(
    test_db_session: AsyncSession, public_app_url, enterprise_edition
):
    """fix(#1548 review r10): origin confusion, not a formatting nit.

    ``https://maps.example.com\\@evil.com`` is host ``maps.example.com\\`` to
    urlsplit and host ``evil.com`` to a browser. Whichever reading is "right",
    the two halves disagreeing is the primitive, so the character is refused.
    """
    public_app_url("https://maps.example.com\\@evil.com")

    assert await public_urls.get_configured_public_app_url(test_db_session) is None
    origins = await embed_service._resolve_self_origins(
        test_db_session, _browser_at(SELF_HOSTED_ORIGIN)
    )
    assert origins == set(), "a value the two parsers read differently is no origin"
    assert (
        await embed_service._request_origin_is_allowed(
            test_db_session, _browser_at("https://evil.com"), [CUSTOMER_ORIGIN]
        )
        is False
    )


async def test_userinfo_never_reaches_a_stored_origin(
    test_db_session: AsyncSession, public_app_url, enterprise_edition
):
    """Credentials in the setting are dropped, not stored and not handed out.

    A browser never sends userinfo in Origin, so keeping it guaranteed a miss —
    and it would have travelled into any CSP header or copied link built from
    the value.
    """
    public_app_url("https://ops:secret@maps.example.com")

    assert (
        await embed_service._request_origin_is_allowed(
            test_db_session, _browser_at(SELF_HOSTED_ORIGIN), [CUSTOMER_ORIGIN]
        )
        is True
    )
    origins = await embed_service._resolve_self_origins(
        test_db_session, _browser_at(SELF_HOSTED_ORIGIN)
    )
    assert origins == {SELF_HOSTED_ORIGIN}
    assert not any("secret" in o for o in origins), "credentials must not be stored"


# ---------------------------------------------------------------------------
# r10 P1: "derived" names two things, and only one of them is untrustworthy
# ---------------------------------------------------------------------------


class TestHostedTenantKeepsItsOwnOrigin:
    """fix(#1548 review r10): requiring the EXPLICIT fleet setting broke hosted.

    ``PUBLIC_APP_URL`` is fleet-wide and cannot represent a tenant host, so
    demanding it made share and embed URLs on ``acme.geolens.example`` come out
    on the fleet host — where the anonymous request carries no Host-derived
    tenant context and fails closed.

    ``tenant_public_origin`` is not the same kind of value as an ``/api``-stripped
    ``PUBLIC_API_URL`` or a caller's header. ``TenantContextMiddleware`` sets it
    only after the Host resolves against the tenant registry, and rejects the
    request outright when it cannot form a trusted origin. Validated
    infrastructure state, not an inference.
    """

    TENANT_ORIGIN = "https://acme.geolens.example"

    @staticmethod
    def _tenant_request(origin: str | None, tenant_id: object = "t-1"):
        request = MagicMock()
        request.headers = {"origin": origin} if origin else {}
        request.client = SimpleNamespace(host="172.18.0.5")
        request.state = SimpleNamespace(
            tenant_id=tenant_id,
            tenant_public_origin=TestHostedTenantKeepsItsOwnOrigin.TENANT_ORIGIN,
        )
        return request

    async def test_a_tenant_host_shares_on_its_own_origin(
        self, test_db_session: AsyncSession, public_app_url, monkeypatch
    ):
        public_app_url("https://fleet.geolens.example")
        monkeypatch.setattr(public_urls, "is_multi_tenant", lambda: True)

        assert (
            await public_urls.get_shareable_app_url(
                test_db_session, request=self._tenant_request(self.TENANT_ORIGIN)
            )
            == self.TENANT_ORIGIN
        ), "a copied /card link on the fleet host arrives without tenant context"

    async def test_single_tenant_still_gets_explicit_only(
        self, test_db_session: AsyncSession, public_app_url, monkeypatch
    ):
        """The tenant branch is gated on the mode that populates it, so nothing
        about single-tenant changes — including that an unset value stays None
        rather than being back-filled from PUBLIC_API_URL."""
        public_app_url(None)
        monkeypatch.setattr(settings, "public_api_url", "https://api.example.com/api")
        public_urls.invalidate_public_url_cache()

        assert (
            await public_urls.get_shareable_app_url(
                test_db_session, request=self._tenant_request(SELF_HOSTED_ORIGIN)
            )
            is None
        )

    async def test_a_service_host_request_falls_back_to_the_fleet_setting(
        self, test_db_session: AsyncSession, public_app_url, monkeypatch
    ):
        """Hosted, but no resolved tenant — a JWT-scoped request on a trusted
        service host. The middleware left no tenant_id, so there is no validated
        tenant origin and the explicit fleet value is the honest answer."""
        public_app_url("https://fleet.geolens.example")
        monkeypatch.setattr(public_urls, "is_multi_tenant", lambda: True)

        assert (
            await public_urls.get_shareable_app_url(
                test_db_session,
                request=self._tenant_request(SELF_HOSTED_ORIGIN, tenant_id=None),
            )
            == "https://fleet.geolens.example"
        )

    async def test_the_tenant_origin_still_has_to_pass_the_shape_rule(
        self, test_db_session: AsyncSession, public_app_url, monkeypatch
    ):
        """Validated by middleware is not a reason to skip the shape check —
        that is how a narrower guarantee gets substituted for a wider one."""
        public_app_url(None)
        monkeypatch.setattr(public_urls, "is_multi_tenant", lambda: True)
        request = self._tenant_request(SELF_HOSTED_ORIGIN)
        request.state.tenant_public_origin = "ftp://acme.geolens.example"

        assert (
            await public_urls.get_shareable_app_url(test_db_session, request=request)
            is None
        )
