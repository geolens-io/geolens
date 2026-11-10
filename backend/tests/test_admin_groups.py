"""Admin API for sharing groups: authorization and each operation."""

import asyncio
import time
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.audit.models import AuditLog
from app.modules.auth import groups as group_service
from app.modules.auth.models import ApiKey, Group, GroupMember

from tests.conftest import _create_test_user

_GROUP = "/admin/groups/{}"
_MEMBERS = "/admin/groups/{}/members/"
_MEMBER = "/admin/groups/{}/members/{}"


def _name() -> str:
    return f"group-{uuid.uuid4().hex[:8]}"


async def _create_group(client: AsyncClient, headers: dict, name: str | None = None):
    resp = await client.post(
        "/admin/groups/", json={"name": name or _name()}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _member_rows(db: AsyncSession, group_id: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(GroupMember)
            .where(GroupMember.group_id == uuid.UUID(group_id))
        )
    ).scalar_one()


def _every_route(group_id: str, user_id: str) -> list[tuple[str, str, dict | None]]:
    """Every route form, the hidden no-slash aliases included."""
    members = _MEMBERS.format(group_id)
    return [
        ("GET", "/admin/groups/", None),
        ("GET", "/admin/groups", None),
        ("POST", "/admin/groups/", {"name": _name()}),
        ("POST", "/admin/groups", {"name": _name()}),
        ("GET", _GROUP.format(group_id), None),
        ("PATCH", _GROUP.format(group_id), {"name": _name()}),
        ("DELETE", _GROUP.format(group_id), None),
        ("GET", members, None),
        ("GET", members.rstrip("/"), None),
        ("POST", members, {"user_ids": [user_id]}),
        ("POST", members.rstrip("/"), {"user_ids": [user_id]}),
        ("DELETE", _MEMBER.format(group_id, user_id), None),
    ]


