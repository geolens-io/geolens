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

    A real database, the real ``get_public_app_url`` stack, and
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
