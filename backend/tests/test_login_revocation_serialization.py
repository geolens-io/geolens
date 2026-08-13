"""Credential issuance is serialized against revocation. Nothing else pins it.

fix(#1459): that issue was filed on the belief that a login whose transaction
BEGINS inside a revoking transaction reads the pre-bump ``token_version``,
mints from that stale state, and lands an unrevoked refresh row that rotates
into a session outliving its own logout. It was closed as not planned: the
interleaving does not occur, because every path that issues a refresh token
writes the user row before minting and therefore queues behind
``revoke_all_tokens``'s ``SELECT ... FOR UPDATE``.

  - password login: ``user.last_login_at = func.now()`` (auth/router.py)
    before ``create_access_token`` / ``create_refresh_token``
  - OAuth login: the same assignment, same ordering (auth/oauth/router.py)
  - rotation: an explicit ``SELECT ... FOR UPDATE`` on the owner row, added
    deliberately by fix(#1446)

Only two orderings exist and both are correct: the login finishes first and
the revocation's UPDATE sees and revokes its row, or the login blocks and
completes wholly after the commit, as a successor whose credentials all carry
the new epoch.

WHY THIS TEST EXISTS. On the rotation path the serialization is deliberate and
commented as such. On the login paths it is ACCIDENTAL, and it is load-bearing
anyway. It rests on two things that look like implementation detail:

  1. ``last_login_at`` being assigned before the tokens are minted, so there is
     a pending write to autoflush at all. Moving that assignment after the
     mint, or writing it in a separate transaction, removes the lock entirely.
  2. ``create_access_token`` re-SELECTing ``token_version`` instead of reading
     it off the User row the caller already loaded. That query is what the
     pending write autoflushes into. Its own comment calls it "a safe extra
     query - correctness over micro-optimisation", which names it as an
     optimisation target: deleting it is exactly the change a reviewer would
     wave through, and it would move the version read in front of the lock.

Either edit silently opens the window #1459 imagined, with no test failing and
no reviewer prompted to think about revocation. This test fails instead.
"""

import uuid

import anyio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import RefreshToken

PASSWORD = "TestPass1234!"  # SEC-S16: 12 chars, 3 character classes


async def _create_user(client: AsyncClient, admin_headers: dict) -> tuple[str, str]:
    """Create a throwaway local user; return (user_id, username)."""
    username = f"serial_{uuid.uuid4().hex[:8]}"
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