async def _wait_until_blocking(holder: AsyncSession) -> None:
    """Return once another backend waits on a lock ``holder`` holds."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        # The activity view is snapshotted once per transaction.
        await holder.execute(text("SELECT pg_stat_clear_snapshot()"))
        blocked = (
            await holder.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE pg_backend_pid() = ANY(pg_blocking_pids(pid))"
                )
            )
        ).scalar_one()
        if blocked:
            return
        await asyncio.sleep(0.1)
    pytest.fail("the add never waited on the held lock")


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["editor", "viewer"])
async def test_non_admin_is_refused_every_route(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    role: str,
):
    group = await _create_group(client, admin_auth_header)
    member_header, member_id = await _create_test_user(
        client, admin_auth_header, "viewer"
    )
    await client.post(
        _MEMBERS.format(group["id"]),
        json={"user_ids": [member_id]},
        headers=admin_auth_header,
    )
    headers, _ = await _create_test_user(client, admin_auth_header, role)

    for method, url, body in _every_route(group["id"], member_id):
        resp = await client.request(method, url, json=body, headers=headers)
        assert resp.status_code == 403, (method, url, resp.status_code)

    still = await client.get(_GROUP.format(group["id"]), headers=admin_auth_header)
    assert still.json()["name"] == group["name"]
    assert still.json()["member_count"] == 1


@pytest.mark.anyio
async def test_anonymous_is_refused_every_route(
    client: AsyncClient, admin_auth_header: dict
):
    group = await _create_group(client, admin_auth_header)
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")

    for method, url, body in _every_route(group["id"], user_id):
        resp = await client.request(method, url, json=body)
        assert resp.status_code == 401, (method, url, resp.status_code)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer not-a-token"},
        {"X-Api-Key": "glk_not-a-real-key"},
    ],
)
async def test_invalid_credentials_are_refused_every_route(
    client: AsyncClient, admin_auth_header: dict, headers: dict
):
    group = await _create_group(client, admin_auth_header)
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")

    for method, url, body in _every_route(group["id"], user_id):
        resp = await client.request(method, url, json=body, headers=headers)
        assert resp.status_code == 401, (method, url, resp.status_code)


@pytest.mark.anyio
async def test_admin_publish_key_is_refused_every_route(
    client: AsyncClient, admin_auth_header: dict, test_db_session: AsyncSession
):
    minted = await client.post(
        "/auth/api-keys/",
        json={"name": "publish key", "scope": "publish"},
        headers=admin_auth_header,
    )
    assert minted.status_code == 201, minted.text
    publish = {"X-Api-Key": minted.json()["key"]}
    group = await _create_group(client, admin_auth_header)
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")

    try:
        for method, url, body in _every_route(group["id"], user_id):
            resp = await client.request(method, url, json=body, headers=publish)
            assert resp.status_code == 403, (method, url, resp.status_code)
    finally:
        # Even revoked, a publish key makes later downgrade tests refuse to run.
        await test_db_session.execute(
            delete(ApiKey).where(ApiKey.id == uuid.UUID(minted.json()["id"]))
        )
        await test_db_session.commit()


@pytest.mark.anyio
async def test_hosted_tenant_admin_is_refused(
    client: AsyncClient, admin_auth_header: dict, monkeypatch
):
    """Groups are deployment-global, so multi_tenant needs manage_tenants."""
    group = await _create_group(client, admin_auth_header)
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

    resp = await client.get(_GROUP.format(group["id"]), headers=admin_auth_header)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_create_get_and_list(
    client: AsyncClient, admin_auth_header: dict, test_db_session: AsyncSession
):
    name = _name()
    created = await _create_group(client, admin_auth_header, f"  {name} ")
    assert created["name"] == name
    assert created["member_count"] == 0

    got = await client.get(_GROUP.format(created["id"]), headers=admin_auth_header)
    assert got.status_code == 200
    assert got.json()["name"] == name

    listed = await client.get("/admin/groups/?limit=200", headers=admin_auth_header)
    assert listed.status_code == 200
    assert name in {g["name"] for g in listed.json()["groups"]}

    audit = await test_db_session.execute(
        select(AuditLog.details).where(
            AuditLog.action == "group.create",
            AuditLog.resource_id == uuid.UUID(created["id"]),
        )
    )
    assert audit.scalar_one() == {"name": name}


@pytest.mark.anyio
async def test_duplicate_and_blank_names_are_refused(
    client: AsyncClient, admin_auth_header: dict
):
    group = await _create_group(client, admin_auth_header)
    other = await _create_group(client, admin_auth_header)

    dup = await client.post(
        "/admin/groups/", json={"name": group["name"]}, headers=admin_auth_header
    )
    assert dup.status_code == 409

    rename_dup = await client.patch(
        _GROUP.format(other["id"]),
        json={"name": group["name"]},
        headers=admin_auth_header,
    )
    assert rename_dup.status_code == 409

    blank = await client.post(
        "/admin/groups/", json={"name": "   "}, headers=admin_auth_header
    )
    assert blank.status_code == 422


@pytest.mark.anyio
async def test_names_are_nfc_normalized(client: AsyncClient, admin_auth_header: dict):
    stem = _name()
    decomposed = f"{stem}-Cafe\u0301"
    composed = f"{stem}-Caf\u00e9"

    created = await _create_group(client, admin_auth_header, decomposed)
    assert created["name"] == composed

    dup = await client.post(
        "/admin/groups/", json={"name": composed}, headers=admin_auth_header
    )
    assert dup.status_code == 409


@pytest.mark.anyio
async def test_rename(client: AsyncClient, admin_auth_header: dict):
    group = await _create_group(client, admin_auth_header)
    new_name = _name()

    resp = await client.patch(
        _GROUP.format(group["id"]), json={"name": new_name}, headers=admin_auth_header
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == new_name
    got = await client.get(_GROUP.format(group["id"]), headers=admin_auth_header)
    assert got.json()["name"] == new_name


@pytest.mark.anyio
async def test_unknown_group_is_404(client: AsyncClient, admin_auth_header: dict):
    missing = str(uuid.uuid4())
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")
    for method, url, body in _every_route(missing, user_id):
        if url.rstrip("/") == "/admin/groups":
            continue
        resp = await client.request(method, url, json=body, headers=admin_auth_header)
        assert resp.status_code == 404, (method, url, resp.status_code)


@pytest.mark.anyio
async def test_add_list_and_remove_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session: AsyncSession
):
    group = await _create_group(client, admin_auth_header)
    _, first = await _create_test_user(client, admin_auth_header, "viewer")
    _, second = await _create_test_user(client, admin_auth_header, "editor")

    added = await client.post(
        _MEMBERS.format(group["id"]),
        json={"user_ids": [first, second, first]},
        headers=admin_auth_header,
    )
    assert added.status_code == 200
    assert added.json()["member_count"] == 2

    again = await client.post(
        _MEMBERS.format(group["id"]),
        json={"user_ids": [first]},
        headers=admin_auth_header,
    )
    assert again.status_code == 200
    assert again.json()["member_count"] == 2

    members = await client.get(_MEMBERS.format(group["id"]), headers=admin_auth_header)
    assert members.status_code == 200
    assert {m["id"] for m in members.json()["members"]} == {first, second}
    assert members.json()["total"] == 2

    removed = await client.delete(
        _MEMBER.format(group["id"], first), headers=admin_auth_header
    )
    assert removed.status_code == 204
    assert await _member_rows(test_db_session, group["id"]) == 1

    not_member = await client.delete(
        _MEMBER.format(group["id"], first), headers=admin_auth_header
    )
    assert not_member.status_code == 404


@pytest.mark.anyio
async def test_add_with_an_unknown_user_adds_nobody(
    client: AsyncClient, admin_auth_header: dict, test_db_session: AsyncSession
):
    group = await _create_group(client, admin_auth_header)
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")
    unknown = str(uuid.uuid4())

    resp = await client.post(
        _MEMBERS.format(group["id"]),
        json={"user_ids": [user_id, unknown]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["user_ids"] == [unknown]
    assert await _member_rows(test_db_session, group["id"]) == 0


@pytest.mark.anyio
async def test_delete_group_cascades_memberships(
    client: AsyncClient, admin_auth_header: dict, test_db_session: AsyncSession
):
    group = await _create_group(client, admin_auth_header)
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")
    await client.post(
        _MEMBERS.format(group["id"]),
        json={"user_ids": [user_id]},
        headers=admin_auth_header,
    )
    assert await _member_rows(test_db_session, group["id"]) == 1

    resp = await client.delete(_GROUP.format(group["id"]), headers=admin_auth_header)
    assert resp.status_code == 204
    assert await _member_rows(test_db_session, group["id"]) == 0
    gone = await client.get(_GROUP.format(group["id"]), headers=admin_auth_header)
    assert gone.status_code == 404

    user = await client.get(f"/admin/users/{user_id}", headers=admin_auth_header)
    assert user.status_code == 200


@pytest.mark.anyio
async def test_deleting_a_user_removes_their_memberships(
    client: AsyncClient, admin_auth_header: dict, test_db_session: AsyncSession
):
    group = await _create_group(client, admin_auth_header)
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")
    await client.post(
        _MEMBERS.format(group["id"]),
        json={"user_ids": [user_id]},
        headers=admin_auth_header,
    )

    resp = await client.delete(f"/admin/users/{user_id}", headers=admin_auth_header)
    assert resp.status_code == 204
    assert await _member_rows(test_db_session, group["id"]) == 0
    got = await client.get(_GROUP.format(group["id"]), headers=admin_auth_header)
    assert got.json()["member_count"] == 0


async def _audit_details(db: AsyncSession, action: str, group_id: str) -> list:
    rows = await db.execute(
        select(AuditLog.details).where(
            AuditLog.action == action, AuditLog.resource_id == uuid.UUID(group_id)
        )
    )
    return list(rows.scalars().all())


@pytest.mark.anyio
async def test_delete_audit_names_the_former_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session: AsyncSession
):
    group = await _create_group(client, admin_auth_header)
    _, first = await _create_test_user(client, admin_auth_header, "viewer")
    _, second = await _create_test_user(client, admin_auth_header, "viewer")
    await client.post(
        _MEMBERS.format(group["id"]),
        json={"user_ids": [first, second]},
        headers=admin_auth_header,
    )

    resp = await client.delete(_GROUP.format(group["id"]), headers=admin_auth_header)
    assert resp.status_code == 204
    [details] = await _audit_details(test_db_session, "group.delete", group["id"])
    assert details["name"] == group["name"]
    assert details["member_count"] == 2
    assert sorted(details["member_ids"]) == sorted([first, second])
    assert details["member_ids_truncated"] is False


@pytest.mark.anyio
async def test_delete_audit_caps_the_member_ids(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.modules.admin.router_groups.AUDIT_MEMBER_ID_CAP", 2, raising=True
    )
    group = await _create_group(client, admin_auth_header)
    members = [
        (await _create_test_user(client, admin_auth_header, "viewer"))[1]
        for _ in range(3)
    ]
    await client.post(
        _MEMBERS.format(group["id"]),
        json={"user_ids": members},
        headers=admin_auth_header,
    )

    resp = await client.delete(_GROUP.format(group["id"]), headers=admin_auth_header)
    assert resp.status_code == 204
    [details] = await _audit_details(test_db_session, "group.delete", group["id"])
    assert details["member_count"] == 3
    assert len(details["member_ids"]) == 2
    assert set(details["member_ids"]) <= set(members)
    assert details["member_ids_truncated"] is True


@pytest.mark.anyio
async def test_renaming_to_the_same_name_is_not_audited(
    client: AsyncClient, admin_auth_header: dict, test_db_session: AsyncSession
):
    group = await _create_group(client, admin_auth_header)

    same = await client.patch(
        _GROUP.format(group["id"]),
        json={"name": group["name"]},
        headers=admin_auth_header,
    )
    assert same.status_code == 200
    assert await _audit_details(test_db_session, "group.rename", group["id"]) == []

    new_name = _name()
    await client.patch(
        _GROUP.format(group["id"]), json={"name": new_name}, headers=admin_auth_header
    )
    assert await _audit_details(test_db_session, "group.rename", group["id"]) == [
        {"before": group["name"], "after": new_name}
    ]


@pytest.mark.anyio
async def test_add_waits_for_a_group_delete_then_finds_no_group(
    client: AsyncClient, admin_auth_header: dict, test_db_session: AsyncSession
):
    group = await _create_group(client, admin_auth_header)
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")
    group_id, member = uuid.UUID(group["id"]), uuid.UUID(user_id)
    factory = async_sessionmaker(test_db_session.bind, expire_on_commit=False)

    async with factory() as deleter, factory() as adder:
        await group_service.delete_group(deleter, group_id, id_limit=1)
        adding = asyncio.create_task(
            group_service.add_members(adder, group_id, [member])
        )
        await _wait_until_blocking(deleter)
        await deleter.commit()
        with pytest.raises(group_service.GroupNotFoundError):
            await adding
        await adder.rollback()


@pytest.mark.anyio
async def test_add_waits_for_a_user_delete_then_reports_the_user_unknown(
    client: AsyncClient, admin_auth_header: dict, test_db_session: AsyncSession
):
    group = await _create_group(client, admin_auth_header)
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")
    group_id, member = uuid.UUID(group["id"]), uuid.UUID(user_id)
    factory = async_sessionmaker(test_db_session.bind, expire_on_commit=False)

    async with factory() as deleter, factory() as adder:
        await deleter.execute(
            text("DELETE FROM catalog.users WHERE id = :id"), {"id": member}
        )
        adding = asyncio.create_task(
            group_service.add_members(adder, group_id, [member])
        )
        await _wait_until_blocking(deleter)
        await deleter.commit()
        with pytest.raises(group_service.UnknownUsersError):
            await adding
        await adder.rollback()


@pytest.mark.anyio
@pytest.mark.parametrize("write", ["rename", "add_members"])
async def test_a_write_answers_from_its_own_commit(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
    write: str,
):
    """A delete landing just after the write commits doesn't turn it into an error."""
    group = await _create_group(client, admin_auth_header)
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")
    group_id = uuid.UUID(group["id"])
    new_name = _name()
    factory = async_sessionmaker(test_db_session.bind, expire_on_commit=False)
    original_commit = AsyncSession.commit
    deleted = False

    async def commit_then_delete(self: AsyncSession) -> None:
        nonlocal deleted
        await original_commit(self)
        if deleted:
            return
        async with factory() as other:
            if write == "rename":
                landed = await other.scalar(
                    select(Group.name).where(Group.id == group_id)
                )
                landed = landed == new_name
            else:
                landed = bool(
                    await other.scalar(
                        select(func.count())
                        .select_from(GroupMember)
                        .where(GroupMember.group_id == group_id)
                    )
                )
            if landed:
                deleted = True
                await other.execute(delete(Group).where(Group.id == group_id))
                await other.commit()

    monkeypatch.setattr(AsyncSession, "commit", commit_then_delete)
    if write == "rename":
        resp = await client.patch(
            _GROUP.format(group["id"]),
            json={"name": new_name},
            headers=admin_auth_header,
        )
    else:
        resp = await client.post(
            _MEMBERS.format(group["id"]),
            json={"user_ids": [user_id]},
            headers=admin_auth_header,
        )
    monkeypatch.undo()

    assert deleted
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == group["id"]
    if write == "rename":
        assert resp.json()["name"] == new_name
    else:
        assert resp.json()["member_count"] == 1


