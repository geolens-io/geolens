"""GH-1455: the revocation horizon, so no session credential outlives its logout.

``revoke_all_tokens`` revokes the refresh rows one statement's snapshot can see
and bumps ``token_version``. Neither can express "everything issued up to now",
so a refresh row inserted by a path that does not take the owner-row lock — a
login racing the logout, the GH-1455 headline case — can commit after that
snapshot and survive its own logout. ``users.sessions_revoked_at`` is the
use-time predicate that covers it: every credential issued at or before the
horizon is rejected on presentation, whatever its own row or claims say.

Every test here asserts a REJECTION that did not happen before, or that a
successor credential (issued after the horizon) still works. Nothing that was
rejected before becomes acceptable — the change is purely additive.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import anyio
import jwt
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.config import settings
from app.modules.auth.dependencies import get_current_user, get_optional_user
from app.modules.auth.models import RefreshToken, User
from app.modules.auth.service import AuthService

PASSWORD = "TestPass1234!"  # SEC-S16: 12 chars, 3 character classes


async def _create_user(client: AsyncClient, admin_headers: dict) -> tuple[str, str]:
    """Create a throwaway local user; return (user_id, username).

    A dedicated user per test rather than the seeded admin: stamping a horizon
    on the shared admin row would reject any token another test on this worker
    minted in the same second.
    """
    username = f"horizon_{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": PASSWORD, "role": "viewer"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], username


async def _login(client: AsyncClient, username: str) -> dict:
    resp = await client.post(
        "/auth/login", data={"username": username, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _load_user(session: AsyncSession, user_id) -> User:
    """Re-read the user, defeating the identity map.

    The test session is ``expire_on_commit=False``, so a plain ORM
    ``select(User)`` hands back a cached instance still carrying
    ``sessions_revoked_at = None`` after a Core UPDATE wrote one.
    ``populate_existing`` refreshes THIS entity from the incoming row without
    expiring the rest of the session, which a blanket ``expire_all()`` would
    do: any other ORM instance the test still holds would then reload lazily
    on next attribute access and raise ``MissingGreenlet`` under asyncio.
    """
    return (
        await session.execute(
            select(User)
            .where(User.id == uuid.UUID(str(user_id)))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _set_horizon(session: AsyncSession, user_id, when: datetime | None) -> None:
    """Write a horizon directly, then resync the cached User row.

    The dependencies under test re-read the user with a plain ``select(User)``,
    which returns the identity-mapped instance without overwriting attributes
    already loaded on it. Without the resync they would keep observing the
    pre-UPDATE horizon and the test would prove nothing.
    """
    await session.execute(
        update(User)
        .where(User.id == uuid.UUID(str(user_id)))
        .values(sessions_revoked_at=when)
    )
    await session.commit()
    await _load_user(session, user_id)


async def _refresh_row(session: AsyncSession, raw_token: str) -> RefreshToken:
    """Re-read the refresh row, defeating the identity map for the same reason
    ``_load_user`` does: ``revoke_all_tokens`` revokes via a Core UPDATE, which
    leaves a cached instance still claiming ``revoked=False``."""
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return (
        await session.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


def _mint_access_token(*, user: User, iat: object, token_version: int | None = None):
    """Encode an access JWT with a chosen ``iat``, otherwise shaped like a real one.

    ``iat`` is passed through verbatim (including ``None``, which omits the
    claim) so the missing-claim and non-numeric conventions are testable.
    """
    payload: dict = {
        "sub": str(user.id),
        "username": user.username,
        "jti": uuid.uuid4().hex,
        "token_version": (
            user.token_version if token_version is None else token_version
        ),
        "exp": datetime.now(UTC) + timedelta(minutes=15),
    }
    if iat is not None:
        payload["iat"] = iat
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def _bare_request() -> Request:
    """A credential-free request, so the API-key lane resolves to None."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
    )


async def _both_dependencies_reject(token: str, session: AsyncSession) -> None:
    """Assert BOTH JWT enforcement sites refuse *token*.

    The two dependencies duplicate their checks on purpose (the expired-token
    UX in ``get_current_user`` is why they were never collapsed), so a horizon
    check added to one and missed on the other is exactly the drift this
    asserts against.
    """
    assert await get_optional_user(_bare_request(), token, session) is None
    with pytest.raises(HTTPException) as excinfo:
        await get_current_user(_bare_request(), token, session)
    assert excinfo.value.status_code == 401


