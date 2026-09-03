"""fix(#1778): group_role_mapping is live, not a one-shot at account creation.

Codebase audit 2026-08-30, "OAuth role is bound once at JIT creation and never
re-evaluated -- group_role_mapping can grant a role but can never revoke one".

_resolve_role ran only on the login that created the account. Removing someone
from the IdP group, or offboarding them and re-onboarding a different person
under a recycled group name, never demoted the GeoLens account: the role granted
on day one stood until an admin edited it by hand. The field's description
("JSON object mapping IdP group names to GeoLens roles. First match wins") and
both UI hints read as a live mapping.

The four preconditions in _reconcile_mapped_role are each tested here, because
each of them is what stops a login from taking a role away that the IdP never
said anything about.

Counterfactual: delete the _reconcile_mapped_role call from the returning-user
branch of find_or_create_oauth_user and
test_a_returning_user_is_demoted_when_the_group_is_gone fails with the account
still holding admin.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.core.edition import init_edition, is_enterprise
from app.modules.audit.models import AuditLog
from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.oauth import service as oauth_service
from app.modules.auth.oauth.encryption import encrypt_secret
from app.modules.auth.oauth.models import OAuthProvider
from app.modules.auth.oauth.service import find_or_create_oauth_user
from app.modules.auth.providers.local import hash_password

pytestmark = pytest.mark.anyio


@pytest.fixture
def enterprise():
    """init_edition is process-global; restore whatever it was."""
    was_enterprise = is_enterprise()
    init_edition(["enterprise"])
    yield
    init_edition(["enterprise"] if was_enterprise else [])


@pytest.fixture(autouse=True)
def _registration_on(monkeypatch):
    """fix(#1778): the sibling gate would otherwise refuse the first login that
    sets these cases up. That gate has its own tests."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        oauth_service.REGISTRATION_ENABLED,
        "get_uncached",
        AsyncMock(return_value=True),
    )


async def _provider(db, **overrides) -> OAuthProvider:
    suffix = uuid.uuid4().hex[:6]
    fields = dict(
        slug=f"role-reeval-{suffix}",
        display_name="Role Reeval Provider",
        provider_type="oidc",
        client_id=f"client-{suffix}",
        client_secret_encrypted=encrypt_secret("test-secret"),
        scopes="openid profile email",
        default_role="viewer",
        group_claim="groups",
        group_role_mapping={"gis-admins": "admin"},
        enabled=True,
    )
    fields.update(overrides)
    provider = OAuthProvider(**fields)
    db.add(provider)
    await db.flush()
    await db.commit()
    return provider


def _userinfo(sub: str, groups=None, **overrides) -> dict:
    info = {
        "sub": sub,
        "email": f"{sub}@example.com",
        "email_verified": True,
        "name": "Reeval User",
    }
    if groups is not None:
        info["groups"] = groups
    info.update(overrides)
    return info


async def _role_names(db, user_id) -> set[str]:
    rows = await db.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return set(rows.scalars().all())


async def test_a_returning_user_is_demoted_when_the_group_is_gone(
    client, test_db_session, enterprise
):
    provider = await _provider(test_db_session)
    sub = f"demote-{uuid.uuid4().hex[:8]}"

    created = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["gis-admins"]), {}
    )
    await test_db_session.commit()
    assert await _role_names(test_db_session, created.id) == {"admin"}

    # Offboarded from the IdP group; the IdP still asserts the claim.
    returning = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["everyone"]), {}
    )
    await test_db_session.commit()
    assert returning.id == created.id
    assert await _role_names(test_db_session, created.id) == {"viewer"}


async def test_a_returning_user_is_promoted_when_the_group_is_added(
    client, test_db_session, enterprise
):
    provider = await _provider(test_db_session)
    sub = f"promote-{uuid.uuid4().hex[:8]}"

    created = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["everyone"]), {}
    )
    await test_db_session.commit()
    assert await _role_names(test_db_session, created.id) == {"viewer"}

    await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["gis-admins"]), {}
    )
    await test_db_session.commit()
    assert await _role_names(test_db_session, created.id) == {"admin"}