@pytest.mark.anyio
async def test_audit_log_names_the_group(client: AsyncClient, admin_auth_header: dict):
    group = await _create_group(client, admin_auth_header)

    resp = await client.get(
        "/admin/audit-logs/",
        params={"resource_id": group["id"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    entries = resp.json()["logs"]
    assert [e["action"] for e in entries] == ["group.create"]
    assert entries[0]["resource_name"] == group["name"]


@pytest.mark.anyio
async def test_delete_group_returns_the_exact_count_and_at_most_id_limit_ids(
    client: AsyncClient, admin_auth_header: dict, test_db_session: AsyncSession
):
    group = await _create_group(client, admin_auth_header)
    members = [
        (await _create_test_user(client, admin_auth_header, "viewer"))[1]
        for _ in range(3)
    ]
    await client.post(
        _MEMBERS.format(group["id"]),
        json={"user_ids": members},
        headers=admin_auth_header,
    )

    name, count, ids = await group_service.delete_group(
        test_db_session, uuid.UUID(group["id"]), id_limit=2
    )
    await test_db_session.commit()

    assert name == group["name"]
    assert count == 3
    assert len(ids) == 2
    assert {str(user_id) for user_id in ids} <= set(members)
    assert await _member_rows(test_db_session, group["id"]) == 0


@pytest.mark.anyio
async def test_add_does_not_block_a_sign_in_updating_the_user(
    client: AsyncClient, admin_auth_header: dict, test_db_session: AsyncSession
):
    """The user lock is FOR KEY SHARE, so non-key user updates go through."""
    group = await _create_group(client, admin_auth_header)
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")
    factory = async_sessionmaker(test_db_session.bind, expire_on_commit=False)

    async with factory() as adder, factory() as signer:
        await group_service.add_members(
            adder, uuid.UUID(group["id"]), [uuid.UUID(user_id)]
        )
        await signer.execute(text("SET LOCAL lock_timeout = '2s'"))
        await signer.execute(
            text("UPDATE catalog.users SET last_login_at = now() WHERE id = :id"),
            {"id": uuid.UUID(user_id)},
        )
        await signer.commit()
        await adder.commit()
