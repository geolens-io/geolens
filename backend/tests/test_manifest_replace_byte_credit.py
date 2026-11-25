"""A manifest replacement is charged net of the bytes it supersedes, as the re-upload door is."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select, text

from app.modules.auth.models import Role, User, UserRole
from app.modules.quota.schemas import UserQuotaUsage
from app.processing.ingest.manifest_service import MANIFEST_KEY_NOT_OWNED
from tests.test_manifest_raster_replace import (
    _admin,
    _apply,
    _cleanup,
    _delete_job,
    _entry,
    _jobs_for_key,
    _pending_upload,
    _published,
    _request,
    _resurveyed,
)
from tests.test_raster_replace_1221 import _make_live_raster, _purge
from tests.test_raster_replace_1221 import raster_storage as raster_storage

pytestmark = pytest.mark.anyio

_CAP = 1_000_000


@contextmanager
def _at_the_cap():
    """Every byte of the cap is used, so a source is admitted only on credit."""
    usage = UserQuotaUsage(
        bytes_used=_CAP, dataset_count=0, storage_cap=_CAP, count_cap=0
    )
    with patch(
        "app.modules.quota.service.get_user_quota_usage",
        new=AsyncMock(return_value=usage),
    ):
        yield


async def _counted(session, dataset_id: uuid.UUID, size_bytes: int) -> None:
    """Give ``dataset_id`` the counted ``data`` row a published raster carries."""
    await session.execute(
        text(
            "INSERT INTO catalog.dataset_assets (dataset_id, key, href, size_bytes) "
            "VALUES (:id, 'data', 'x', :size)"
        ),
        {"id": dataset_id, "size": size_bytes},
    )
    await session.commit()


async def _source(session, published, user: User, version: str) -> str:
    """The entry's source: a staged path in version 1, the caller's upload in 2."""
    if version == "1":
        return published.uri
    return f"upload:{await _pending_upload(session, user.id, published.staged)}"


async def _drop_upload(session, source: str) -> None:
    if source.startswith("upload:"):
        await _delete_job(session, uuid.UUID(source.removeprefix("upload:")))


@pytest.mark.parametrize("version", ["1", "2"])
async def test_a_replacement_no_larger_than_the_old_file_is_admitted_at_the_cap(
    test_db_session, raster_storage, version
):
    user = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, user)
    await _counted(
        test_db_session, published.dataset_id, published.staged.stat().st_size
    )
    source = await _source(test_db_session, published, user, version)
    try:
        with _at_the_cap():
            result, defer = await _apply(
                test_db_session,
                _request(
                    _entry(published.key, source, _resurveyed(published)),
                    version=version,
                ),
                user,
            )
        assert (result.action, result.dataset_id) == (
            "update",
            published.dataset_id,
        ), result
        defer.assert_awaited_once()
    finally:
        await _drop_upload(test_db_session, source)
        await _cleanup(test_db_session, published)


@pytest.mark.parametrize("version", ["1", "2"])
async def test_a_replacement_larger_than_the_room_it_frees_is_refused(
    test_db_session, raster_storage, version
):
    user = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, user)
    await _counted(
        test_db_session, published.dataset_id, published.staged.stat().st_size - 1
    )
    source = await _source(test_db_session, published, user, version)
    try:
        before = len(await _jobs_for_key(test_db_session, published.key))
        with _at_the_cap():
            result, defer = await _apply(
                test_db_session,
                _request(
                    _entry(published.key, source, _resurveyed(published)),
                    version=version,
                ),
                user,
            )
        assert result.action == "error", result
        assert "Storage quota exceeded" in result.message
        defer.assert_not_awaited()
        jobs = await _jobs_for_key(test_db_session, published.key)
        assert [job.status for job in jobs[before:]] in ([], ["failed"])
    finally:
        await _drop_upload(test_db_session, source)
        await _cleanup(test_db_session, published)


async def test_a_create_at_the_cap_is_still_refused(test_db_session, raster_storage):
    """The caller's other datasets free nothing for an entry that creates one."""
    user = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, user)
    await _counted(test_db_session, published.dataset_id, _CAP)
    new_key = f"dem-new-{uuid.uuid4().hex[:8]}"
    try:
        with _at_the_cap():
            result, defer = await _apply(
                test_db_session,
                _request(_entry(new_key, published.uri, _resurveyed(published))),
                user,
            )
        assert result.action == "error", result
        assert "Storage quota exceeded" in result.message
        defer.assert_not_awaited()
    finally:
        await _cleanup(test_db_session, published)