async def test_the_change_is_recorded(client, test_db_session, enterprise):
    provider = await _provider(test_db_session)
    sub = f"audited-{uuid.uuid4().hex[:8]}"

    created = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["gis-admins"]), {}
    )
    await test_db_session.commit()

    await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["everyone"]), {}
    )
    await test_db_session.commit()

    rows = (
        (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "oauth.role.changed",
                    AuditLog.user_id == created.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows, "a silent demotion is the thing that made this hard to notice"
    details = rows[0].details or {}
    assert details["previous_roles"] == ["admin"]
    assert details["new_role"] == "viewer"
    assert details["provider_slug"] == provider.slug


async def test_no_mapping_configured_leaves_a_local_promotion_alone(
    client, test_db_session, enterprise
):
    """With no mapping the operator has said nothing about roles, so an admin
    promoted in the GeoLens UI must survive every subsequent login."""
    provider = await _provider(test_db_session, group_role_mapping=None)
    sub = f"unmapped-{uuid.uuid4().hex[:8]}"

    created = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["everyone"]), {}
    )
    await test_db_session.commit()

    admin_role = await test_db_session.scalar(select(Role).where(Role.name == "admin"))
    created.roles = [admin_role]
    await test_db_session.commit()

    await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["everyone"]), {}
    )
    await test_db_session.commit()
    assert await _role_names(test_db_session, created.id) == {"admin"}


async def test_an_omitted_groups_claim_does_not_demote(
    client, test_db_session, enterprise
):
    """No assertion is not evidence of no membership. _resolve_role(None, ...)
    returns default_role, so acting on an omitted claim would demote everyone
    who signed in while the IdP was misconfigured."""
    provider = await _provider(test_db_session)
    sub = f"noclaim-{uuid.uuid4().hex[:8]}"

    created = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["gis-admins"]), {}
    )
    await test_db_session.commit()
    assert await _role_names(test_db_session, created.id) == {"admin"}

    await find_or_create_oauth_user(test_db_session, provider, _userinfo(sub), {})
    await test_db_session.commit()
    assert await _role_names(test_db_session, created.id) == {"admin"}


async def test_a_local_account_linked_by_email_keeps_its_roles(
    client, test_db_session, enterprise
):
    """The account is the GeoLens admin's, not the provider's."""
    provider = await _provider(test_db_session)
    username = f"localacct_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"

    admin_role = await test_db_session.scalar(select(Role).where(Role.name == "admin"))
    local = User(
        username=username,
        email=email,
        email_verified=True,
        password_hash=hash_password("TestPass1234!"),
        auth_provider="local",
        is_active=True,
        status="active",
        roles=[admin_role],
    )
    test_db_session.add(local)
    await test_db_session.commit()

    linked = await find_or_create_oauth_user(
        test_db_session,
        provider,
        _userinfo(f"link-{uuid.uuid4().hex[:8]}", ["everyone"], email=email),
        {},
    )
    await test_db_session.commit()
    assert linked.id == local.id

    # A second login, now a returning user through the OAuthAccount link.
    await find_or_create_oauth_user(
        test_db_session,
        provider,
        _userinfo(f"link-{uuid.uuid4().hex[:8]}", ["everyone"], email=email),
        {},
    )
    await test_db_session.commit()
    assert await _role_names(test_db_session, local.id) == {"admin"}


async def test_community_ignores_the_mapping(client, test_db_session):
    """Group mapping is an enterprise capability; the JIT path already ignores
    the column outside it, and so must the re-evaluation."""
    init_edition([])
    provider = await _provider(test_db_session)
    sub = f"community-{uuid.uuid4().hex[:8]}"

    created = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["gis-admins"]), {}
    )
    await test_db_session.commit()
    assert await _role_names(test_db_session, created.id) == {"viewer"}

    admin_role = await test_db_session.scalar(select(Role).where(Role.name == "admin"))
    created.roles = [admin_role]
    await test_db_session.commit()

    await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["everyone"]), {}
    )
    await test_db_session.commit()
    assert await _role_names(test_db_session, created.id) == {"admin"}