async def _newest_refresh_row(session: AsyncSession, user_id) -> RefreshToken:
    """Re-read with ``populate_existing`` so a Core UPDATE elsewhere in the
    request cannot be masked by a cached instance, and without expiring the
    rest of the session (a blanket ``expire_all()`` makes any other ORM object
    the test holds reload lazily and raise ``MissingGreenlet`` under asyncio).
    """
    rows = (
        (
            await session.execute(
                select(RefreshToken)
                .where(RefreshToken.user_id == uuid.UUID(str(user_id)))
                .order_by(RefreshToken.created_at)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    return rows[-1]


class TestLoginIsSerializedAgainstRevocation:
    async def test_a_login_racing_a_logout_is_revoked_or_a_clean_successor(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """Force the interleaving deterministically, then assert the outcome.

        The logout handler runs ``revoke_all_tokens(commit=False)`` and then
        ``audit_emit`` before its single commit, so stalling ``audit_emit``
        holds the owner-row lock and the uncommitted revocation open while a
        login is fired underneath it. Without the serialization this test
        guards, that login reads the pre-bump version and lands a live row.
        """
        import app.modules.audit.service as audit_mod

        user_id, username = await _create_user(client, admin_auth_header)
        first = await _login(client, username)
        original_emit = audit_mod.audit_emit

        # fix(#1460 codex): synchronize on the lock actually being held, not on
        # elapsed time. A sleep long enough on a warm machine is not long
        # enough under CI connection contention, and a login that slips in
        # BEFORE the logout takes its lock gets revoked normally, which used to
        # satisfy this test through an early return. That made the guard pass
        # vacuously in exactly the conditions where it is hardest to notice,
        # including with the serialization removed. audit_emit runs after
        # revoke_all_tokens and before the commit, so entering it proves the
        # lock is held and the revocation is staged but not yet durable.
        lock_held = anyio.Event()

        async def _stalled_emit(*args, **kwargs):
            result = await original_emit(*args, **kwargs)
            lock_held.set()
            await anyio.sleep(1.5)
            return result

        monkeypatch.setattr(audit_mod, "audit_emit", _stalled_emit)
        results: dict = {}

        async def _logout():
            resp = await client.post(
                "/auth/logout/",
                headers={"Authorization": f"Bearer {first['access_token']}"},
            )
            results["logout"] = resp.status_code

        async def _login_racing():
            # Fail loudly rather than hang if the logout never reaches the
            # stall (e.g. it 401s), which would otherwise look like a timeout.
            with anyio.fail_after(30):
                await lock_held.wait()
            resp = await client.post(
                "/auth/login", data={"username": username, "password": PASSWORD}
            )
            results["login"] = resp.status_code
            results["tokens"] = resp.json() if resp.status_code == 200 else None

        async with anyio.create_task_group() as tg:
            tg.start_soon(_logout)
            tg.start_soon(_login_racing)
        monkeypatch.undo()

        assert results["logout"] == 204
        racing = await _newest_refresh_row(test_db_session, user_id)

        # The login provably began after the lock was taken, so the revocation's
        # UPDATE had already run and cannot have seen this row. Asserting that,
        # rather than tolerating it, is what stops a mis-ordered run from
        # passing without exercising anything. The other ordering has its own
        # test below.
        assert not racing.revoked, (
            "the racing login's row was revoked, so it committed before the "
            "revocation's UPDATE despite starting after the lock was held; the "
            "interleaving this test needs did not happen and nothing was proven"
        )

        # It therefore completed after the revocation committed, read
        # post-revocation state, and is an ordinary successor. Both of its
        # credentials must work. A failure here means it minted from
        # pre-revocation state and kept a live credential, which is the
        # zombie-session shape #1459 described.
        tokens = results["tokens"]
        assert tokens is not None, "an unrevoked row implies the login succeeded"

        me = await client.get(
            "/auth/me/",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert me.status_code == 200, (
            "the racing login's own access token must authenticate; a 401 here "
            "means it read the pre-bump token_version, so issuance is no longer "
            "serialized against revocation - see this module's docstring"
        )

        rotated = await client.post(
            "/auth/refresh/", json={"refresh_token": tokens["refresh_token"]}
        )
        assert rotated.status_code == 200, rotated.text

    async def test_a_login_that_finishes_first_is_revoked_by_the_logout(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The other ordering, without any stall: a login that commits before
        the revocation runs is inside the set the revocation can see."""
        user_id, username = await _create_user(client, admin_auth_header)
        first = await _login(client, username)
        second = await _login(client, username)

        resp = await client.post(
            "/auth/logout/",
            headers={"Authorization": f"Bearer {second['access_token']}"},
        )
        assert resp.status_code == 204, resp.text

        assert (await _newest_refresh_row(test_db_session, user_id)).revoked
        for token in (first["refresh_token"], second["refresh_token"]):
            assert (
                await client.post("/auth/refresh/", json={"refresh_token": token})
            ).status_code == 401


class TestTheSerializationPointsStillExist:
    """Structural guards on the two incidental mechanisms above.

    The behavioural test needs a forced interleaving to fail, which makes it
    the slower and less obvious signal. These name the exact edits that would
    break it, so the failure arrives with its cause attached.
    """

    def test_login_assigns_last_login_at_before_minting_tokens(self):
        from pathlib import Path

        for rel in (
            "app/modules/auth/router.py",
            "app/modules/auth/oauth/router.py",
        ):
            source = (Path(__file__).resolve().parents[1] / rel).read_text()
            assign = source.find("last_login_at = func.now()")
            mint = source.find("create_refresh_token(")
            assert assign != -1, f"{rel}: last_login_at assignment not found"
            assert mint != -1, f"{rel}: create_refresh_token call not found"
            assert assign < mint, (
                f"{rel}: the pending last_login_at write must precede token "
                "issuance. It is what queues this login behind a concurrent "
                "revocation's owner-row lock (fix(#1459)); minting first lets "
                "the login read a token_version the revocation is about to bump."
            )

    def test_create_access_token_still_queries_the_database(self):
        """The autoflush trigger, asserted as the mechanism rather than as a
        literal: any query will flush the pending write, so a rewrite of the
        SELECT is fine and only its REMOVAL breaks the invariant."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "app/modules/auth/service.py"
        ).read_text()
        start = source.find("async def create_access_token")
        end = source.find("def create_download_token")
        assert start != -1 and end > start
        body = source[start:end]
        assert "self.db.execute(" in body and "token_version" in body, (
            "create_access_token must read token_version through a database "
            "query rather than off an already-loaded User row. That query is "
            "what the pending last_login_at write autoflushes into, and the "
            "autoflush is what puts a login behind a concurrent revocation's "
            "owner-row lock (fix(#1459)). The comment on it calls it 'a safe "
            "extra query', which marks it as an optimisation target; it is "
            "not one, and removing it opens a revocation-bypass window."
        )
