"""Regression coverage for serialized, internally consistent admin lifecycle state."""

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update

from app.modules.admin.service import AdminService
from app.modules.auth.models import Role, User, UserRole
from tests.conftest import _create_test_user


async def _create_pending_user(session, *, role_name: str | None = None) -> uuid.UUID:
    """Create a committed pending account, optionally with a legacy role."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"pending_lifecycle_{suffix}",
        email=f"pending_lifecycle_{suffix}@example.com",
        password_hash="unused",
        status="pending",
        is_active=False,
    )
    session.add(user)
    await session.flush()
    if role_name is not None:
        role = (
            await session.execute(select(Role).where(Role.name == role_name))
        ).scalar_one()
        session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()
    return user.id


@pytest.mark.anyio
async def test_generic_patch_cannot_disable_calling_admin(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """The generic PATCH path cannot bypass the dedicated self-operation guard."""
    me = await client.get("/auth/me/", headers=admin_auth_header)
    admin_id = me.json()["id"]

    for payload in (
        {"is_active": False},
        {"status": "suspended"},
        {"status": "deactivated"},
    ):
        response = await client.patch(
            f"/admin/users/{admin_id}",
            json=payload,
            headers=admin_auth_header,
        )
        assert response.status_code == 422, response.text

    still_authenticated = await client.get("/auth/me/", headers=admin_auth_header)
    assert still_authenticated.status_code == 200


@pytest.mark.anyio
async def test_explicit_suspend_reactivate_and_legacy_toggle_stay_consistent(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Every supported transition keeps status and is_active synchronized."""
    viewer_headers, viewer_id = await _create_test_user(
        client, admin_auth_header, "viewer"
    )

    suspended = await client.patch(
        f"/admin/users/{viewer_id}",
        json={"status": "suspended"},
        headers=admin_auth_header,
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"
    assert suspended.json()["is_active"] is False
    assert (await client.get("/auth/me/", headers=viewer_headers)).status_code == 401

    audit_resp = await client.get(
        "/admin/audit-logs/",
        params={"action": "user.update"},
        headers=admin_auth_header,
    )
    entries = [
        entry
        for entry in audit_resp.json()["logs"]
        if entry["resource_id"] == viewer_id
    ]
    assert entries
    assert entries[0]["details"]["before"]["status"] == "active"
    assert entries[0]["details"]["after"]["status"] == "suspended"

    reactivated = await client.patch(
        f"/admin/users/{viewer_id}",
        json={"status": "active"},
        headers=admin_auth_header,
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["status"] == "active"
    assert reactivated.json()["is_active"] is True

    legacy_deactivated = await client.patch(
        f"/admin/users/{viewer_id}",
        json={"is_active": False},
        headers=admin_auth_header,
    )
    assert legacy_deactivated.status_code == 200, legacy_deactivated.text
    assert legacy_deactivated.json()["status"] == "deactivated"
    assert legacy_deactivated.json()["is_active"] is False

    legacy_reactivated = await client.patch(
        f"/admin/users/{viewer_id}",
        json={"is_active": True},
        headers=admin_auth_header,
    )
    assert legacy_reactivated.status_code == 200, legacy_reactivated.text
    assert legacy_reactivated.json()["status"] == "active"
    assert legacy_reactivated.json()["is_active"] is True


@pytest.mark.anyio
async def test_pending_role_patch_is_422_and_approval_replaces_legacy_role(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Only approve/reject decide a pending account's authority and state."""
    user_id = await _create_pending_user(test_db_session, role_name="admin")

    patch_response = await client.patch(
        f"/admin/users/{user_id}",
        json={"role": "editor"},
        headers=admin_auth_header,
    )
    assert patch_response.status_code == 422, patch_response.text
    assert "approved or rejected" in patch_response.json()["detail"]

    deactivate_response = await client.post(
        f"/admin/users/{user_id}/deactivate/",
        headers=admin_auth_header,
    )
    assert deactivate_response.status_code == 409, deactivate_response.text
    assert "approved or rejected" in deactivate_response.json()["detail"]

    approved = await client.post(
        f"/admin/users/{user_id}/approve/",
        json={"role": "viewer"},
        headers=admin_auth_header,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "active"
    assert approved.json()["roles"] == ["viewer"]

    role_names = set(
        (
            await test_db_session.execute(
                select(Role.name)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user_id)
            )
        ).scalars()
    )
    assert role_names == {"viewer"}

    already_decided = await client.post(
        f"/admin/users/{user_id}/approve/",
        json={"role": "editor"},
        headers=admin_auth_header,
    )
    assert already_decided.status_code == 409, already_decided.text

    reject_after_approval = await client.post(
        f"/admin/users/{user_id}/reject/",
        headers=admin_auth_header,
    )
    assert reject_after_approval.status_code == 409, reject_after_approval.text

    missing_id = uuid.uuid4()
    missing_approval = await client.post(
        f"/admin/users/{missing_id}/approve/",
        json={"role": "viewer"},
        headers=admin_auth_header,
    )
    missing_rejection = await client.post(
        f"/admin/users/{missing_id}/reject/",
        headers=admin_auth_header,
    )
    assert missing_approval.status_code == 404, missing_approval.text
    assert missing_rejection.status_code == 404, missing_rejection.text


@pytest.mark.anyio
async def test_concurrent_service_approvals_serialize_to_one_role(client: AsyncClient):
    """A second approval waits for the first and then reports a conflict."""
    import app.core.db as db_module

    async with db_module.async_session() as setup:
        user_id = await _create_pending_user(setup)

    async with (
        db_module.async_session() as first_session,
        db_module.async_session() as second_session,
    ):
        await AdminService(first_session).approve_user(user_id, "viewer")

        async def competing_approval():
            try:
                return await AdminService(second_session).approve_user(
                    user_id, "editor"
                )
            except Exception as exc:
                return exc

        second_approval = asyncio.create_task(competing_approval())

        # The first transaction still owns the user row. The competing decision
        # must remain blocked until that transaction commits.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(second_approval), timeout=0.1)

        await first_session.commit()
        # The app fixture reloads application modules after test collection,
        # so compare the domain error semantically rather than against the
        # stale class object imported with AdminService.
        outcome = await second_approval
        assert outcome.__class__.__name__ == "PendingUserTransitionConflict"
        assert "approval is no longer available" in str(outcome)
        await second_session.rollback()

    async with db_module.async_session() as verify:
        user = (
            await verify.execute(select(User).where(User.id == user_id))
        ).scalar_one()
        roles = set(
            (
                await verify.execute(
                    select(Role.name)
                    .join(UserRole, UserRole.role_id == Role.id)
                    .where(UserRole.user_id == user_id)
                )
            ).scalars()
        )
        assert user.status == "active"
        assert user.is_active is True
        assert roles == {"viewer"}


@pytest.mark.anyio
async def test_approved_user_cannot_be_deleted_by_waiting_rejection(
    client: AsyncClient,
):
    """An approval committed while rejection waits wins permanently."""
    import app.core.db as db_module

    async with db_module.async_session() as setup:
        user_id = await _create_pending_user(setup)

    async with (
        db_module.async_session() as approval_session,
        db_module.async_session() as rejection_session,
    ):
        await AdminService(approval_session).approve_user(user_id, "viewer")

        async def competing_rejection():
            try:
                return await AdminService(rejection_session).reject_user(user_id)
            except Exception as exc:
                return exc

        waiting_rejection = asyncio.create_task(competing_rejection())

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(waiting_rejection), timeout=0.1)

        await approval_session.commit()
        outcome = await waiting_rejection
        assert outcome.__class__.__name__ == "PendingUserTransitionConflict"
        assert "rejection is no longer available" in str(outcome)
        await rejection_session.rollback()

    async with db_module.async_session() as verify:
        user = (
            await verify.execute(select(User).where(User.id == user_id))
        ).scalar_one()
        roles = set(
            (
                await verify.execute(
                    select(Role.name)
                    .join(UserRole, UserRole.role_id == Role.id)
                    .where(UserRole.user_id == user_id)
                )
            ).scalars()
        )
        assert user.status == "active"
        assert user.is_active is True
        assert roles == {"viewer"}


@pytest.mark.anyio
async def test_concurrent_api_approve_reject_has_exactly_one_success(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Approve/reject races cannot both commit or delete an approved account."""
    user_id = await _create_pending_user(test_db_session)

    approve_response, reject_response = await asyncio.gather(
        client.post(
            f"/admin/users/{user_id}/approve/",
            json={"role": "viewer"},
            headers=admin_auth_header,
        ),
        client.post(
            f"/admin/users/{user_id}/reject/",
            headers=admin_auth_header,
        ),
    )

    statuses = [approve_response.status_code, reject_response.status_code]
    assert sum(code in {200, 204} for code in statuses) == 1, (
        approve_response.text,
        reject_response.text,
    )
    assert any(code in {404, 409} for code in statuses)

    test_db_session.expire_all()
    stored_user = (
        await test_db_session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if approve_response.status_code == 200:
        assert reject_response.status_code == 409
        assert stored_user is not None
        assert stored_user.status == "active"
        role_names = set(
            (
                await test_db_session.execute(
                    select(Role.name)
                    .join(UserRole, UserRole.role_id == Role.id)
                    .where(UserRole.user_id == user_id)
                )
            ).scalars()
        )
        assert role_names == {"viewer"}
    else:
        assert reject_response.status_code == 204
        # A competing approval sees either the deleted row (404) or, if the
        # backend returns a post-wait row version, the decided state (409).
        assert approve_response.status_code in {404, 409}
        assert stored_user is None


@pytest.mark.anyio
async def test_concurrent_admin_reducers_leave_one_viable_admin(
    client: AsyncClient,
):
    """Cross-row reductions serialize; an inactive admin role does not count."""
    import app.core.db as db_module

    first_id: uuid.UUID | None = None
    second_id: uuid.UUID | None = None
    original_states: dict[uuid.UUID, tuple[str, bool]] = {}

    try:
        async with db_module.async_session() as setup:
            service = AdminService(setup)
            suffix = uuid.uuid4().hex[:8]
            first = await service.create_user(
                f"concurrent_admin_a_{suffix}", "TestPass1234!", role_name="admin"
            )
            second = await service.create_user(
                f"concurrent_admin_b_{suffix}", "TestPass1234!", role_name="admin"
            )
            first_id, second_id = first.id, second.id
            await setup.commit()

            admins = (
                (
                    await setup.execute(
                        select(User)
                        .join(UserRole, User.id == UserRole.user_id)
                        .join(Role, UserRole.role_id == Role.id)
                        .where(Role.name == "admin")
                    )
                )
                .scalars()
                .all()
            )
            for admin in admins:
                if admin.id not in {first_id, second_id}:
                    original_states[admin.id] = (admin.status, admin.is_active)
                    admin.status = "suspended"
                    admin.is_active = False
            await setup.commit()

        assert first_id is not None and second_id is not None

        async def deactivate(target_id: uuid.UUID, actor_id: uuid.UUID) -> str:
            async with db_module.async_session() as session:
                try:
                    await AdminService(session).deactivate_user(target_id, actor_id)
                    await session.commit()
                    return "deactivated"
                except ValueError as exc:
                    await session.rollback()
                    return str(exc)

        outcomes = await asyncio.gather(
            deactivate(first_id, second_id),
            deactivate(second_id, first_id),
        )
        assert outcomes.count("deactivated") == 1
        assert sum("last admin" in outcome for outcome in outcomes) == 1

        async with db_module.async_session() as verify:
            viable_ids = set(
                (
                    await verify.execute(
                        select(User.id)
                        .join(UserRole, User.id == UserRole.user_id)
                        .join(Role, UserRole.role_id == Role.id)
                        .where(
                            Role.name == "admin",
                            User.status == "active",
                            User.is_active == True,  # noqa: E712
                        )
                    )
                ).scalars()
            )
            assert viable_ids == ({first_id, second_id} & viable_ids)
            assert len(viable_ids) == 1

            # The deactivated peer still owns an admin role, but cannot satisfy
            # the last-admin guard for a subsequent (sequential) reduction.
            remaining_id = viable_ids.pop()
            with pytest.raises(ValueError, match="last admin"):
                await AdminService(verify).deactivate_user(
                    remaining_id, current_user_id=uuid.uuid4()
                )
            await verify.rollback()
    finally:
        async with db_module.async_session() as cleanup:
            for user_id, (status, is_active) in original_states.items():
                await cleanup.execute(
                    update(User)
                    .where(User.id == user_id)
                    .values(status=status, is_active=is_active)
                )
            ids = [user_id for user_id in (first_id, second_id) if user_id is not None]
            if ids:
                await cleanup.execute(delete(User).where(User.id.in_(ids)))
            await cleanup.commit()