# ---------------------------------------------------------------------------
# fix(#1778 codex r1): the reconciliation must be the SAME role change every
# other route makes, not a weaker copy of it.
#
# Counterfactuals, each run: assign user.roles directly instead of calling
# AdminService.set_role_from_identity_provider and the sole-admin and key-epoch
# tests fail; drop the _reconcile_mapped_role call from the verified-email
# branch and the cross-provider test fails.
# ---------------------------------------------------------------------------


async def _active_admin_count(db) -> int:
    rows = await db.execute(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, UserRole.role_id == Role.id)
        .where(Role.name == "admin", User.status == "active", User.is_active.is_(True))
    )
    return len(set(rows.scalars().all()))


@asynccontextmanager
async def _only_admin_is(db, keep_id):
    """Strip admin from every other account for the body, then put it back.

    The seeded GEOLENS_ADMIN account is one of the accounts demoted here, and it
    is cluster-global state every other test in this database depends on, so the
    restore runs in a finally.
    """
    viewer = await db.scalar(select(Role).where(Role.name == "viewer"))
    admin_role = await db.scalar(select(Role).where(Role.name == "admin"))
    rows = await db.execute(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, UserRole.role_id == Role.id)
        .where(Role.name == "admin", User.id != keep_id)
    )
    demoted = list(rows.scalars().unique().all())
    for other in demoted:
        other.roles = [viewer]
    await db.commit()
    try:
        yield
    finally:
        for other in demoted:
            other.roles = [admin_role]
        await db.commit()


async def test_the_sole_admin_is_not_demoted_by_an_empty_groups_claim(
    client, test_db_session, enterprise
):
    """The last-admin invariant belongs to every demotion route, this one
    included. Assigning the default role directly would remove the deployment's
    only way back in on the say-so of an IdP assertion."""
    provider = await _provider(test_db_session)
    sub = f"soleadmin-{uuid.uuid4().hex[:8]}"

    created = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["gis-admins"]), {}
    )
    await test_db_session.commit()
    assert await _role_names(test_db_session, created.id) == {"admin"}

    async with _only_admin_is(test_db_session, created.id):
        assert await _active_admin_count(test_db_session) == 1

        returning = await find_or_create_oauth_user(
            test_db_session, provider, _userinfo(sub, []), {}
        )
        await test_db_session.commit()

        assert returning.id == created.id
        assert await _role_names(test_db_session, created.id) == {"admin"}, (
            "an IdP assertion removed the last admin"
        )

        refusals = (
            (
                await test_db_session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "oauth.role.change_refused",
                        AuditLog.user_id == created.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert refusals, "a refused demotion has to be visible to an operator"
        details = refusals[0].details or {}
        assert details["reason"] == "last_admin"
        assert details["mapped_role"] == "viewer"
        assert details["current_roles"] == ["admin"]


async def test_a_second_admin_present_lets_the_demotion_through(
    client, test_db_session, enterprise
):
    """The invariant refuses only the LAST admin. With another one active the
    mapped demotion applies as normal.

    The second admin is created here rather than assumed from the seeded
    GEOLENS_ADMIN account, so this does not turn red because some other module
    left that account demoted."""
    provider = await _provider(test_db_session)
    sub = f"notlast-{uuid.uuid4().hex[:8]}"

    created = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["gis-admins"]), {}
    )
    await test_db_session.commit()
    assert await _role_names(test_db_session, created.id) == {"admin"}

    admin_role = await test_db_session.scalar(select(Role).where(Role.name == "admin"))
    spare = User(
        username=f"spareadmin_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("TestPass1234!"),
        auth_provider="local",
        is_active=True,
        status="active",
        roles=[admin_role],
    )
    test_db_session.add(spare)
    await test_db_session.commit()
    assert await _active_admin_count(test_db_session) >= 2

    await find_or_create_oauth_user(test_db_session, provider, _userinfo(sub, []), {})
    await test_db_session.commit()
    assert await _role_names(test_db_session, created.id) == {"viewer"}