class TestRefreshRowsAtOrBeforeTheHorizonAreRejected:
    """The regression test for the race that motivates GH-1455.

    An UNREVOKED refresh row whose ``created_at`` is at or before the horizon
    is the survivor of the insert race: ``revoke_all_tokens`` never saw it, so
    ``revoked`` is still false and every pre-existing check passes it.
    """

    async def test_get_user_from_refresh_token_rejects_it(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        user_id, username = await _create_user(client, admin_auth_header)
        raw = (await _login(client, username))["refresh_token"]
        row = await _refresh_row(test_db_session, raw)
        assert not row.revoked, "the point of this test is an unrevoked row"

        service = AuthService(test_db_session)
        assert await service.get_user_from_refresh_token(raw) is not None

        # Exactly the row's own timestamp: the boundary is "at or before".
        await _set_horizon(test_db_session, user_id, row.created_at)

        assert await service.get_user_from_refresh_token(raw) is None

    async def test_rotate_refresh_token_rejects_it(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        user_id, username = await _create_user(client, admin_auth_header)
        raw = (await _login(client, username))["refresh_token"]
        row = await _refresh_row(test_db_session, raw)
        await _set_horizon(test_db_session, user_id, row.created_at)

        with pytest.raises(ValueError):
            await AuthService(test_db_session).rotate_refresh_token(raw)

        # And over HTTP, which is how the zombie session would actually present.
        resp = await client.post("/auth/refresh/", json={"refresh_token": raw})
        assert resp.status_code == 401, resp.text

    async def test_the_row_is_still_unrevoked_so_only_the_horizon_rejected_it(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Pins WHY it was rejected. If a future change revoked the row instead,
        this test would pass for the wrong reason and stop guarding the race."""
        user_id, username = await _create_user(client, admin_auth_header)
        raw = (await _login(client, username))["refresh_token"]
        row = await _refresh_row(test_db_session, raw)
        await _set_horizon(test_db_session, user_id, row.created_at)

        assert (
            await AuthService(test_db_session).get_user_from_refresh_token(raw) is None
        )
        assert not (await _refresh_row(test_db_session, raw)).revoked


class TestRefreshRowsAfterTheHorizonSurvive:
    """Successor survival: a login that follows the revocation is outside the
    revocation set by construction, with no client choreography involved."""

    async def test_a_row_created_after_the_horizon_rotates(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        user_id, username = await _create_user(client, admin_auth_header)
        first = (await _login(client, username))["refresh_token"]
        row = await _refresh_row(test_db_session, first)
        await _set_horizon(test_db_session, user_id, row.created_at)

        successor = (await _login(client, username))["refresh_token"]
        successor_row = await _refresh_row(test_db_session, successor)
        horizon = (await _load_user(test_db_session, user_id)).sessions_revoked_at
        assert successor_row.created_at > horizon

        resp = await client.post("/auth/refresh/", json={"refresh_token": successor})
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]


class TestAccessTokensAtOrBeforeTheHorizonAreRejected:
    """The JWT half, at both enforcement sites.

    ``token_version`` is deliberately held CURRENT in every rejection case
    here: a rotation racing the revocation reads the pre-bump value and mints a
    token carrying it, so a matching version is not evidence the token
    postdates the revocation.
    """

    async def test_iat_before_the_horizon_is_rejected_at_both_sites(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        user_id, username = await _create_user(client, admin_auth_header)
        await _login(client, username)
        user = await _load_user(test_db_session, user_id)

        horizon = datetime.now(UTC)
        token = _mint_access_token(user=user, iat=int(horizon.timestamp()) - 60)
        await _set_horizon(test_db_session, user_id, horizon)

        await _both_dependencies_reject(token, test_db_session)

    async def test_iat_after_the_horizon_is_accepted_at_both_sites(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        user_id, username = await _create_user(client, admin_auth_header)
        await _login(client, username)
        user = await _load_user(test_db_session, user_id)

        horizon = datetime.now(UTC) - timedelta(minutes=5)
        await _set_horizon(test_db_session, user_id, horizon)
        token = _mint_access_token(user=user, iat=int(datetime.now(UTC).timestamp()))

        assert (
            await get_optional_user(_bare_request(), token, test_db_session)
        ) is not None
        assert await get_current_user(_bare_request(), token, test_db_session)

    async def test_a_missing_iat_claim_is_rejected_once_a_horizon_exists(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Mirrors the missing-``token_version``-is-0 convention: absent means
        0, which is at or before every horizon."""
        user_id, username = await _create_user(client, admin_auth_header)
        await _login(client, username)
        user = await _load_user(test_db_session, user_id)

        token = _mint_access_token(user=user, iat=None)
        assert "iat" not in jwt.decode(token, options={"verify_signature": False})

        # No horizon yet: the same token authenticates, so the rejection below
        # is attributable to the horizon and nothing else.
        assert (
            await get_optional_user(_bare_request(), token, test_db_session)
        ) is not None

        await _set_horizon(test_db_session, user_id, datetime.now(UTC))
        await _both_dependencies_reject(token, test_db_session)

    async def test_a_non_numeric_iat_is_rejected_rather_than_raising(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """PyJWT validates ``iat`` by casting a COPY, so a numeric string stays
        a string in the payload and reaches the horizon comparison intact.

        The horizon is deliberately in the PAST and the claim is NOT in the
        future: PyJWT rejects a future ``iat`` itself (ImmatureSignatureError),
        which would make this pass without ever reaching the code under test,
        and a string that compares as later than the horizon is exactly the
        input that would raise ``TypeError`` out of the dependency (a 500)
        instead of refusing the token.
        """
        user_id, username = await _create_user(client, admin_auth_header)
        await _login(client, username)
        user = await _load_user(test_db_session, user_id)

        await _set_horizon(
            test_db_session, user_id, datetime.now(UTC) - timedelta(minutes=5)
        )
        token = _mint_access_token(
            user=user, iat=str(int(datetime.now(UTC).timestamp()))
        )

        await _both_dependencies_reject(token, test_db_session)

    async def test_the_same_second_as_the_horizon_is_accepted(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Pins the rounding direction, which is a real decision, not a detail.

        ``iat`` is whole seconds, so it names the interval ``[iat, iat+1)``
        rather than an instant. Rejecting the whole second would kill a token
        minted AFTER the revocation, which breaks logging out and immediately
        logging back in. The sub-second region is covered by the
        ``token_version`` bump instead: this same user's version is current
        here precisely because no bump happened.
        """
        user_id, username = await _create_user(client, admin_auth_header)
        await _login(client, username)
        user = await _load_user(test_db_session, user_id)

        second = int(datetime.now(UTC).timestamp())
        token = _mint_access_token(user=user, iat=second)
        # Horizon 20ms into the very second the token is stamped with, which is
        # the shape observed in the failure this rounding fixes.
        await _set_horizon(
            test_db_session, user_id, datetime.fromtimestamp(second + 0.02, UTC)
        )

        assert (
            await get_optional_user(_bare_request(), token, test_db_session)
        ) is not None
        assert await get_current_user(_bare_request(), token, test_db_session)

        # One whole second earlier is unambiguously before the horizon.
        stale = _mint_access_token(user=user, iat=second - 1)
        await _both_dependencies_reject(stale, test_db_session)

    async def test_no_horizon_means_no_new_rejection(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """NULL is correct for every pre-migration row, so a user who has never
        revoked must see no behaviour change at all — including for the ancient
        ``iat`` that the horizon check would otherwise refuse."""
        user_id, username = await _create_user(client, admin_auth_header)
        await _login(client, username)
        user = await _load_user(test_db_session, user_id)
        assert user.sessions_revoked_at is None

        token = _mint_access_token(user=user, iat=1)
        assert (
            await get_optional_user(_bare_request(), token, test_db_session)
        ) is not None
        assert await get_current_user(_bare_request(), token, test_db_session)


class TestLogoutStampsTheHorizonAndKeepsItMonotonic:
    async def test_logout_sets_a_horizon_and_still_bumps_token_version(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        user_id, username = await _create_user(client, admin_auth_header)
        before = await _load_user(test_db_session, user_id)
        assert before.sessions_revoked_at is None
        version_before = before.token_version

        await AuthService(test_db_session).revoke_all_tokens(uuid.UUID(str(user_id)))

        after = await _load_user(test_db_session, user_id)
        assert after.sessions_revoked_at is not None, (
            "the COALESCE fallback must let the first revocation stamp a NULL "
            "horizon — a broken sentinel cast would leave it NULL"
        )
        assert abs((after.sessions_revoked_at - datetime.now(UTC)).total_seconds()) < 60
        # The bump is RETAINED, not replaced: it is what still rejects a
        # pre-revocation token whose iat clears the horizon under clock skew.
        assert after.token_version == version_before + 1

    async def test_a_later_revocation_cannot_regress_the_horizon(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GREATEST, not assignment. A DB clock that steps backwards must not
        resurrect credentials an earlier revocation already killed."""
        user_id, username = await _create_user(client, admin_auth_header)
        future = datetime.now(UTC) + timedelta(hours=1)
        await _set_horizon(test_db_session, user_id, future)

        await AuthService(test_db_session).revoke_all_tokens(uuid.UUID(str(user_id)))

        after = await _load_user(test_db_session, user_id)
        assert after.sessions_revoked_at == future

    async def test_a_second_revocation_advances_it(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The other half of GREATEST: monotonic must not mean frozen."""
        user_id, username = await _create_user(client, admin_auth_header)
        past = datetime.now(UTC) - timedelta(hours=1)
        await _set_horizon(test_db_session, user_id, past)

        await AuthService(test_db_session).revoke_all_tokens(uuid.UUID(str(user_id)))

        after = await _load_user(test_db_session, user_id)
        assert after.sessions_revoked_at > past


class TestASuccessorLoginSurvivesTheLogoutEndToEnd:
    """The whole point: logout must kill the old session without maiming the
    next one. Runs entirely over HTTP, through the real handlers."""

    async def test_logout_then_login_then_refresh(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        user_id, username = await _create_user(client, admin_auth_header)
        first = await _login(client, username)

        resp = await client.post(
            "/auth/logout/",
            json={"refresh_token": first["refresh_token"]},
            headers={"Authorization": f"Bearer {first['access_token']}"},
        )
        assert resp.status_code == 204, resp.text

        # The ended session is dead on both credentials.
        assert (
            await client.get(
                "/auth/me/",
                headers={"Authorization": f"Bearer {first['access_token']}"},
            )
        ).status_code == 401
        assert (
            await client.post(
                "/auth/refresh/", json={"refresh_token": first["refresh_token"]}
            )
        ).status_code == 401

        # iat is integer seconds, so a token minted in the same second as the
        # horizon is rejected too (over-revocation bounded by one second, in
        # the fail-safe direction). Wait that second out so the successor's
        # acceptance is deterministic rather than clock-phase dependent.
        horizon = (await _load_user(test_db_session, user_id)).sessions_revoked_at
        assert horizon is not None
        while int(datetime.now(UTC).timestamp()) <= int(horizon.timestamp()):
            await anyio.sleep(0.05)

        successor = await _login(client, username)
        assert (
            await client.get(
                "/auth/me/",
                headers={"Authorization": f"Bearer {successor['access_token']}"},
            )
        ).status_code == 200

        rotated = await client.post(
            "/auth/refresh/", json={"refresh_token": successor["refresh_token"]}
        )
        assert rotated.status_code == 200, rotated.text
        assert (
            await client.get(
                "/auth/me/",
                headers={"Authorization": f"Bearer {rotated.json()['access_token']}"},
            )
        ).status_code == 200


class TestSamlConversionStampsTheHorizon:
    """The conversion used to duplicate revoke_all_tokens' two UPDATEs inline,
    which is precisely how it would have missed the horizon. Folding it onto
    the shared method is what keeps the two revocation sites identical."""

    async def test_conversion_revokes_refresh_rows_and_stamps_the_horizon(
        self, client: AsyncClient, test_db_session
    ):
        from app.modules.admin.service import AdminService
        from app.modules.auth.models import Role, UserRole
        from app.modules.auth.oauth.encryption import encrypt_secret
        from app.modules.auth.oauth.models import OAuthAccount, OAuthProvider
        from app.modules.auth.providers.local import hash_password

        suffix = uuid.uuid4().hex[:8]
        provider = OAuthProvider(
            slug=f"saml-horizon-{suffix}",
            display_name="SAML Horizon Test",
            provider_type="saml",
            client_id="saml-no-client-id",
            client_secret_encrypted=encrypt_secret("saml-no-client-secret"),
            scopes="",
            enabled=True,
            default_role="viewer",
        )
        test_db_session.add(provider)
        await test_db_session.flush()

        saml_user = User(
            username=f"samlhorizon-{suffix}",
            password_hash=hash_password(PASSWORD),
            is_active=True,
            status="active",
            auth_provider="oauth",
        )
        test_db_session.add(saml_user)
        await test_db_session.flush()

        viewer_role = (
            await test_db_session.execute(select(Role).where(Role.name == "viewer"))
        ).scalar_one()
        test_db_session.add(UserRole(user_id=saml_user.id, role_id=viewer_role.id))
        test_db_session.add(
            OAuthAccount(
                provider_id=provider.id,
                user_id=saml_user.id,
                subject=f"saml-sub-{suffix}",
            )
        )
        # A live SAML-era refresh row, so the folded revocation has something
        # to revoke — the half of the fold nothing else covers.
        raw_refresh = AuthService(test_db_session).create_refresh_token(saml_user.id)
        await test_db_session.commit()

        assert (
            await _load_user(test_db_session, saml_user.id)
        ).sessions_revoked_at is None

        await AdminService(test_db_session).convert_saml_user_to_local(
            saml_user.id, "NewPass1234!"
        )
        await test_db_session.commit()

        converted = await _load_user(test_db_session, saml_user.id)
        assert converted.sessions_revoked_at is not None
        assert (await _refresh_row(test_db_session, raw_refresh)).revoked


class TestPathsThatMustNotStampTheHorizon:
    async def test_a_role_change_does_not_stamp_the_horizon(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The horizon means "log every session out", not "refresh your
        claims". Role change bumps key_epoch only, and must keep doing so."""
        user_id, _username = await _create_user(client, admin_auth_header)

        resp = await client.patch(
            f"/admin/users/{user_id}",
            json={"role": "editor"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text

        after = await _load_user(test_db_session, user_id)
        assert after.sessions_revoked_at is None
        assert after.key_epoch > 1
