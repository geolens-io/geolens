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

import uuid

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