async def test_a_mapped_promotion_bumps_the_key_epoch(
    client, test_db_session, enterprise
):
    """fix(#821)'s rule is that a role change invalidates keys minted under the
    old role. An API key minted while the account was a viewer must not silently
    become an admin key after the next OAuth login."""
    provider = await _provider(test_db_session)
    sub = f"epoch-{uuid.uuid4().hex[:8]}"

    created = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["everyone"]), {}
    )
    await test_db_session.commit()
    assert await _role_names(test_db_session, created.id) == {"viewer"}
    epoch_before = await test_db_session.scalar(
        select(User.key_epoch).where(User.id == created.id)
    )

    await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["gis-admins"]), {}
    )
    await test_db_session.commit()

    epoch_after = await test_db_session.scalar(
        select(User.key_epoch).where(User.id == created.id)
    )
    assert await _role_names(test_db_session, created.id) == {"admin"}
    assert epoch_after > epoch_before, (
        "a key minted as viewer still resolves after the account became admin"
    )


async def test_an_unchanged_role_does_not_bump_the_key_epoch(
    client, test_db_session, enterprise
):
    """An assertion that agrees with the current role is not a security event,
    so it must not revoke the account's API keys on every login."""
    provider = await _provider(test_db_session)
    sub = f"idempotent-{uuid.uuid4().hex[:8]}"

    created = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["gis-admins"]), {}
    )
    await test_db_session.commit()
    epoch_before = await test_db_session.scalar(
        select(User.key_epoch).where(User.id == created.id)
    )

    await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["gis-admins"]), {}
    )
    await test_db_session.commit()

    epoch_after = await test_db_session.scalar(
        select(User.key_epoch).where(User.id == created.id)
    )
    assert epoch_after == epoch_before


async def test_the_first_email_linked_login_applies_the_new_provider_mapping(
    client, test_db_session, enterprise
):
    """The verified-email branch is the OTHER return path that yields an
    existing account. Without reconciliation there, an OAuth-provisioned account
    linking to a second provider carries its old role for that whole session."""
    first = await _provider(test_db_session)
    second = await _provider(test_db_session, group_role_mapping={"leads": "editor"})

    email = f"crossprovider-{uuid.uuid4().hex[:8]}@example.com"
    created = await find_or_create_oauth_user(
        test_db_session,
        first,
        _userinfo(f"first-{uuid.uuid4().hex[:8]}", ["gis-admins"], email=email),
        {},
    )
    await test_db_session.commit()
    assert await _role_names(test_db_session, created.id) == {"admin"}

    # First ever login through the SECOND provider: linked by verified email,
    # so the subject-link branch is not the one that runs.
    linked = await find_or_create_oauth_user(
        test_db_session,
        second,
        _userinfo(f"second-{uuid.uuid4().hex[:8]}", ["everyone"], email=email),
        {},
    )
    await test_db_session.commit()

    assert linked.id == created.id
    assert await _role_names(test_db_session, created.id) == {"viewer"}, (
        "the second provider's mapping was ignored on the linking login"
    )


# ---------------------------------------------------------------------------
# fix(#1778 codex r4): two OAuth callbacks for the same account can arrive
# together. Both used to enter set_role_from_identity_provider's PROMOTION
# branch unserialized, and _update_user_role deletes and re-inserts
# catalog.user_roles, whose primary key is (user_id, role_id) -- so the two
# inserts collided and one otherwise valid login failed on a duplicate key.
#
# The promotion branch now takes the same admin-lifecycle advisory lock the
# demotion branch does, which also makes _update_user_role's idempotency check
# load-bearing: the second caller re-reads the roles under the lock, finds the
# promotion already applied, and returns without touching the table.
#
# Counterfactual: move the lock back inside the non-admin branch and
# test_concurrent_mapped_promotions_do_not_collide fails with a UniqueViolation
# on catalog.user_roles.
#
# The SAML overlay reaches this through the SAME call chain: SAML JIT goes
# through find_or_create_oauth_user, whose only role-change path is
# _reconcile_mapped_role -> set_role_from_identity_provider, and that is the
# only caller of it in the tree. So this covers both protocols; there is no
# separate SAML branch to fix.
# ---------------------------------------------------------------------------


