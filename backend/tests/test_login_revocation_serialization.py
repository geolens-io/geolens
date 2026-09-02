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

fix(#1715): half of that is no longer accidental. Admin password reset needs a
login to see the reset's write, so ``LocalAuthProvider.authenticate()`` takes an
explicit ``SELECT ... FOR NO KEY UPDATE`` on the account row before verifying
the hash. A racing password login now queues there, one step earlier than
before and ahead of the ``token_version`` read rather than just ahead of the
mint, so on that path the window is shut by construction.

The accidental mechanism is still the only thing holding the OAuth path, which
has no such lock, so both structural guards below still matter and both are
kept. What changed here is only WHERE a blocked login is observed: the stall
signals from ``authenticate`` instead of ``create_access_token``, because the
login can no longer reach the latter while the lock it is waiting for is the
one the stall is holding.
"""

import uuid

import anyio
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import RefreshToken
from app.modules.auth.providers.local import LocalAuthProvider

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

        # fix(#1460 codex): both ends of the window are synchronized on events,
        # not on elapsed time. Neither side may drift out of the interleaving.
        #
        # Start: audit_emit runs after revoke_all_tokens and before the commit,
        # so entering it proves the lock is held and the revocation is staged
        # but not durable. A login released by a timer instead could slip in
        # BEFORE the lock was taken, get revoked normally, and satisfy the test
        # without exercising anything.
        #
        # End: the stall must not expire on a timer either, or a login delayed
        # past it (CI contention) arrives after the commit, legitimately reads
        # post-revocation state, and passes for the wrong reason. So the
        # revocation is held uncommitted until the login's write is OBSERVED
        # waiting on the lock, in pg_stat_activity, over a third connection.
        # Entering issuance is not sufficient evidence on its own: it proves
        # the version read was about to happen, not that it is blocked, and any
        # fixed margin bridging that gap fails under pool contention in exactly
        # the case the margin exists to catch.
        lock_held = anyio.Event()
        login_reached_the_lock = anyio.Event()
        original_authenticate = LocalAuthProvider.authenticate

        async def _signalling_authenticate(self, *args, **kwargs):
            # Signal BEFORE delegating, so the signal cannot depend on the very
            # lock this is about to wait for.
            #
            # fix(#1715): this used to wrap create_access_token, because the
            # login blocked at the autoflushed last_login_at write that its
            # version re-SELECT triggered. authenticate() now takes an explicit
            # SELECT ... FOR NO KEY UPDATE on the account row, so the login
            # blocks HERE instead, one step earlier and before it reads
            # token_version at all. Signalling from create_access_token became
            # unreachable: the login could not get there without the lock the
            # stall was holding while waiting for the signal, so the pair
            # deadlocked and both died on the 30s deadline.
            login_reached_the_lock.set()
            return await original_authenticate(self, *args, **kwargs)

        async def _login_write_is_waiting_on_the_lock() -> bool:
            """True once a backend is blocked on a lock inside the racing login.

            fix(#1715): still matched by ``last_login_at`` without change. The
            login now blocks on its locking SELECT of the account row, and that
            statement lists every user column, ``last_login_at`` among them, so
            the same predicate identifies the new waiter as well as the old
            autoflushed UPDATE. The OAuth path, which has no explicit lock,
            still blocks on that UPDATE.

            Read over ``test_db_session``, a connection belonging to neither
            transaction in the race, because both of theirs are occupied.
            ``pg_stat_activity`` reports live shared state rather than an MVCC
            snapshot, so an open transaction here does not hide the waiter.
            """
            waiting = await test_db_session.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND pid <> pg_backend_pid() "
                    "AND state = 'active' "
                    "AND wait_event_type = 'Lock' "
                    "AND query ILIKE '%last_login_at%'"
                )
            )
            return waiting.scalar_one() > 0

        async def _stalled_emit(db, event, *args, **kwargs):
            result = await original_emit(db, event, *args, **kwargs)
            # Only the logout's call holds the lock. The racing login emits its
            # own user.login.success audit through this same patched symbol,
            # and stalling that one waits for a lock waiter that has already
            # come and gone, so the login hangs until fail_after fires. A
            # sleep-based stall hid this by merely delaying the login.
            if getattr(event, "action", None) != "user.logout":
                return result
            lock_held.set()
            with anyio.fail_after(30):
                await login_reached_the_lock.wait()
                while not await _login_write_is_waiting_on_the_lock():
                    await anyio.sleep(0.05)
            return result

        monkeypatch.setattr(audit_mod, "audit_emit", _stalled_emit)
        monkeypatch.setattr(LocalAuthProvider, "authenticate", _signalling_authenticate)
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
            # fix(#1460 codex): compare against create_access_token, NOT
            # create_refresh_token. The boundary that matters is the version
            # re-SELECT, because that is the query the pending write
            # autoflushes into. Measuring against the refresh mint leaves a gap
            # exactly the width of the two calls: an assignment moved BETWEEN
            # them still precedes create_refresh_token and passes, while the
            # access token has already been minted from pre-revocation state.
            # The behavioural test above only drives /auth/login, so an OAuth
            # reorder into that gap would be caught by nothing.
            mint = source.find("create_access_token(")
            assert assign != -1, f"{rel}: last_login_at assignment not found"
            assert mint != -1, f"{rel}: create_access_token call not found"
            assert assign < mint, (
                f"{rel}: the pending last_login_at write must precede "
                "create_access_token. Its version re-SELECT is what flushes "
                "that write into a concurrent revocation's owner-row lock "
                "queue (fix(#1459)); minting first lets the login read a "
                "token_version the revocation is about to bump."
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