async def test_only_the_replaced_dataset_is_credited(test_db_session, raster_storage):
    """A larger neighbour's bytes do not pay for a replacement of a smaller one."""
    user = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, user)
    size = published.staged.stat().st_size
    await _counted(test_db_session, published.dataset_id, size - 1)
    neighbour = await _make_live_raster(
        test_db_session, raster_storage, created_by=user.id
    )
    neighbour_ids = (neighbour.dataset.id, neighbour.dataset.record_id)
    await _counted(test_db_session, neighbour_ids[0], size * 10)
    try:
        with _at_the_cap():
            result, defer = await _apply(
                test_db_session,
                _request(_entry(published.key, published.uri, _resurveyed(published))),
                user,
            )
        assert result.action == "error", result
        assert "Storage quota exceeded" in result.message
        defer.assert_not_awaited()
    finally:
        await _purge(
            test_db_session, dataset_id=neighbour_ids[0], record_id=neighbour_ids[1]
        )
        await _cleanup(test_db_session, published)


@pytest.mark.parametrize("role", ["admin", None])
async def test_another_owners_dataset_earns_the_caller_no_credit(
    test_db_session, raster_storage, role
):
    """A caller at the cap naming someone else's key is refused before any
    quota is weighed, an admin who may write the dataset included, so its
    bytes are never credited to them."""
    owner = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, owner)
    await _counted(test_db_session, published.dataset_id, _CAP)
    suffix = uuid.uuid4().hex[:8]
    other = User(
        username=f"credit_other_{suffix}",
        email=f"credit_other_{suffix}@example.invalid",
        password_hash="x",
    )
    test_db_session.add(other)
    await test_db_session.flush()
    if role is not None:
        role_id = await test_db_session.scalar(select(Role.id).where(Role.name == role))
        test_db_session.add(UserRole(user_id=other.id, role_id=role_id))
    await test_db_session.commit()
    other_id = other.id
    upload_id = await _pending_upload(test_db_session, other_id, published.staged)
    try:
        with (
            _at_the_cap(),
            patch(
                "app.modules.quota.service.check_replacement_quota",
                new=AsyncMock(),
            ) as replacement_quota,
        ):
            result, defer = await _apply(
                test_db_session,
                _request(
                    _entry(
                        published.key, f"upload:{upload_id}", _resurveyed(published)
                    ),
                    version="2",
                ),
                (
                    await test_db_session.execute(
                        select(User)
                        .where(User.id == other_id)
                        .execution_options(populate_existing=True)
                    )
                ).scalar_one(),
            )
        assert (result.action, result.message) == ("error", MANIFEST_KEY_NOT_OWNED)
        replacement_quota.assert_not_awaited()
        defer.assert_not_awaited()
    finally:
        await _delete_job(test_db_session, upload_id)
        await _cleanup(test_db_session, published)
        await test_db_session.execute(
            delete(UserRole).where(UserRole.user_id == other_id)
        )
        await test_db_session.execute(delete(User).where(User.id == other_id))
        await test_db_session.commit()


async def test_an_http_replacement_streams_against_the_room_it_frees(
    test_db_session, raster_storage
):
    """The download budget counts the credit, so a same-size HTTPS source is
    not cut off at the cap before admission can weigh it."""
    user = await _admin(test_db_session)
    published = await _published(test_db_session, raster_storage, user)
    size = published.staged.stat().st_size
    await _counted(test_db_session, published.dataset_id, size)
    budgets: list[int | None] = []

    async def _download(prepared, *, job_id, max_size_bytes, quota_byte_limit=None):
        budgets.append(quota_byte_limit)
        return str(published.staged)

    try:
        with (
            _at_the_cap(),
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=_download,
            ),
        ):
            result, defer = await _apply(
                test_db_session,
                _request(
                    _entry(
                        published.key,
                        f"https://data.example.test/{published.uri}",
                        _resurveyed(published),
                    )
                ),
                user,
            )
        assert budgets == [size]
        assert result.action == "update", result
        defer.assert_awaited_once()
    finally:
        await _cleanup(test_db_session, published)