async def test_concurrent_mapped_promotions_do_not_collide(
    client, test_db_session, enterprise
):
    """Two simultaneous logins for the same returning viewer whose IdP group now
    maps to admin. Both must succeed, and the account must end up holding
    exactly one role row."""
    import app.core.db as db_module
    from app.modules.admin.service import AdminService

    provider = await _provider(test_db_session)
    sub = f"concurrent-{uuid.uuid4().hex[:8]}"

    created = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["everyone"]), {}
    )
    await test_db_session.commit()
    user_id = created.id
    assert await _role_names(test_db_session, user_id) == {"viewer"}

    # Both callers must have READ the current roles before either writes, which
    # is the state two simultaneous callbacks are actually in. Without a barrier
    # the event loop is free to run one to completion first and the race never
    # happens, which is exactly how the unlocked version passed.
    ready = asyncio.Barrier(2)

    async def promote():
        # Its own session, as a second Uvicorn worker would have.
        async with db_module.async_session() as session:
            user = await session.get(User, user_id)
            await session.refresh(user, attribute_names=["roles"])
            await ready.wait()
            outcome = await AdminService(session).set_role_from_identity_provider(
                user, "admin"
            )
            # _reconcile_mapped_role flushes here, so the INSERT is issued
            # before the commit rather than at it.
            await session.flush()
            await session.commit()
            return outcome

    results = await asyncio.gather(promote(), promote(), return_exceptions=True)

    failures = [r for r in results if isinstance(r, BaseException)]
    assert not failures, f"a concurrent mapped promotion failed: {failures!r}"
    assert all(r.applied for r in results)

    rows = await test_db_session.execute(
        select(UserRole).where(UserRole.user_id == user_id)
    )
    assert len(rows.scalars().all()) == 1
    assert await _role_names(test_db_session, user_id) == {"admin"}

    # fix(#1778 codex r5): exactly ONE of the two actually changed anything, and
    # the other must say so rather than reporting a transition that had already
    # happened. The loser used to return True and its caller emitted a second
    # oauth.role.changed carrying a previous_roles snapshot taken before the
    # winner's write.
    assert sorted(r.changed for r in results) == [False, True], (
        "both concurrent promotions reported a change, so the caller would "
        "audit the same transition twice"
    )
    winner = next(r for r in results if r.changed)
    assert winner.previous_roles == ["viewer"]
    loser = next(r for r in results if not r.changed)
    assert loser.previous_roles == ["admin"], (
        "the loser's previous_roles were captured before the lock, so they "
        "describe a state the winner had already replaced"
    )


async def test_a_second_concurrent_login_emits_no_duplicate_audit_event(
    client, test_db_session, enterprise
):
    """The same race driven through _reconcile_mapped_role, which is what emits
    the audit row, asserting exactly one oauth.role.changed lands.

    Counterfactual: have set_role_from_identity_provider report a change
    unconditionally and this finds two rows for one transition.
    """
    import app.core.db as db_module
    from app.modules.auth.oauth.service import _reconcile_mapped_role

    provider = await _provider(test_db_session)
    sub = f"dupaudit-{uuid.uuid4().hex[:8]}"

    created = await find_or_create_oauth_user(
        test_db_session, provider, _userinfo(sub, ["everyone"]), {}
    )
    await test_db_session.commit()
    user_id = created.id
    assert await _role_names(test_db_session, user_id) == {"viewer"}

    ready = asyncio.Barrier(2)

    async def login():
        async with db_module.async_session() as session:
            user = await session.get(User, user_id)
            await session.refresh(user, attribute_names=["roles"])
            fresh_provider = await session.get(OAuthProvider, provider.id)
            await ready.wait()
            await _reconcile_mapped_role(session, fresh_provider, user, ["gis-admins"])
            await session.commit()

    results = await asyncio.gather(login(), login(), return_exceptions=True)
    failures = [r for r in results if isinstance(r, BaseException)]
    assert not failures, f"a concurrent mapped login failed: {failures!r}"

    rows = (
        (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "oauth.role.changed",
                    AuditLog.user_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, (
        f"expected one oauth.role.changed for one transition, got {len(rows)}"
    )
    assert (rows[0].details or {})["previous_roles"] == ["viewer"]
    assert await _role_names(test_db_session, user_id) == {"admin"}
