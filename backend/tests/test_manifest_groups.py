"""Groups in a publish manifest: who a dataset or map is shared with, the
groups a caller may name, and the sharing warnings A056, A057 and A058.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import contextlib
import dataclasses
import re
import shutil
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import structlog
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update

from app.core.identity import IdentitySnapshot
from app.modules.auth.models import Group, GroupMember, Role, User
from app.modules.auth.schemas import GroupRef
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    DatasetGroupGrant,
)
from app.modules.catalog.maps.models import (
    Map,
    MapEditHistoryEvent,
    MapGroupGrant,
    MapLayer,
)
from app.platform.extensions import get_processing_port
from app.platform.jobs.models import IngestJob
from app.platform.jobs.schemas import ManifestGroupsLeftOffWarning
from app.processing.ingest.manifest_schemas import ManifestApplyRequest
from app.processing.ingest.manifest_service import apply_manifest
from app.processing.ingest.manifest_sources import manifest_dataset_fingerprint
from tests.factories import create_user
from tests.test_api_key_scope_875 import _remove_keys_minted_by_the_test  # noqa: F401
from tests.test_dataset_group_sharing import _mint_key
from tests.test_manifest_accept_publish_key import _accept
from tests.test_manifest_blocked_reapply import _KEY as _HELD_KEY, _held_apply
from tests.test_manifest_dataset_fields import (
    _apply as _apply_entries,
    _editors_without,
    _in_flight,
    _entry,
    _finalize,
    _manifest_dataset,
    _publish_key,
    _queue_update,
    _record,
    _request as _entries_request,
    _run_update,
    _set_record,
    _stage_fixture,
    _uploaded,
)
from tests.test_manifest_reapply_publication import (
    _entry as _held_entry,
    _http_request as _held_http_request,
    _reupload_task,
)
from tests.test_manifest_maps_apply import (
    _apply,
    _dataset,
    _layer,
    _map,
    _map_row,
)
from tests.write_recheck_races import _commit, _move_to_role

pytestmark = pytest.mark.anyio


async def _group(session, *members: uuid.UUID) -> GroupRef:
    """A group with ``members``, as plain values: a dry run rolls the session
    back, which expires ORM rows."""
    group = Group(name=f"grp-{uuid.uuid4().hex[:8]}")
    session.add(group)
    await session.flush()
    for member in members:
        session.add(GroupMember(group_id=group.id, user_id=member))
    ref = GroupRef(id=group.id, name=group.name)
    await session.commit()
    return ref


async def _editor(client, session, admin_headers) -> tuple[dict, IdentitySnapshot]:
    headers, user_id = await create_user(client, admin_headers, "editor")
    user = await session.get(User, uuid.UUID(user_id))
    return headers, IdentitySnapshot.of(user)


async def _admin(session) -> IdentitySnapshot:
    return IdentitySnapshot.of(
        (
            await session.execute(select(User).where(User.username == "admin"))
        ).scalar_one()
    )


def _codes(result) -> list[str]:
    return [message.code for message in result.messages]


async def _map_grants(session, map_id) -> set[uuid.UUID]:
    return set(
        await session.scalars(
            select(MapGroupGrant.group_id).where(MapGroupGrant.map_id == map_id)
        )
    )


async def _dataset_grants(session, dataset_id) -> set[uuid.UUID]:
    return set(
        await session.scalars(
            select(DatasetGroupGrant.group_id).where(
                DatasetGroupGrant.dataset_id == dataset_id
            )
        )
    )


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------


def test_version_1_refuses_groups():
    with pytest.raises(ValidationError, match="groups"):
        _entries_request(_entry("v1-groups", groups=[str(uuid.uuid4())]), version="1")


def test_the_same_groups_give_an_entry_the_same_fingerprint():
    first, second = uuid.uuid4(), uuid.uuid4()
    ordered = _entries_request(_entry("k", groups=[str(first), str(second)]))
    repeated = _entries_request(
        _entry("k", groups=[str(second), str(first), str(second)])
    )

    assert ordered.datasets[0].groups == repeated.datasets[0].groups
    assert manifest_dataset_fingerprint(
        ordered.datasets[0]
    ) == manifest_dataset_fingerprint(repeated.datasets[0])


def test_a_request_names_at_most_100_groups():
    with pytest.raises(ValidationError):
        _entries_request(_entry("k", groups=[str(uuid.uuid4()) for _ in range(101)]))


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


async def test_capabilities_lists_the_groups_each_caller_may_share_with(
    client: AsyncClient, admin_auth_header, test_db_session, clean_tables
):
    member_headers, member = await _editor(client, test_db_session, admin_auth_header)
    loner_headers, _ = await _editor(client, test_db_session, admin_auth_header)
    admin = await _admin(test_db_session)
    mine = await _group(test_db_session, member.id)
    theirs = await _group(test_db_session)
    admins = await _group(test_db_session, admin.id)

    async def groups(headers) -> set[str]:
        response = await client.get("/capabilities/", headers=headers)
        assert response.status_code == 200, response.text
        return {group["id"] for group in response.json()["me"]["groups"]}

    assert await groups(member_headers) == {str(mine.id)}
    assert await groups(loner_headers) == set()
    assert {str(mine.id), str(theirs.id), str(admins.id)} <= await groups(
        admin_auth_header
    )
    # A publish key shares as its owner without the admin role.
    key = await _mint_key(client, admin_auth_header, "publish")
    as_key = await groups(key)
    assert str(admins.id) in as_key
    assert not {str(mine.id), str(theirs.id)} & as_key


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------


async def test_a_group_the_publisher_isnt_in_is_left_off_with_a058(
    client, admin_auth_header, test_db_session, clean_tables
):
    _, editor = await _editor(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, editor.id)
    mine = await _group(test_db_session, editor.id)
    other = await _group(test_db_session)
    unknown = uuid.uuid4()
    entry = _map(
        "groups-left-off",
        _layer(dataset_id=str(dataset_id)),
        groups=[str(mine.id), str(other.id), str(unknown)],
    )

    [result] = (await _apply(test_db_session, editor, entry)).maps

    assert (result.action, result.visibility) == ("create", "restricted")
    assert _codes(result) == ["A058"]
    assert str(other.id) in result.messages[0].message
    assert str(unknown) in result.messages[0].message
    # The name of a group the publisher isn't in is never shown.
    assert other.name not in result.messages[0].message
    assert result.groups == [mine.name]
    assert await _map_grants(test_db_session, result.map_id) == {mine.id}
    assert (await _map_row(test_db_session, result.map_id)).visibility == "restricted"


async def test_an_admin_shares_a_map_with_any_group(test_db_session, clean_tables):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    other = await _group(test_db_session)

    [result] = (
        await _apply(
            test_db_session,
            admin,
            _map(
                "groups-admin",
                _layer(dataset_id=str(dataset_id)),
                groups=[str(other.id)],
            ),
        )
    ).maps

    assert (result.action, _codes(result), result.groups) == (
        "create",
        [],
        [other.name],
    )
    assert await _map_grants(test_db_session, result.map_id) == {other.id}


async def test_an_omitted_groups_keeps_a_maps_grants_on_republish(
    client, admin_auth_header, test_db_session, clean_tables
):
    _, editor = await _editor(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, editor.id)
    mine = await _group(test_db_session, editor.id)
    layer = _layer(dataset_id=str(dataset_id))
    [created] = (
        await _apply(
            test_db_session, editor, _map("groups-kept", layer, groups=[str(mine.id)])
        )
    ).maps

    [republished] = (
        await _apply(test_db_session, editor, _map("groups-kept", layer))
    ).maps

    assert (republished.action, republished.visibility) == ("update", "restricted")
    assert republished.groups == [mine.name]
    assert await _map_grants(test_db_session, created.map_id) == {mine.id}


async def test_a_map_dry_run_warns_a056_and_a057_and_writes_nothing(
    client, admin_auth_header, test_db_session, clean_tables
):
    _, editor = await _editor(client, test_db_session, admin_auth_header)
    _, member = await _editor(client, test_db_session, admin_auth_header)
    private_id = await _dataset(test_db_session, editor.id, visibility="private")
    mine = await _group(test_db_session, editor.id, member.id)
    layer = _layer(dataset_id=str(private_id))
    [created] = (await _apply(test_db_session, editor, _map("groups-dry", layer))).maps
    events = await test_db_session.scalar(
        select(func.count()).select_from(MapEditHistoryEvent)
    )

    [internal] = (
        await _apply(
            test_db_session,
            editor,
            _map("groups-dry", layer, visibility="internal"),
            dry_run=True,
        )
    ).maps
    [shared] = (
        await _apply(
            test_db_session,
            editor,
            _map("groups-dry", layer, groups=[str(mine.id)]),
            dry_run=True,
        )
    ).maps

    assert _codes(internal) == ["A057", "A056"]
    assert "everyone in your organization" in internal.messages[0].message
    assert internal.messages[1].layer == "parks"
    assert (shared.visibility, _codes(shared)) == ("restricted", ["A057", "A056"])
    assert mine.name in shared.messages[1].message
    row = await _map_row(test_db_session, created.map_id)
    assert row.visibility == "private"
    assert await _map_grants(test_db_session, created.map_id) == set()
    assert (
        await test_db_session.scalar(
            select(func.count()).select_from(MapEditHistoryEvent)
        )
        == events
    )


async def test_a_publish_key_adds_no_group_to_an_existing_private_map(
    client, admin_auth_header, test_db_session, clean_tables
):
    _, editor = await _editor(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, editor.id)
    mine = await _group(test_db_session, editor.id)
    layer = _layer(dataset_id=str(dataset_id))
    [created] = (await _apply(test_db_session, editor, _map("groups-key", layer))).maps

    with _publish_key(test_db_session):
        [widened] = (
            await _apply(
                test_db_session,
                editor,
                _map("groups-key", layer, groups=[str(mine.id)]),
            )
        ).maps
        [new] = (
            await _apply(
                test_db_session,
                editor,
                _map("groups-key-new", layer, groups=[str(mine.id)]),
            )
        ).maps

    assert (widened.action, widened.visibility, _codes(widened)) == (
        "update",
        "private",
        ["A056"],
    )
    assert mine.name in widened.messages[0].message
    assert await _map_grants(test_db_session, created.map_id) == set()
    # A map the key creates has no readers to widen.
    assert (new.action, new.visibility, new.groups) == (
        "create",
        "restricted",
        [mine.name],
    )


_BOOKMARK = {"name": "Park", "extent": [-89.7, 39.7, -89.6, 39.8]}
_NEW_BOOKMARK = {"name": "River", "extent": [-89.9, 39.5, -89.5, 39.9]}


@pytest.mark.parametrize("dry_run", [False, True], ids=["apply", "dry-run"])
@pytest.mark.parametrize("names_current", [False, True], ids=["swap", "add"])
async def test_a_publish_keys_map_reaches_no_group_its_entry_leaves_out(
    client, admin_auth_header, test_db_session, clean_tables, names_current, dry_run
):
    """The key may not add the new group, so the share is held back whole
    and the map keeps its group. A swap would hand the description and
    bookmarks it publishes to the group it drops, so nothing is written; an
    addition names the map's group and is written."""
    _, editor = await _editor(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, editor.id)
    current = await _group(test_db_session, editor.id)
    wanted = await _group(test_db_session, editor.id)
    layer = _layer(dataset_id=str(dataset_id))
    key = "groups-map-key-swap"
    [created] = (
        await _apply(
            test_db_session,
            editor,
            _map(
                key,
                layer,
                description="Before",
                bookmarks=[_BOOKMARK],
                groups=[str(current.id)],
            ),
        )
    ).maps
    assert (created.action, created.visibility) == ("create", "restricted")
    named = [str(wanted.id), *([str(current.id)] if names_current else [])]

    with _publish_key(test_db_session):
        [republished] = (
            await _apply(
                test_db_session,
                editor,
                _map(
                    key,
                    layer,
                    description="After",
                    bookmarks=[_NEW_BOOKMARK],
                    groups=named,
                ),
                dry_run=dry_run,
            )
        ).maps

    severity = "warning" if names_current else "error"
    assert [(m.code, m.severity) for m in republished.messages] == [("A056", severity)]
    assert republished.action == ("update" if names_current else "error")
    written = names_current and not dry_run
    stored = await _map_row(test_db_session, created.map_id)
    assert stored.description == ("After" if written else "Before")
    assert [bookmark["name"] for bookmark in stored.bookmarks] == [
        "River" if written else "Park"
    ]
    assert await _map_grants(test_db_session, created.map_id) == {current.id}
    assert stored.visibility == "restricted"


@pytest.mark.parametrize("held_back", [False, True], ids=["omitted", "held-back"])
async def test_a_private_map_that_kept_a_grant_is_reported_private(
    client, admin_auth_header, test_db_session, clean_tables, held_back
):
    """The map was made private in GeoLens and kept its grant. An entry that
    omits ``groups``, or a publish key's that may not wake the grant, writes
    neither the level nor the grants, so the dry run says private as the
    apply does."""
    _, editor = await _editor(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, editor.id)
    kept = await _group(test_db_session, editor.id)
    layer = _layer(dataset_id=str(dataset_id))
    key = "groups-map-kept-grant"
    [created] = (
        await _apply(test_db_session, editor, _map(key, layer, groups=[str(kept.id)]))
    ).maps
    await _commit(
        update(Map).where(Map.id == created.map_id).values(visibility="private")
    )
    entry = _map(key, layer, **({"groups": [str(kept.id)]} if held_back else {}))

    results = []
    for dry_run in (True, False):
        if held_back:
            with _publish_key(test_db_session):
                response = await _apply(test_db_session, editor, entry, dry_run=dry_run)
        else:
            response = await _apply(test_db_session, editor, entry, dry_run=dry_run)
        [result] = response.maps
        results.append((result.action, result.visibility, _codes(result)))

    assert results == [("update", "private", ["A056"] if held_back else [])] * 2
    assert (await _map_row(test_db_session, created.map_id)).visibility == "private"
    assert await _map_grants(test_db_session, created.map_id) == {kept.id}


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


async def test_a_dataset_is_shared_with_its_groups_when_published(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    mine = await _group(test_db_session, editor.id)
    other = await _group(test_db_session)
    request = _entries_request(
        await _uploaded(
            client, headers, "groups-create", groups=[str(mine.id), str(other.id)]
        )
    )

    response, _ = await _apply_entries(test_db_session, editor, request)

    [result] = response.results
    assert result.errors == [], result
    assert (result.action, _codes(result)) == ("create", ["A058"])
    assert (result.visibility, result.groups) == ("restricted", [mine.name])
    job = await test_db_session.get(IngestJob, result.job_id)
    assert job.user_metadata["manifest_groups"] == [str(mine.id)]

    dataset = await _finalize(test_db_session, editor, job)

    assert dataset.record.visibility == "restricted"
    assert await _dataset_grants(test_db_session, dataset.id) == {mine.id}


async def test_a_refused_share_publishes_the_dataset_with_a_job_warning(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    mine = await _group(test_db_session, editor.id)
    request = _entries_request(
        await _uploaded(client, headers, "groups-refused", groups=[str(mine.id)])
    )
    [result] = (await _apply_entries(test_db_session, editor, request))[0].results
    job = await test_db_session.get(IngestJob, result.job_id)

    with (
        patch(
            "app.modules.catalog.datasets.domain.service_sharing.write_group_grants",
            new=AsyncMock(side_effect=RuntimeError("raced")),
        ),
        structlog.testing.capture_logs() as logs,
    ):
        dataset = await _finalize(test_db_session, editor, job)

    assert [
        entry["error"]
        for entry in logs
        if entry["event"] == "manifest_dataset_groups_refused"
    ] == ["RuntimeError"]
    assert (dataset.record.visibility, dataset.tile_cache_version) == ("private", 1)
    assert await _dataset_grants(test_db_session, dataset.id) == set()
    assert job.user_metadata["warnings"] == [
        {
            "kind": "manifest_groups_left_off",
            "details": {"group_ids": [str(mine.id)], "reason": "refused"},
        }
    ]
    assert ManifestGroupsLeftOffWarning.model_validate(job.user_metadata["warnings"][0])


async def test_an_omitted_level_never_widens_an_existing_dataset(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    user = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    key = "groups-omitted"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "private", "published"
    )
    entry = await _uploaded(client, admin_auth_header, key)

    preview = (
        await _apply_entries(
            test_db_session, user, _entries_request(entry, dry_run=True)
        )
    )[0].results[0]
    result, task = await _queue_update(test_db_session, user, entry)
    job = await _run_update(test_db_session, result, task)

    assert (preview.action, _codes(preview)) == ("update", [])
    assert (job.status, job.error_message) == ("complete", None)
    assert "manifest_groups" not in job.user_metadata
    assert await _record(test_db_session, dataset_id) == ("private", "published")


async def test_a_dataset_dry_run_warns_a057_and_writes_nothing(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    user = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    mine = await _group(test_db_session, user.id)
    key = "groups-dry"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "private", "published"
    )
    jobs = await test_db_session.scalar(select(func.count()).select_from(IngestJob))
    widened = await _uploaded(client, admin_auth_header, key, visibility="internal")
    grouped = await _uploaded(client, admin_auth_header, key, groups=[str(mine.id)])

    [internal] = (
        await _apply_entries(
            test_db_session, user, _entries_request(widened, dry_run=True)
        )
    )[0].results
    [shared] = (
        await _apply_entries(
            test_db_session, user, _entries_request(grouped, dry_run=True)
        )
    )[0].results

    assert (internal.action, _codes(internal)) == ("update", ["A057"])
    assert "everyone in your organization" in internal.messages[0].message
    assert (shared.visibility, _codes(shared)) == ("restricted", ["A057"])
    assert mine.name in shared.messages[0].message
    assert await _record(test_db_session, dataset_id) == ("private", "published")
    assert await _dataset_grants(test_db_session, dataset_id) == set()
    # Only the two uploads.
    assert (
        await test_db_session.scalar(select(func.count()).select_from(IngestJob))
        == jobs + 2
    )


@pytest.mark.parametrize(
    ("level", "intent", "visibility", "with_group", "readers"),
    [
        ("public", "published", None, False, "visible to everyone,"),
        ("internal", "published", None, False, "everyone in your organization"),
        ("restricted", "published", None, False, "the groups and roles it is"),
        ("private", "published", "internal", False, "everyone in your organization"),
        ("private", "published", None, False, None),
        ("public", "draft", None, False, None),
        ("private", "draft", "internal", False, None),
        ("private", "draft", None, True, None),
    ],
    ids=[
        "public",
        "internal",
        "restricted",
        "published-and-widened",
        "private",
        "stays-draft",
        "draft-widened",
        "draft-shared",
    ],
)
async def test_a_dry_run_warns_a057_only_when_more_people_will_read_the_dataset(
    client,
    admin_auth_header,
    test_db_session,
    clean_tables,
    level,
    intent,
    visibility,
    with_group,
    readers,
):
    """Only a published dataset is read past its owner and admins: marking
    a draft published lets the readers of its level in, and a wider level or
    a new group on a dataset that stays a draft lets nobody in."""
    _stage_fixture()
    user = await _admin(test_db_session)
    key = f"groups-draft-{level}-{intent}-{visibility}-{with_group}".lower()
    dataset_id = await _manifest_dataset(test_db_session, user, key, level, "draft")
    changes: dict = {"publication": {"intent": intent}}
    if visibility is not None:
        changes["visibility"] = visibility
    if with_group:
        changes["groups"] = [str((await _group(test_db_session, user.id)).id)]
    entry = await _uploaded(client, admin_auth_header, key, **changes)

    [preview] = (
        await _apply_entries(
            test_db_session, user, _entries_request(entry, dry_run=True)
        )
    )[0].results

    assert preview.action == "update", preview
    if readers is None:
        assert _codes(preview) == []
    else:
        assert _codes(preview) == ["A057"]
        assert readers in preview.messages[0].message
        cause = "marks it published" if visibility is None else "level changed"
        assert cause in preview.messages[0].message
    assert await _record(test_db_session, dataset_id) == (level, "draft")


async def test_a_dry_run_names_added_groups_as_what_widens_a_restricted_dataset(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    key = "groups-dry-added"
    dataset_id, kept = await _restricted_to(test_db_session, user, key)
    added = await _group(test_db_session, user.id)
    entry = await _uploaded(
        client, admin_auth_header, key, groups=[str(kept.id), str(added.id)]
    )

    [preview] = (
        await _apply_entries(
            test_db_session, user, _entries_request(entry, dry_run=True)
        )
    )[0].results

    assert (preview.action, _codes(preview)) == ("update", ["A057"])
    [warning] = preview.messages
    assert "because this publish adds groups to it" in warning.message
    assert warning.fix == "Continue, or keep its current groups."
    assert await _dataset_grants(test_db_session, dataset_id) == {kept.id}


async def test_a_dataset_made_private_reports_no_groups(
    client, admin_auth_header, test_db_session, clean_tables
):
    """Private with ``groups`` omitted keeps the grants, which admit nobody
    while the dataset is private."""
    _stage_fixture()
    user = await _admin(test_db_session)
    mine = await _group(test_db_session, user.id)
    key = "groups-private-kept"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "restricted", "published"
    )
    test_db_session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=mine.id))
    await test_db_session.commit()
    entry = await _uploaded(client, admin_auth_header, key, visibility="private")

    result, task = await _queue_update(test_db_session, user, entry)
    job = await _run_update(test_db_session, result, task)

    assert (result.visibility, result.groups) == ("private", [])
    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("private", "published")
    assert await _dataset_grants(test_db_session, dataset_id) == {mine.id}


async def test_an_omitted_groups_leaves_a_datasets_grants(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    user = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    mine = await _group(test_db_session, user.id)
    key = "groups-dataset-kept"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "restricted", "published"
    )
    test_db_session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=mine.id))
    await test_db_session.commit()

    result, task = await _queue_update(
        test_db_session, user, await _uploaded(client, admin_auth_header, key)
    )
    job = await _run_update(test_db_session, result, task)

    assert (job.status, job.error_message) == ("complete", None)
    assert result.groups == [mine.name]
    assert await _dataset_grants(test_db_session, dataset_id) == {mine.id}
    assert await _record(test_db_session, dataset_id) == ("restricted", "published")


async def test_a_publish_key_adds_no_group_to_an_existing_private_dataset(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    user = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    mine = await _group(test_db_session, user.id)
    key = "groups-dataset-key"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "private", "published"
    )
    entry = await _uploaded(client, admin_auth_header, key, groups=[str(mine.id)])

    with _publish_key(test_db_session):
        result, task = await _queue_update(test_db_session, user, entry)
    job = await _run_update(test_db_session, result, task)

    assert (result.action, _codes(result)) == ("update", ["A056"])
    assert (job.status, job.error_message) == ("complete", None)
    assert await _dataset_grants(test_db_session, dataset_id) == set()
    assert await _record(test_db_session, dataset_id) == ("private", "published")


async def test_a_datasets_group_names_are_its_owners_and_admins_only(
    client, admin_auth_header, test_db_session, clean_tables
):
    _, owner = await _editor(client, test_db_session, admin_auth_header)
    _, member = await _editor(client, test_db_session, admin_auth_header)
    admin = await _admin(test_db_session)
    group = await _group(test_db_session, owner.id, member.id)
    dataset_id = await _dataset(test_db_session, owner.id, visibility="restricted")
    test_db_session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=group.id))
    await test_db_session.commit()
    port = get_processing_port()

    async def names(user):
        return await port.manifest_dataset_group_names(
            test_db_session, dataset_id, user
        )

    assert await names(owner) == [group.name]
    assert await names(admin) == [group.name]
    # The member reads the dataset, as on its page, without its groups.
    assert await names(member) is None


# ---------------------------------------------------------------------------
# The group routes with a publish key
# ---------------------------------------------------------------------------


async def test_a_publish_key_reaches_the_group_routes_and_cannot_delete(
    client: AsyncClient, admin_auth_header, test_db_session, clean_tables
):
    owner_headers, owner = await _editor(client, test_db_session, admin_auth_header)
    mine = await _group(test_db_session, owner.id)
    key = await _mint_key(client, owner_headers, "publish")
    internal_id = await _dataset(test_db_session, owner.id, visibility="internal")
    private_id = await _dataset(test_db_session, owner.id, visibility="private")
    map_id = (await client.post("/maps/", json={"name": "Keyed"}, headers=key)).json()[
        "id"
    ]
    body = {"group_ids": [str(mine.id)]}

    # Grants on an internal dataset wait for a narrowing, so nobody new reads it.
    dataset_shared = await client.put(
        f"/datasets/{internal_id}/groups/", json=body, headers=key
    )
    # A private dataset or map shared with a group reaches more people.
    dataset_widened = await client.put(
        f"/datasets/{private_id}/groups", json=body, headers=key
    )
    map_widened = await client.put(f"/maps/{map_id}/groups/", json=body, headers=key)
    shared_in_geolens = await client.put(
        f"/maps/{map_id}/groups/", json=body, headers=owner_headers
    )
    map_narrowed = await client.put(
        f"/maps/{map_id}/groups", json={"group_ids": []}, headers=key
    )
    deleted = await client.delete(f"/maps/{map_id}", headers=key)

    assert dataset_shared.status_code == 200, dataset_shared.text
    for refused in (dataset_widened, map_widened, deleted):
        assert refused.status_code == 403, refused.text
        assert refused.json()["detail"]["code"] == "api_key_scope"
    assert shared_in_geolens.status_code == 200, shared_in_geolens.text
    assert map_narrowed.status_code == 200, map_narrowed.text
    assert map_narrowed.json()["groups"] == []
    test_db_session.expire_all()
    assert (await test_db_session.get(Map, uuid.UUID(map_id))).visibility == "private"
    assert await _dataset_grants(test_db_session, internal_id) == {mine.id}


# ---------------------------------------------------------------------------
# Who a change reaches, judged by the audience it leaves
# ---------------------------------------------------------------------------


async def test_a_publish_key_cannot_wake_a_private_datasets_retained_grants(
    client: AsyncClient, admin_auth_header, test_db_session, clean_tables
):
    """A dataset made private keeps its group grants; naming them again would
    let the members read it."""
    _stage_fixture()
    user = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    mine = await _group(test_db_session, user.id)
    key = "groups-retained"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "private", "published"
    )
    test_db_session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=mine.id))
    await test_db_session.commit()
    publish = await _mint_key(client, admin_auth_header, "publish")

    routed = await client.put(
        f"/datasets/{dataset_id}/groups/",
        json={"group_ids": [str(mine.id)]},
        headers=publish,
    )
    entry = await _uploaded(client, admin_auth_header, key, groups=[str(mine.id)])
    with _publish_key(test_db_session):
        result, task = await _queue_update(test_db_session, user, entry)
    job = await _run_update(test_db_session, result, task)

    assert routed.status_code == 403, routed.text
    assert routed.json()["detail"]["code"] == "api_key_scope"
    assert (result.action, _codes(result)) == ("update", ["A056"])
    assert (result.visibility, result.groups) == ("private", [])
    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("private", "published")
    assert await _dataset_grants(test_db_session, dataset_id) == {mine.id}


async def test_a_publish_key_cannot_wake_a_private_maps_retained_grants(
    client: AsyncClient, admin_auth_header, test_db_session, clean_tables
):
    owner_headers, owner = await _editor(client, test_db_session, admin_auth_header)
    mine = await _group(test_db_session, owner.id)
    map_id = (
        await client.post("/maps/", json={"name": "Retained"}, headers=owner_headers)
    ).json()["id"]
    test_db_session.add(MapGroupGrant(map_id=uuid.UUID(map_id), group_id=mine.id))
    await test_db_session.commit()
    publish = await _mint_key(client, owner_headers, "publish")

    routed = await client.put(
        f"/maps/{map_id}/groups/", json={"group_ids": [str(mine.id)]}, headers=publish
    )

    assert routed.status_code == 403, routed.text
    assert routed.json()["detail"]["code"] == "api_key_scope"
    test_db_session.expire_all()
    assert (await test_db_session.get(Map, uuid.UUID(map_id))).visibility == "private"


async def test_a_publish_key_may_narrow_an_internal_map_to_its_group(
    client, admin_auth_header, test_db_session, clean_tables
):
    """Private with a group is restricted, narrower than internal, though the
    map is private for a moment between the two writes."""
    _, editor = await _editor(client, test_db_session, admin_auth_header)
    dataset_id = await _dataset(test_db_session, editor.id)
    mine = await _group(test_db_session, editor.id)
    layer = _layer(dataset_id=str(dataset_id))
    [created] = (
        await _apply(
            test_db_session, editor, _map("groups-narrow", layer, visibility="internal")
        )
    ).maps

    with _publish_key(test_db_session):
        [narrowed] = (
            await _apply(
                test_db_session,
                editor,
                _map(
                    "groups-narrow", layer, visibility="private", groups=[str(mine.id)]
                ),
            )
        ).maps

    assert (narrowed.action, _codes(narrowed)) == ("update", [])
    assert (narrowed.visibility, narrowed.groups) == ("restricted", [mine.name])
    assert await _map_grants(test_db_session, created.map_id) == {mine.id}
    assert (await _map_row(test_db_session, created.map_id)).visibility == "restricted"


async def test_a_publish_keys_kept_level_is_the_level_reported(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    user = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    key = "groups-kept-level"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "private", "published"
    )
    entry = await _uploaded(
        client,
        admin_auth_header,
        key,
        visibility="public",
    )

    with _publish_key(test_db_session):
        response, _ = await _apply_entries(
            test_db_session,
            user,
            _entries_request(entry, dry_run=True, public_fallback="internal"),
        )

    [result] = response.results
    assert (result.action, _codes(result)) == ("update", ["A056"])
    assert result.visibility == "private"
    assert await _record(test_db_session, dataset_id) == ("private", "published")


async def test_a_role_grant_keeps_a_dataset_restricted_in_the_result(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    user = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    mine = await _group(test_db_session, user.id)
    key = "groups-role-grant"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "restricted", "published"
    )
    editor_role = await test_db_session.scalar(
        select(Role.id).where(Role.name == "editor")
    )
    test_db_session.add_all(
        [
            DatasetGroupGrant(dataset_id=dataset_id, group_id=mine.id),
            DatasetGrant(dataset_id=dataset_id, role_id=editor_role),
        ]
    )
    await test_db_session.commit()

    result, task = await _queue_update(
        test_db_session,
        user,
        await _uploaded(client, admin_auth_header, key, groups=[]),
    )
    job = await _run_update(test_db_session, result, task)

    assert (result.visibility, result.groups) == ("restricted", [])
    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("restricted", "published")
    assert await _dataset_grants(test_db_session, dataset_id) == set()


@pytest.mark.parametrize("listed", [False, True], ids=["dropped", "moved"])
async def test_a_kept_layer_is_judged_on_the_dataset_it_shows(
    client, admin_auth_header, test_db_session, clean_tables, listed
):
    """A layer a kept publish no longer lists stays on its dataset; a listed
    one pointed at another dataset moves there, and is judged there."""
    _, editor = await _editor(client, test_db_session, admin_auth_header)
    private_id = await _dataset(
        test_db_session, editor.id, visibility="private", name="Kept parks"
    )
    public_id = await _dataset(test_db_session, editor.id, name="New parks")
    await _apply(
        test_db_session,
        editor,
        _map("groups-kept-layer", _layer(dataset_id=str(private_id))),
    )

    [kept] = (
        await _apply(
            test_db_session,
            editor,
            _map(
                "groups-kept-layer",
                _layer("parks" if listed else "trails", dataset_id=str(public_id)),
                styling="keep",
                visibility="internal",
            ),
            dry_run=True,
        )
    ).maps

    gaps = [message for message in kept.messages if message.code == "A056"]
    if listed:
        assert gaps == []
    else:
        [gap] = gaps
        assert gap.layer == "parks"
        assert "Kept parks" in gap.message


@pytest.mark.parametrize("stored_mine", [False, True], ids=["left-off", "same"])
async def test_an_in_flight_job_is_reused_only_for_the_groups_it_shares_with(
    client, admin_auth_header, test_db_session, clean_tables, stored_mine
):
    """A job queued while the owner wasn't in the group shares with none; the
    same entry now resolves the group, so it is not that job."""
    _stage_fixture()
    user = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    mine = await _group(test_db_session, user.id)
    entry = _entry("groups-in-flight", visibility="internal", groups=[str(mine.id)])
    stored = [str(mine.id)] if stored_mine else []
    job_id = (
        await _in_flight(
            test_db_session,
            user,
            entry,
            manifest_version="2",
            manifest_requested_visibility="internal",
            visibility="internal",
            manifest_groups=stored,
        )
    ).id

    response, queue = await _apply_entries(
        test_db_session, user, _entries_request(entry)
    )

    [result] = response.results
    if stored_mine:
        assert (result.action, result.groups) == ("skip", [mine.name])
    else:
        assert (result.action, result.errors) == ("error", ["dataset_busy"])
    queue.assert_not_awaited()
    test_db_session.expire_all()
    assert (await test_db_session.get(IngestJob, job_id)).user_metadata[
        "manifest_groups"
    ] == stored


async def test_an_in_flight_job_is_reused_after_one_of_its_groups_is_renamed(
    client, admin_auth_header, test_db_session, clean_tables
):
    """A plan lists groups by name, so a rename can reorder the ids an
    unchanged entry resolves; the job still shares with the same groups."""
    _stage_fixture()
    user = await _admin(test_db_session)
    first = Group(name=f"alpha-{uuid.uuid4().hex[:8]}")
    second = Group(name=f"beta-{uuid.uuid4().hex[:8]}")
    test_db_session.add_all([first, second])
    await test_db_session.flush()
    first_id, second_id, second_name = first.id, second.id, second.name
    test_db_session.add_all(
        GroupMember(group_id=group_id, user_id=user.id)
        for group_id in (first_id, second_id)
    )
    await test_db_session.commit()
    entry = _entry(
        "groups-in-flight-renamed",
        visibility="internal",
        groups=[str(first_id), str(second_id)],
    )
    await _in_flight(
        test_db_session,
        user,
        entry,
        manifest_version="2",
        manifest_requested_visibility="internal",
        visibility="internal",
        manifest_groups=[str(first_id), str(second_id)],
    )
    renamed = f"zeta-{uuid.uuid4().hex[:8]}"
    await _commit(update(Group).where(Group.id == first_id).values(name=renamed))

    response, queue = await _apply_entries(
        test_db_session, user, _entries_request(entry)
    )

    [result] = response.results
    assert (result.action, result.groups) == ("skip", [second_name, renamed])
    queue.assert_not_awaited()


async def test_an_in_flight_job_removing_groups_is_not_one_that_keeps_them(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin(test_db_session)
    entry = _entry("groups-in-flight-omitted", visibility="internal")
    await _in_flight(
        test_db_session,
        user,
        entry,
        manifest_version="2",
        manifest_requested_visibility="internal",
        visibility="internal",
        manifest_groups=[],
    )

    response, queue = await _apply_entries(
        test_db_session, user, _entries_request(entry)
    )

    [result] = response.results
    assert (result.action, result.errors) == ("error", ["dataset_busy"])
    queue.assert_not_awaited()


@pytest.mark.parametrize("groups", [[], "mine"], ids=["removed", "named"])
async def test_naming_groups_needs_edit_metadata(
    client, admin_auth_header, test_db_session, clean_tables, monkeypatch, groups
):
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    mine = await _group(test_db_session, editor.id)
    ids = [] if groups == [] else [str(mine.id)]
    entry = await _uploaded(client, headers, "groups-capability", groups=ids)
    _editors_without(monkeypatch, "edit_metadata")

    response, queue = await _apply_entries(
        test_db_session, editor, _entries_request(entry)
    )

    [result] = response.results
    assert (result.action, result.errors) == (
        "error",
        ["Missing permission: edit_metadata"],
    )
    queue.assert_not_awaited()


async def test_the_publish_shares_with_no_group_once_edit_metadata_is_revoked(
    client, admin_auth_header, test_db_session, clean_tables, monkeypatch
):
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    mine = await _group(test_db_session, editor.id)
    request = _entries_request(
        await _uploaded(client, headers, "groups-revoked", groups=[str(mine.id)])
    )
    [result] = (await _apply_entries(test_db_session, editor, request))[0].results
    job = await test_db_session.get(IngestJob, result.job_id)
    _editors_without(monkeypatch, "edit_metadata")

    dataset = await _finalize(test_db_session, editor, job)

    assert dataset.record.visibility == "private"
    assert await _dataset_grants(test_db_session, dataset.id) == set()
    assert job.user_metadata["warnings"][0]["details"]["reason"] == "refused"


def test_an_update_naming_groups_needs_edit_metadata_at_publish():
    from app.processing.ingest.manifest_dataset_fields import required_capabilities

    stored = {"manifest_key": "k", "reupload": True, "manifest_groups": []}

    assert required_capabilities(stored, "upload") == ["upload", "edit_metadata"]
    assert required_capabilities(
        {k: v for k, v in stored.items() if k != "manifest_groups"}, "upload"
    ) == ["upload"]


@pytest.mark.rls
async def test_a_new_item_takes_groups_of_the_requests_tenant(
    multi_tenant_rls, monkeypatch
):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.modules.catalog.datasets.domain.service import (
        plan_manifest_dataset_groups,
    )
    from app.modules.catalog.maps.manifest_sharing import plan_map_groups

    ctx = multi_tenant_rls
    group_id = uuid.uuid4()

    # The harness's reader role can't read roles; the member is no admin.
    async def no_roles(_session, _user):
        return set()

    monkeypatch.setattr(
        "app.modules.catalog.datasets.domain.service_sharing.get_user_roles", no_roles
    )
    engine = create_async_engine(ctx.db_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.groups (id, name, tenant_id) "
                    "VALUES (:id, 'Field crew', :tenant)"
                ),
                {"id": group_id, "tenant": ctx.tenant_a},
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.group_members (group_id, user_id) "
                    "VALUES (:group_id, :user_id)"
                ),
                {"group_id": group_id, "user_id": ctx.user_a_id},
            )
        member = IdentitySnapshot(
            id=uuid.UUID(ctx.user_a_id),
            username="tenant-a",
            email=None,
            is_active=True,
            roles=(),
            created_at=datetime.now(UTC),
        )
        async with ctx.tenant_session(ctx.tenant_a) as session:
            dataset_plan, _ = await plan_manifest_dataset_groups(
                session, None, [group_id], member, level=None
            )
            map_groups, _ = await plan_map_groups(
                session,
                SimpleNamespace(groups=[group_id], key="tenant-map"),
                None,
                member,
                is_admin=False,
                is_key=False,
                level="private",
            )
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("DELETE FROM catalog.groups WHERE id = :id"), {"id": group_id}
            )
        await engine.dispose()

    assert (dataset_plan.group_ids, dataset_plan.left_off) == ([group_id], [])
    assert [group.id for group in map_groups] == [group_id]


# ---------------------------------------------------------------------------
# What the worker writes, judged when it writes
# ---------------------------------------------------------------------------


async def _admin_user(session) -> User:
    return (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()


async def _held_back_warnings(job) -> list[dict]:
    return [
        warning["details"]
        for warning in job.user_metadata.get("warnings", [])
        if warning["kind"] == "manifest_groups_left_off"
    ]


async def test_groups_planned_for_a_wider_dataset_stay_off_after_a_narrowing(
    client, admin_auth_header, test_db_session, clean_tables
):
    """A grant on an internal dataset reaches nobody new; once the owner made
    the dataset private, the same grant would."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    mine = await _group(test_db_session, user.id)
    key = "groups-narrowed"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "internal", "published"
    )
    entry = await _uploaded(client, admin_auth_header, key, groups=[str(mine.id)])
    result, task = await _queue_update(test_db_session, user, entry)
    assert (result.action, _codes(result)) == ("update", [])

    await _set_record(test_db_session, dataset_id, "private", "published")
    job = await _run_update(test_db_session, result, task)

    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("private", "published")
    assert await _dataset_grants(test_db_session, dataset_id) == set()
    assert await _held_back_warnings(job) == [
        {"group_ids": [str(mine.id)], "reason": "held_back"}
    ]


async def test_the_worker_holds_back_a_publish_keys_share(
    client, admin_auth_header, test_db_session, clean_tables
):
    """A key's job that reaches the worker with a group its private dataset
    would gain, which the apply would have held back."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    mine = await _group(test_db_session, user.id)
    key = "groups-worker-key"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "private", "published"
    )
    with _publish_key(test_db_session):
        result, task = await _queue_update(
            test_db_session, user, await _uploaded(client, admin_auth_header, key)
        )
    job = await test_db_session.get(IngestJob, result.job_id)
    job.user_metadata = {**job.user_metadata, "manifest_groups": [str(mine.id)]}
    await test_db_session.commit()

    job = await _run_update(test_db_session, result, task)

    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("private", "published")
    assert await _dataset_grants(test_db_session, dataset_id) == set()
    assert await _held_back_warnings(job) == [
        {"group_ids": [str(mine.id)], "reason": "held_back"}
    ]


async def test_a_publish_keys_kept_level_is_a_job_warning(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    user = await _admin_user(test_db_session)
    key = "groups-kept-warning"
    await _manifest_dataset(test_db_session, user, key, "private", "published")
    entry = await _uploaded(client, admin_auth_header, key, visibility="internal")
    with _publish_key(test_db_session):
        result, task = await _queue_update(test_db_session, user, entry)

    job = await _run_update(test_db_session, result, task)

    assert (job.status, job.error_message) == ("complete", None)
    assert job.user_metadata["warnings"] == [
        {"kind": "manifest_widening_kept", "details": {"visibility": "internal"}}
    ]


async def _restricted_to(session, user, key) -> tuple[uuid.UUID, GroupRef]:
    """A restricted, published manifest dataset of ``user``'s and the group
    it is shared with."""
    kept = await _group(session, user.id)
    dataset_id = await _manifest_dataset(session, user, key, "restricted", "published")
    session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=kept.id))
    await session.commit()
    return dataset_id, kept


@pytest.mark.parametrize("dry_run", [False, True], ids=["apply", "dry-run"])
async def test_a_publish_keys_group_swap_is_refused_before_anything_is_queued(
    client, admin_auth_header, test_db_session, clean_tables, dry_run
):
    """The key may not add the new group, so the share would be held back
    whole and the group the entry drops would read the new data."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    key = "groups-key-swap"
    dataset_id, kept = await _restricted_to(test_db_session, user, key)
    wanted = await _group(test_db_session, user.id)
    entry = await _uploaded(client, admin_auth_header, key, groups=[str(wanted.id)])

    with _publish_key(test_db_session):
        result, task = await _queue_update(
            test_db_session, user, entry, dry_run=dry_run
        )

    assert result.action == "error", result
    assert [(m.code, m.severity) for m in result.messages] == [("A056", "error")]
    assert "was not updated" in result.messages[0].message
    task.defer_async.assert_not_awaited()
    assert await _dataset_grants(test_db_session, dataset_id) == {kept.id}
    assert await _record(test_db_session, dataset_id) == ("restricted", "published")


async def test_a_publish_keys_added_group_is_held_back_and_the_data_publishes(
    client, admin_auth_header, test_db_session, clean_tables
):
    """The entry keeps every group the dataset has, so holding the new one
    back leaves nobody reading the data that the entry removes."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    key = "groups-held-keeps"
    dataset_id, kept = await _restricted_to(test_db_session, user, key)
    added = await _group(test_db_session, user.id)
    version = await _data_version(test_db_session, dataset_id)
    entry = await _uploaded(
        client, admin_auth_header, key, groups=[str(kept.id), str(added.id)]
    )

    with _publish_key(test_db_session):
        result, task = await _queue_update(test_db_session, user, entry)
    job = await _run_update(test_db_session, result, task)

    assert (result.action, _codes(result)) == ("update", ["A056"])
    assert "groups stay as they are" in result.messages[0].message
    assert (result.visibility, result.groups) == ("restricted", [kept.name])
    assert "manifest_groups" not in job.user_metadata
    assert (job.status, job.error_message) == ("complete", None)
    assert await _data_version(test_db_session, dataset_id) != version
    assert await _dataset_grants(test_db_session, dataset_id) == {kept.id}
    assert await _record(test_db_session, dataset_id) == ("restricted", "published")


async def _failed_job(session, result) -> IngestJob:
    return await session.scalar(
        select(IngestJob)
        .where(IngestJob.id == result.job_id)
        .execution_options(populate_existing=True)
    )


async def _assert_not_replaced(
    session, result, task, dataset_id, *, version, grants, because: str
) -> None:
    """Run the entry's worker: it fails for a group the entry leaves out,
    says ``because``, and leaves the dataset's data and groups alone."""
    with pytest.raises(ValueError, match=re.escape(because)):
        await _run_update(session, result, task)
    job = await _failed_job(session, result)
    assert job.status == "failed"
    assert "groups this publish leaves out" in job.error_message
    assert because in job.error_message
    assert await _data_version(session, dataset_id) == version
    assert await _dataset_grants(session, dataset_id) == grants


async def test_the_worker_fails_a_publish_keys_swap_it_holds_back(
    client, admin_auth_header, test_db_session, clean_tables
):
    """A key's job that reaches the worker with a swap the apply would have
    refused: the dataset keeps its group, and the data is not replaced."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    key = "groups-worker-key-swap"
    dataset_id, kept = await _restricted_to(test_db_session, user, key)
    wanted = await _group(test_db_session, user.id)
    version = await _data_version(test_db_session, dataset_id)
    with _publish_key(test_db_session):
        result, task = await _queue_update(
            test_db_session, user, await _uploaded(client, admin_auth_header, key)
        )
    job = await test_db_session.get(IngestJob, result.job_id)
    job.user_metadata = {**job.user_metadata, "manifest_groups": [str(wanted.id)]}
    await test_db_session.commit()

    await _assert_not_replaced(
        test_db_session,
        result,
        task,
        dataset_id,
        version=version,
        grants={kept.id},
        because="held back because a publish key can't share",
    )
    assert await _record(test_db_session, dataset_id) == ("restricted", "published")


async def test_a_group_granted_after_a_publish_keys_held_back_addition_stops_it(
    client, admin_auth_header, test_db_session, clean_tables
):
    """The key's entry keeps the dataset's group and adds one, which is held
    back at the apply, so its job writes no groups. A group the owner grants
    before the worker runs is outside the entry's list all the same."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    key = "groups-key-granted-since"
    dataset_id, kept = await _restricted_to(test_db_session, user, key)
    added = await _group(test_db_session, user.id)
    since = await _group(test_db_session, user.id)
    version = await _data_version(test_db_session, dataset_id)
    entry = await _uploaded(
        client, admin_auth_header, key, groups=[str(kept.id), str(added.id)]
    )
    with _publish_key(test_db_session):
        result, task = await _queue_update(test_db_session, user, entry)
    assert (result.action, _codes(result)) == ("update", ["A056"])
    job = await test_db_session.get(IngestJob, result.job_id)
    assert "manifest_groups" not in job.user_metadata
    assert job.user_metadata["manifest_groups_requested"] == sorted(
        [str(kept.id), str(added.id)]
    )

    test_db_session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=since.id))
    await test_db_session.commit()

    await _assert_not_replaced(
        test_db_session,
        result,
        task,
        dataset_id,
        version=version,
        grants={kept.id, since.id},
        because="held back because a publish key can't share",
    )


async def test_a_group_granted_after_the_apply_is_removed_by_the_publish(
    client, admin_auth_header, test_db_session, clean_tables
):
    """A signed-in submitter's share is written as named, which removes a
    group granted since, so the data reaches only the entry's groups."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    key = "groups-granted-since"
    dataset_id, kept = await _restricted_to(test_db_session, user, key)
    since = await _group(test_db_session, user.id)
    version = await _data_version(test_db_session, dataset_id)
    entry = await _uploaded(client, admin_auth_header, key, groups=[str(kept.id)])
    result, task = await _queue_update(test_db_session, user, entry)
    assert (result.action, _codes(result)) == ("update", [])

    test_db_session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=since.id))
    await test_db_session.commit()
    job = await _run_update(test_db_session, result, task)

    assert (job.status, job.error_message) == ("complete", None)
    assert await _data_version(test_db_session, dataset_id) != version
    assert await _dataset_grants(test_db_session, dataset_id) == {kept.id}


async def test_a_removal_its_submitter_may_no_longer_make_stops_the_replacement(
    client, admin_auth_header, test_db_session, clean_tables, monkeypatch
):
    """``edit_metadata`` is lost after the publish checked the submitter's
    write access and before it shares, so the groups the entry removes stay."""
    from app.processing.ingest import manifest_dataset_fields as fields_module

    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    key = "groups-permission-lost"
    dataset_id, kept = await _restricted_to(test_db_session, editor, key)
    version = await _data_version(test_db_session, dataset_id)
    entry = await _uploaded(client, headers, key, groups=[])
    result, task = await _queue_update(test_db_session, editor, entry)
    assert (result.action, _codes(result)) == ("update", [])
    share = fields_module._apply_groups

    async def after_losing_edit_metadata(*args, **kwargs):
        _editors_without(monkeypatch, "edit_metadata")
        return await share(*args, **kwargs)

    monkeypatch.setattr(fields_module, "_apply_groups", after_losing_edit_metadata)

    await _assert_not_replaced(
        test_db_session,
        result,
        task,
        dataset_id,
        version=version,
        grants={kept.id},
        because="may no longer change the dataset's groups",
    )


@pytest.mark.parametrize("names_current", [False, True], ids=["swap", "add"])
async def test_a_share_held_back_after_a_narrowing_publishes_only_to_named_groups(
    client, admin_auth_header, test_db_session, clean_tables, names_current
):
    """An internal dataset's grant reads nothing extra, so the apply planned
    the entry's groups as given. Restricted before the worker runs, the new
    group is held back whole and the current one stays: a swap would hand
    the new data to the group it drops, an addition would not."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    current = await _group(test_db_session, user.id)
    wanted = await _group(test_db_session, user.id)
    key = f"groups-narrowed-{'add' if names_current else 'swap'}"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "internal", "published"
    )
    test_db_session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=current.id))
    await test_db_session.commit()
    version = await _data_version(test_db_session, dataset_id)
    named = [str(wanted.id), *([str(current.id)] if names_current else [])]
    entry = await _uploaded(client, admin_auth_header, key, groups=named)
    result, task = await _queue_update(test_db_session, user, entry)
    assert (result.action, _codes(result)) == ("update", [])

    await _set_record(test_db_session, dataset_id, "restricted", "published")
    if names_current:
        job = await _run_update(test_db_session, result, task)
        assert (job.status, job.error_message) == ("complete", None)
        assert await _data_version(test_db_session, dataset_id) != version
        assert await _held_back_warnings(job) == [
            {"group_ids": [str(wanted.id)], "reason": "held_back"}
        ]
    else:
        await _assert_not_replaced(
            test_db_session,
            result,
            task,
            dataset_id,
            version=version,
            grants={current.id},
            because="held back because the dataset was made visible to fewer",
        )
    assert await _dataset_grants(test_db_session, dataset_id) == {current.id}
    assert await _record(test_db_session, dataset_id) == ("restricted", "published")


@pytest.mark.parametrize(
    ("named", "unreadable", "replaced"),
    [
        ("kept", "manifest_groups", True),
        ("none", "manifest_groups", False),
        ("kept", "manifest_groups_requested", False),
    ],
    ids=["names-the-group", "removes-the-group", "unreadable-request"],
)
async def test_an_unreadable_groups_entry_keeps_the_grants(
    client,
    admin_auth_header,
    test_db_session,
    clean_tables,
    named,
    unreadable,
    replaced,
):
    """The share isn't written, so the dataset keeps its group. The data is
    replaced only when the entry's own list is readable and names it."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    key = f"groups-malformed-{named}-{unreadable.replace('_', '-')}"
    dataset_id, kept = await _restricted_to(test_db_session, user, key)
    version = await _data_version(test_db_session, dataset_id)
    entry = await _uploaded(
        client,
        admin_auth_header,
        key,
        groups=[str(kept.id)] if named == "kept" else [],
    )
    result, task = await _queue_update(test_db_session, user, entry)
    job = await test_db_session.get(IngestJob, result.job_id)
    job.user_metadata = {**job.user_metadata, unreadable: ["not-a-group"]}
    await test_db_session.commit()

    if replaced:
        job = await _run_update(test_db_session, result, task)
        assert (job.status, job.error_message) == ("complete", None)
        assert await _data_version(test_db_session, dataset_id) != version
        assert await _held_back_warnings(job) == [
            {"group_ids": [], "reason": "refused"}
        ]
        assert await _dataset_grants(test_db_session, dataset_id) == {kept.id}
        return
    await _assert_not_replaced(
        test_db_session,
        result,
        task,
        dataset_id,
        version=version,
        grants={kept.id},
        because="The groups this job stored could not be read.",
    )


async def test_an_empty_groups_removes_more_grants_than_a_request_may_name(
    client, admin_auth_header, test_db_session, clean_tables
):
    """Map shares add to a dataset's grants without the request's limit of
    100 groups, and the job stores every one the dataset had."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    key = "groups-many-removed"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "restricted", "published"
    )
    groups = [Group(name=f"grp-{index}-{uuid.uuid4().hex[:8]}") for index in range(101)]
    test_db_session.add_all(groups)
    await test_db_session.flush()
    test_db_session.add_all(
        DatasetGroupGrant(dataset_id=dataset_id, group_id=group.id) for group in groups
    )
    await test_db_session.commit()
    entry = await _uploaded(client, admin_auth_header, key, groups=[])

    result, task = await _queue_update(test_db_session, user, entry)
    assert (result.action, _codes(result)) == ("update", [])
    job = await test_db_session.get(IngestJob, result.job_id)
    assert len(job.user_metadata["manifest_groups_granted"]) == 101
    job = await _run_update(test_db_session, result, task)

    assert (job.status, job.error_message) == ("complete", None)
    assert await _held_back_warnings(job) == []
    assert await _dataset_grants(test_db_session, dataset_id) == set()
    assert await _record(test_db_session, dataset_id) == ("private", "published")


async def test_a_planning_error_does_not_fail_the_publish(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    mine = await _group(test_db_session, editor.id)
    request = _entries_request(
        await _uploaded(client, headers, "groups-plan-error", groups=[str(mine.id)])
    )
    [result] = (await _apply_entries(test_db_session, editor, request))[0].results
    job = await test_db_session.get(IngestJob, result.job_id)

    with patch(
        "app.modules.catalog.datasets.domain.service_sharing.plan_share_groups",
        new=AsyncMock(side_effect=RuntimeError("database went away")),
    ):
        dataset = await _finalize(test_db_session, editor, job)

    assert dataset.record.visibility == "private"
    assert await _dataset_grants(test_db_session, dataset.id) == set()
    assert job.user_metadata["warnings"][0]["details"] == {
        "group_ids": [str(mine.id)],
        "reason": "refused",
    }


# ---------------------------------------------------------------------------
# What changed between the plan and the write
# ---------------------------------------------------------------------------


async def test_a_grant_revoked_after_the_plan_is_not_restored(
    client, admin_auth_header, test_db_session, clean_tables
):
    """The apply kept groups A and B; B was removed before the job ran, and
    the dataset stays restricted through A."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    kept = await _group(test_db_session, user.id)
    revoked = await _group(test_db_session, user.id)
    key = "groups-revoked-since"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "restricted", "published"
    )
    test_db_session.add_all(
        [
            DatasetGroupGrant(dataset_id=dataset_id, group_id=kept.id),
            DatasetGroupGrant(dataset_id=dataset_id, group_id=revoked.id),
        ]
    )
    await test_db_session.commit()
    entry = await _uploaded(
        client, admin_auth_header, key, groups=[str(kept.id), str(revoked.id)]
    )
    result, task = await _queue_update(test_db_session, user, entry)
    assert (result.action, _codes(result)) == ("update", [])

    await test_db_session.execute(
        delete(DatasetGroupGrant).where(
            DatasetGroupGrant.dataset_id == dataset_id,
            DatasetGroupGrant.group_id == revoked.id,
        )
    )
    await test_db_session.commit()
    job = await _run_update(test_db_session, result, task)

    assert (job.status, job.error_message) == ("complete", None)
    assert await _dataset_grants(test_db_session, dataset_id) == {kept.id}
    assert await _held_back_warnings(job) == [
        {"group_ids": [str(revoked.id)], "reason": "held_back"}
    ]


@pytest.mark.parametrize("was", ["member", "admin"])
async def test_the_worker_shares_as_its_submitter_stands_when_it_runs(
    client, admin_auth_header, test_db_session, clean_tables, was
):
    """The apply planned a group its submitter could add then, as a member
    who has left the group since or as an admin since made an editor."""
    _stage_fixture()
    headers, user_id = await create_user(
        client, admin_auth_header, "admin" if was == "admin" else "editor"
    )
    submitter = IdentitySnapshot.of(await test_db_session.get(User, uuid.UUID(user_id)))
    group = await _group(test_db_session, *([submitter.id] if was == "member" else []))
    key = f"groups-standing-{was}"
    dataset_id = await _manifest_dataset(
        test_db_session, submitter, key, "private", "published"
    )
    entry = await _uploaded(client, headers, key, groups=[str(group.id)])
    result, task = await _queue_update(test_db_session, submitter, entry)
    assert (result.action, _codes(result)) == ("update", [])
    job = await test_db_session.get(IngestJob, result.job_id)
    assert job.user_metadata["manifest_groups"] == [str(group.id)]

    if was == "member":
        await _commit(delete(GroupMember).where(GroupMember.user_id == submitter.id))
    else:
        await _commit(_move_to_role(submitter.id, "editor"))
    job = await _run_update(test_db_session, result, task)

    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("private", "published")
    assert await _dataset_grants(test_db_session, dataset_id) == set()
    assert await _held_back_warnings(job) == [
        {"group_ids": [str(group.id)], "reason": "left_off"}
    ]


async def test_the_write_refuses_a_group_its_plan_wrongly_kept(
    client, admin_auth_header, test_db_session, clean_tables, monkeypatch
):
    """The write reads the submitter's standing itself, so a plan that took
    them for an admin adds nothing."""
    from app.modules.catalog.datasets.domain import service_sharing

    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    other = await _group(test_db_session)
    key = "groups-write-standing"
    dataset_id = await _manifest_dataset(
        test_db_session, editor, key, "private", "published"
    )
    result, task = await _queue_update(
        test_db_session, editor, await _uploaded(client, headers, key)
    )
    job = await test_db_session.get(IngestJob, result.job_id)
    job.user_metadata = {**job.user_metadata, "manifest_groups": [str(other.id)]}
    await test_db_session.commit()
    planned = service_sharing.plan_share_groups

    async def as_an_admin(*args, **kwargs):
        return await planned(*args, **{**kwargs, "is_admin": True})

    monkeypatch.setattr(service_sharing, "plan_share_groups", as_an_admin)

    job = await _run_update(test_db_session, result, task)

    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("private", "published")
    assert await _dataset_grants(test_db_session, dataset_id) == set()
    assert await _held_back_warnings(job) == [
        {"group_ids": [str(other.id)], "reason": "refused"}
    ]


async def test_an_admin_demoted_mid_batch_shares_only_with_own_groups(
    client, admin_auth_header, test_db_session, clean_tables, monkeypatch
):
    _, admin_id = await create_user(client, admin_auth_header, "admin")
    admin = IdentitySnapshot.of(await test_db_session.get(User, uuid.UUID(admin_id)))
    other = await _group(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    layer = _layer(dataset_id=str(dataset_id))
    editor_role = await test_db_session.scalar(
        select(Role.id).where(Role.name == "editor")
    )
    from app.modules.auth.models import UserRole
    from app.modules.catalog.maps import manifest_apply

    applied = manifest_apply._apply_map

    async def demote_after_the_first(session, entry, request):
        result = await applied(session, entry, request)
        if entry.key == "demoted-first":
            await session.execute(delete(UserRole).where(UserRole.user_id == admin.id))
            session.add(UserRole(user_id=admin.id, role_id=editor_role))
            await session.commit()
        return result

    monkeypatch.setattr(manifest_apply, "_apply_map", demote_after_the_first)

    first, second = (
        await _apply(
            test_db_session,
            admin,
            _map("demoted-first", layer),
            _map("demoted-second", layer, groups=[str(other.id)]),
        )
    ).maps

    assert (first.action, second.action) == ("create", "create")
    assert _codes(second) == ["A058"]
    assert await _map_grants(test_db_session, second.map_id) == set()


async def test_a_private_entry_with_its_groups_keeps_a_group_shared_map(
    client, admin_auth_header, test_db_session, clean_tables
):
    """Private with the same groups is restricted, so the owner's map shared
    with that group keeps the layer; the publish never makes it private."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    _, member = await _editor(client, test_db_session, admin_auth_header)
    mine = await _group(test_db_session, user.id, member.id)
    key = "groups-private-shared-map"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "restricted", "published"
    )
    shared_map = Map(name="Shared", created_by=user.id, visibility="restricted")
    test_db_session.add(shared_map)
    await test_db_session.flush()
    test_db_session.add_all(
        [
            DatasetGroupGrant(dataset_id=dataset_id, group_id=mine.id),
            MapGroupGrant(map_id=shared_map.id, group_id=mine.id),
            MapLayer(map_id=shared_map.id, dataset_id=dataset_id),
        ]
    )
    await test_db_session.commit()
    entry = await _uploaded(
        client, admin_auth_header, key, visibility="private", groups=[str(mine.id)]
    )

    result, task = await _queue_update(test_db_session, user, entry)
    job = await _run_update(test_db_session, result, task)

    assert (result.visibility, result.groups) == ("restricted", [mine.name])
    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("restricted", "published")
    assert await _dataset_grants(test_db_session, dataset_id) == {mine.id}


async def _shared_through(session, user, member, dataset_id) -> GroupRef:
    """Restrict the dataset to a group ``member`` is in, on a map of
    ``user``'s shared with that group: the map's readers need the grant."""
    group = await _group(session, user.id, member.id)
    session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=group.id))
    await session.commit()
    await _map_needing(session, user, group, dataset_id)
    return group


async def _map_needing(session, user, group, dataset_id) -> None:
    """A map of ``user``'s shared with ``group``, showing the dataset."""
    shared_map = Map(name="Shared", created_by=user.id, visibility="restricted")
    session.add(shared_map)
    await session.flush()
    session.add_all(
        [
            MapGroupGrant(map_id=shared_map.id, group_id=group.id),
            MapLayer(map_id=shared_map.id, dataset_id=dataset_id),
        ]
    )
    await session.commit()


async def _data_version(session, dataset_id) -> int | None:
    return await session.scalar(
        select(Dataset.current_version)
        .where(Dataset.id == dataset_id)
        .execution_options(populate_existing=True)
    )


async def test_a_replacement_whose_group_removal_is_refused_publishes_nothing(
    client, admin_auth_header, test_db_session, clean_tables
):
    """A shared map that keeps the group arrives after the apply, so the
    job's removal is refused; publishing anyway would hand the new data to
    the group the entry drops. The same manifest sent again while the job is
    queued says so: a dry run is refused with A056, and an apply answers for
    the job with it as a warning."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    _, member = await _editor(client, test_db_session, admin_auth_header)
    key = "groups-removal-refused"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "restricted", "published"
    )
    mine = await _group(test_db_session, user.id, member.id)
    test_db_session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=mine.id))
    await test_db_session.commit()
    version = await _data_version(test_db_session, dataset_id)
    entry = await _uploaded(client, admin_auth_header, key, groups=[])
    result, task = await _queue_update(test_db_session, user, entry)
    assert (result.action, _codes(result)) == ("update", [])
    await _map_needing(test_db_session, user, mine, dataset_id)

    response, _ = await _apply_entries(
        test_db_session, user, _entries_request(entry, dry_run=True)
    )
    [previewed] = response.results
    assert previewed.action == "error", previewed
    assert [(m.code, m.severity) for m in previewed.messages] == [("A056", "error")]
    assert "used in shared maps: Shared" in previewed.messages[0].message
    # The refused entry rolled the session back, which expires the user row.
    user = await _admin_user(test_db_session)
    response, _ = await _apply_entries(test_db_session, user, _entries_request(entry))
    [applied] = response.results
    assert (applied.action, applied.job_id) == ("skip", result.job_id)
    assert _job_refusals(applied) == [("A056", "warning")]
    assert await _dataset_grants(test_db_session, dataset_id) == {mine.id}

    await _assert_not_replaced(
        test_db_session,
        result,
        task,
        dataset_id,
        version=version,
        grants={mine.id},
        because=(
            "The group change was refused: Cannot restrict visibility: dataset "
            "is used in shared maps: Shared."
        ),
    )
    assert await _record(test_db_session, dataset_id) == ("restricted", "published")


async def test_a_replacement_swapping_a_maps_group_is_refused_before_it_is_queued(
    client, admin_auth_header, test_db_session, clean_tables
):
    """The owner's shared map needs group A, so the job could not swap A for
    B and would fail: the entry is refused with A056 before anything is
    queued, and a map in the same request isn't judged on B's access."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    _, member = await _editor(client, test_db_session, admin_auth_header)
    key = "groups-swap-refused"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "restricted", "published"
    )
    needed = await _shared_through(test_db_session, user, member, dataset_id)
    swapped = await _group(test_db_session, user.id)
    entry = await _uploaded(client, admin_auth_header, key, groups=[str(swapped.id)])
    maps = [
        _map(
            "groups-swap-refused-map",
            _layer(dataset_key=key),
            groups=[str(swapped.id)],
        )
    ]

    response, _ = await _apply_entries(
        test_db_session, user, _entries_request(entry, dry_run=True, maps=maps)
    )
    [refused] = response.results
    assert refused.action == "error", refused
    assert [(m.code, m.severity) for m in refused.messages] == [("A056", "error")]
    assert "used in shared maps: Shared" in refused.messages[0].message
    [checked] = response.maps
    assert ("A052", "parks") in [(m.code, m.layer) for m in checked.messages]
    assert _layer_gaps(checked) == []

    user = await _admin_user(test_db_session)
    applied, queue = await _apply_entries(
        test_db_session, user, _entries_request(entry)
    )
    [refused] = applied.results
    assert [(m.code, m.severity) for m in refused.messages] == [("A056", "error")]
    queue.assert_not_awaited()
    assert await _dataset_grants(test_db_session, dataset_id) == {needed.id}


async def _internal_shared_through(client, admin_auth_header, session, key):
    """An internal dataset of the admin's granted to group A, whose member
    reads it only as the organization, and group B, which only the admin is
    in; the dataset, A, B and the admin."""
    user = await _admin_user(session)
    _, member = await _editor(client, session, admin_auth_header)
    dataset_id = await _manifest_dataset(session, user, key, "internal", "published")
    needed = await _group(session, user.id, member.id)
    session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=needed.id))
    await session.commit()
    swapped = await _group(session, user.id)
    return dataset_id, needed, swapped, user


async def test_a_private_replacement_its_publication_would_refuse_is_not_queued(
    client, admin_auth_header, test_db_session, clean_tables
):
    """Private with group B makes the internal dataset restricted to B after
    its share, which strands the owner's map shared with A: the job's
    publication would be refused, so the entry is refused with A056 before
    anything is queued, and a map in the same request isn't judged on B."""
    _stage_fixture()
    key = "groups-private-narrowing-refused"
    dataset_id, needed, swapped, user = await _internal_shared_through(
        client, admin_auth_header, test_db_session, key
    )
    await _map_needing(test_db_session, user, needed, dataset_id)
    entry = await _uploaded(
        client,
        admin_auth_header,
        key,
        visibility="private",
        groups=[str(swapped.id)],
    )
    maps = [_map(f"{key}-map", _layer(dataset_key=key), groups=[str(swapped.id)])]

    response, _ = await _apply_entries(
        test_db_session, user, _entries_request(entry, dry_run=True, maps=maps)
    )
    [refused] = response.results
    assert refused.action == "error", refused
    assert [(m.code, m.severity) for m in refused.messages] == [("A056", "error")]
    assert "used in shared maps: Shared" in refused.messages[0].message
    [checked] = response.maps
    assert ("A052", "parks") in [(m.code, m.layer) for m in checked.messages]
    assert _layer_gaps(checked) == []

    user = await _admin_user(test_db_session)
    applied, _ = await _apply_entries(test_db_session, user, _entries_request(entry))
    [refused] = applied.results
    assert [(m.code, m.severity) for m in refused.messages] == [("A056", "error")]
    assert await _record(test_db_session, dataset_id) == ("internal", "published")
    assert await _dataset_grants(test_db_session, dataset_id) == {needed.id}


async def test_a_queued_private_replacement_its_publication_will_refuse_says_so(
    client, admin_auth_header, test_db_session, clean_tables
):
    """The map shared with A arrives after the apply, so the job's
    publication will be refused once its share leaves only B: the same
    manifest sent again is refused with A056 in a dry run and warned of in
    an apply, and the job fails and leaves the dataset as it was."""
    _stage_fixture()
    key = "groups-private-narrowing-queued"
    dataset_id, needed, swapped, user = await _internal_shared_through(
        client, admin_auth_header, test_db_session, key
    )
    entry = await _uploaded(
        client,
        admin_auth_header,
        key,
        visibility="private",
        groups=[str(swapped.id)],
    )
    queued, task = await _queue_update(test_db_session, user, entry)
    assert queued.action == "update", queued
    await _map_needing(test_db_session, user, needed, dataset_id)

    response, _ = await _apply_entries(
        test_db_session, user, _entries_request(entry, dry_run=True)
    )
    [previewed] = response.results
    assert previewed.action == "error", previewed
    assert [(m.code, m.severity) for m in previewed.messages] == [("A056", "error")]
    assert "used in shared maps: Shared" in previewed.messages[0].message
    user = await _admin_user(test_db_session)
    response, _ = await _apply_entries(test_db_session, user, _entries_request(entry))
    [applied] = response.results
    assert (applied.action, applied.job_id) == ("skip", queued.job_id)
    assert _job_refusals(applied) == [("A056", "warning")]

    with pytest.raises(ValueError, match="used in shared maps"):
        await _run_update(test_db_session, queued, task)
    assert (await _failed_job(test_db_session, queued)).status == "failed"
    assert await _record(test_db_session, dataset_id) == ("internal", "published")
    assert await _dataset_grants(test_db_session, dataset_id) == {needed.id}


async def test_a_queued_widening_that_removes_a_maps_group_is_answered_as_a_publish(
    client, admin_auth_header, test_db_session, clean_tables
):
    """The job makes the dataset internal before it removes the group, so
    the owner's map keeps its readers and the replacement publishes; the same
    manifest sent again while the job is queued answers as that publish."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    _, member = await _editor(client, test_db_session, admin_auth_header)
    key = "groups-widening-removal"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "restricted", "published"
    )
    await _shared_through(test_db_session, user, member, dataset_id)
    entry = await _uploaded(
        client, admin_auth_header, key, groups=[], visibility="internal"
    )
    result, task = await _queue_update(test_db_session, user, entry)
    assert result.action == "update", result

    response, _ = await _apply_entries(
        test_db_session, user, _entries_request(entry, dry_run=True)
    )
    [previewed] = response.results
    assert (previewed.action, previewed.job_id) == ("skip", result.job_id)
    assert "A056" not in _codes(previewed)
    user = await _admin_user(test_db_session)
    response, _ = await _apply_entries(test_db_session, user, _entries_request(entry))
    [applied] = response.results
    assert (applied.action, applied.job_id) == ("skip", result.job_id)
    assert _job_refusals(applied) == []

    job = await _run_update(test_db_session, result, task)
    assert (job.status, job.error_message) == ("complete", None)
    assert await _record(test_db_session, dataset_id) == ("internal", "published")
    assert await _dataset_grants(test_db_session, dataset_id) == set()


async def test_a_replacement_whose_added_group_is_refused_still_publishes(
    client, admin_auth_header, test_db_session, clean_tables
):
    """The refused share would only have added readers, so the dataset keeps
    the groups the entry names and the data is replaced."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    kept = await _group(test_db_session, user.id)
    added = await _group(test_db_session, user.id)
    key = "groups-addition-refused"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "restricted", "published"
    )
    test_db_session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=kept.id))
    await test_db_session.commit()
    version = await _data_version(test_db_session, dataset_id)
    entry = await _uploaded(
        client, admin_auth_header, key, groups=[str(kept.id), str(added.id)]
    )
    result, task = await _queue_update(test_db_session, user, entry)

    with patch(
        "app.modules.catalog.datasets.domain.service_sharing.write_group_grants",
        new=AsyncMock(side_effect=RuntimeError("raced")),
    ):
        job = await _run_update(test_db_session, result, task)

    assert (job.status, job.error_message) == ("complete", None)
    assert await _data_version(test_db_session, dataset_id) != version
    assert await _dataset_grants(test_db_session, dataset_id) == {kept.id}
    assert await _held_back_warnings(job) == [
        {
            "group_ids": sorted([str(kept.id), str(added.id)]),
            "reason": "refused",
        }
    ]


async def test_an_unpublished_layer_on_an_organization_map_is_a056(
    client, admin_auth_header, test_db_session, clean_tables
):
    _, editor = await _editor(client, test_db_session, admin_auth_header)
    draft_id = await _dataset(
        test_db_session,
        editor.id,
        visibility="internal",
        record_status="draft",
        name="Draft parks",
    )

    [checked] = (
        await _apply(
            test_db_session,
            editor,
            _map(
                "groups-draft-layer",
                _layer(dataset_id=str(draft_id)),
                visibility="internal",
            ),
            dry_run=True,
        )
    ).maps

    [gap] = [message for message in checked.messages if message.code == "A056"]
    assert (gap.layer, "Draft parks" in gap.message) == ("parks", True)


# ---------------------------------------------------------------------------
# A dry run's layers on datasets the same request publishes
# ---------------------------------------------------------------------------


async def _dry_run_maps(session, user, entry: dict, *maps: dict) -> list:
    """The map results of a dry run that publishes ``entry`` and ``maps``."""
    response, _ = await _apply_entries(
        session, user, _entries_request(entry, dry_run=True, maps=list(maps))
    )
    [dataset] = response.results
    assert dataset.action in ("create", "update"), dataset
    _assert_maps_written(response.maps)
    return response.maps


def _assert_maps_written(maps) -> None:
    """Every map checks clean apart from its warnings, so a missing A056 is
    the layer judged readable, not a map that failed before its layers."""
    assert all(result.action in ("create", "update") for result in maps), maps


def _layer_gaps(result) -> list[tuple[str | None, str]]:
    return [
        (message.layer, message.message)
        for message in result.messages
        if message.code == "A056" and message.layer is not None
    ]


async def test_a_dry_run_judges_a_layer_on_the_groups_its_dataset_is_published_to(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    _, reader = await _editor(client, test_db_session, admin_auth_header)
    _, other = await _editor(client, test_db_session, admin_auth_header)
    readers = await _group(test_db_session, editor.id, reader.id)
    others = await _group(test_db_session, editor.id, other.id)
    key = "groups-pending-create"
    layer = _layer(dataset_key=key)

    without, shared = await _dry_run_maps(
        test_db_session,
        editor,
        await _uploaded(client, headers, key, groups=[str(others.id)]),
        _map("groups-pending-readers", layer, groups=[str(readers.id)]),
        _map("groups-pending-others", layer, groups=[str(others.id)]),
    )

    [(gap_layer, gap)] = _layer_gaps(without)
    assert gap_layer == "parks"
    assert (readers.name in gap, others.name in gap) == (True, False)
    assert "Road centerlines" in gap
    assert _layer_gaps(shared) == []
    assert await test_db_session.scalar(select(func.count()).select_from(Map)) == 0


async def test_a_dry_run_judges_a_layer_on_the_groups_a_replacement_leaves(
    client, admin_auth_header, test_db_session, clean_tables
):
    """The dataset is shared with the map's group now, and the same request
    shares it with another group only."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    _, reader = await _editor(client, test_db_session, admin_auth_header)
    _, other = await _editor(client, test_db_session, admin_auth_header)
    readers = await _group(test_db_session, reader.id)
    others = await _group(test_db_session, other.id)
    key = "groups-pending-update"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "restricted", "published"
    )
    test_db_session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=readers.id))
    await test_db_session.commit()
    layer = _layer(dataset_id=str(dataset_id))

    without, shared = await _dry_run_maps(
        test_db_session,
        user,
        await _uploaded(client, admin_auth_header, key, groups=[str(others.id)]),
        _map("groups-pending-readers", layer, groups=[str(readers.id)]),
        _map("groups-pending-others", layer, groups=[str(others.id)]),
    )

    [(gap_layer, gap)] = _layer_gaps(without)
    assert (gap_layer, readers.name in gap) == ("parks", True)
    assert _layer_gaps(shared) == []
    assert await _dataset_grants(test_db_session, dataset_id) == {readers.id}


@pytest.mark.parametrize(
    "publishes",
    [
        {"visibility": "private"},
        {"visibility": "internal", "publication": {"intent": "draft"}},
    ],
    ids=["private", "draft"],
)
async def test_a_dry_run_warns_for_an_organization_map_over_a_dataset_it_cant_read(
    client, admin_auth_header, test_db_session, clean_tables, publishes
):
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    hidden_key, open_key = "groups-pending-hidden", "groups-pending-open"
    hidden = await _uploaded(client, headers, hidden_key, **publishes)
    opened = await _uploaded(client, headers, open_key, visibility="internal")
    request = _entries_request(
        hidden,
        dry_run=True,
        maps=[
            _map(
                "groups-pending-organization",
                _layer("hidden", dataset_key=hidden_key),
                _layer("open", dataset_key=open_key),
                visibility="internal",
            )
        ],
    )
    request.datasets.append(_entries_request(opened).datasets[0])

    response, _ = await _apply_entries(test_db_session, editor, request)

    assert [result.action for result in response.results] == ["create", "create"]
    [checked] = response.maps
    [(gap_layer, gap)] = _layer_gaps(checked)
    assert gap_layer == "hidden"
    assert "everyone in your organization" in gap


async def test_a_dry_run_judges_a_publish_keys_held_back_group_as_held_back(
    client, admin_auth_header, test_db_session, clean_tables
):
    """The key may not add the map's group to the dataset, so the dataset
    keeps its groups and that group's members won't see the layer."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    _, reader = await _editor(client, test_db_session, admin_auth_header)
    key = "groups-pending-held"
    dataset_id, kept = await _restricted_to(test_db_session, user, key)
    added = await _group(test_db_session, user.id, reader.id)
    entry = await _uploaded(
        client, admin_auth_header, key, groups=[str(kept.id), str(added.id)]
    )
    layer = _layer(dataset_id=str(dataset_id))

    with _publish_key(test_db_session):
        without, shared = await _dry_run_maps(
            test_db_session,
            user,
            entry,
            _map("groups-pending-added", layer, groups=[str(added.id)]),
            _map("groups-pending-kept", layer, groups=[str(kept.id)]),
        )

    [(gap_layer, gap)] = _layer_gaps(without)
    assert (gap_layer, added.name in gap) == ("parks", True)
    assert _layer_gaps(shared) == []


async def test_a_dry_run_judges_a_draft_shared_with_the_maps_group_as_unread(
    client, admin_auth_header, test_db_session, clean_tables
):
    """Until it is published only its owner and admins read a dataset,
    whatever groups its entry shares it with."""
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    _, reader = await _editor(client, test_db_session, admin_auth_header)
    readers = await _group(test_db_session, editor.id, reader.id)
    key = "groups-pending-draft"
    entry = await _uploaded(
        client,
        headers,
        key,
        visibility="private",
        groups=[str(readers.id)],
        publication={"intent": "draft"},
    )

    [checked] = await _dry_run_maps(
        test_db_session,
        editor,
        entry,
        _map(
            "groups-pending-draft-map",
            _layer(dataset_key=key),
            groups=[str(readers.id)],
        ),
    )

    [(gap_layer, gap)] = _layer_gaps(checked)
    assert (gap_layer, readers.name in gap) == ("parks", True)


async def test_a_dry_run_counts_the_publisher_as_reading_the_dataset_it_creates(
    client, admin_auth_header, test_db_session, clean_tables
):
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    _, reader = await _editor(client, test_db_session, admin_auth_header)
    alone = await _group(test_db_session, editor.id)
    readers = await _group(test_db_session, editor.id, reader.id)
    key = "groups-pending-owner"
    layer = _layer(dataset_key=key)

    own, shared = await _dry_run_maps(
        test_db_session,
        editor,
        await _uploaded(client, headers, key, visibility="private"),
        _map("groups-pending-own", layer, groups=[str(alone.id)]),
        _map("groups-pending-shared", layer, groups=[str(readers.id)]),
    )

    assert _layer_gaps(own) == []
    [(gap_layer, gap)] = _layer_gaps(shared)
    assert (gap_layer, readers.name in gap) == ("parks", True)


@pytest.mark.parametrize("to_another_group", [True, False], ids=["swapped", "removed"])
async def test_a_dry_run_counts_a_role_grant_a_removed_groups_members_keep(
    client, admin_auth_header, test_db_session, clean_tables, to_another_group
):
    """The entry takes the editors' group off the dataset, and the editor
    role's grant still lets them read it; with no group left that grant is
    also what keeps the dataset restricted."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    _, editor = await _editor(client, test_db_session, admin_auth_header)
    _, viewer_id = await create_user(client, admin_auth_header, "viewer")
    _, other = await _editor(client, test_db_session, admin_auth_header)
    editors = await _group(test_db_session, editor.id)
    viewers = await _group(test_db_session, uuid.UUID(viewer_id))
    others = await _group(test_db_session, other.id)
    key = "groups-pending-role"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "restricted", "published"
    )
    editor_role = await test_db_session.scalar(
        select(Role.id).where(Role.name == "editor")
    )
    test_db_session.add_all(
        [
            DatasetGroupGrant(dataset_id=dataset_id, group_id=editors.id),
            DatasetGroupGrant(dataset_id=dataset_id, group_id=viewers.id),
            DatasetGrant(dataset_id=dataset_id, role_id=editor_role),
        ]
    )
    await test_db_session.commit()
    layer = _layer(dataset_id=str(dataset_id))

    by_role, without = await _dry_run_maps(
        test_db_session,
        user,
        await _uploaded(
            client,
            admin_auth_header,
            key,
            groups=[str(others.id)] if to_another_group else [],
        ),
        _map("groups-pending-editors", layer, groups=[str(editors.id)]),
        _map("groups-pending-viewers", layer, groups=[str(viewers.id)]),
    )

    assert _layer_gaps(by_role) == []
    [(gap_layer, gap)] = _layer_gaps(without)
    assert (gap_layer, viewers.name in gap) == ("parks", True)


async def test_a_dry_run_judges_a_kept_layer_on_the_pending_dataset_it_moves_to(
    client, admin_auth_header, test_db_session, clean_tables
):
    """A kept publish points a layer's key at a dataset the same request
    creates: the layer stays on its dataset until that one exists, and shows
    it once the maps are sent again."""
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    stored_id = await _dataset(
        test_db_session, editor.id, visibility="internal", name="Stored parks"
    )
    await _apply(
        test_db_session,
        editor,
        _map(
            "groups-pending-move",
            _layer(dataset_id=str(stored_id)),
            visibility="internal",
        ),
    )
    key = "groups-pending-moved-to"

    [checked] = await _dry_run_maps(
        test_db_session,
        editor,
        await _uploaded(client, headers, key, visibility="private"),
        _map(
            "groups-pending-move",
            _layer(dataset_key=key),
            styling="keep",
            visibility="internal",
        ),
    )

    assert (checked.action, checked.styling) == ("update", "kept")
    [(gap_layer, gap)] = _layer_gaps(checked)
    assert gap_layer == "parks"
    assert ("Road centerlines" in gap, "Stored parks" in gap) == (True, False)


async def test_a_dry_run_leaves_a_planned_groups_members_to_the_permission_authority(
    client, admin_auth_header, test_db_session, clean_tables, monkeypatch
):
    """An authority that narrows the community answer, as an overlay may,
    is asked about the groups the entry plans: it admits their members, and
    its denial of one of them stands."""
    from app.modules.catalog import authorization
    from app.modules.catalog.maps import manifest_sharing
    from app.platform.extensions import DefaultPermissionExtension, RecordAudience

    _stage_fixture()
    user = await _admin_user(test_db_session)
    _, reader = await _editor(client, test_db_session, admin_auth_header)
    _, denied = await _editor(client, test_db_session, admin_auth_header)
    admitted = await _group(test_db_session, reader.id)
    narrowed = await _group(test_db_session, reader.id, denied.id)
    key = "groups-pending-authority"
    layer = _layer(dataset_key=key)

    class _DeniesAMember(DefaultPermissionExtension):
        async def record_audience(self, query, user_cls, *, grant_cls=None):
            community = await super().record_audience(
                query, user_cls, grant_cls=grant_cls
            )
            return RecordAudience(
                users=community.users & (user_cls.id != denied.id),
                includes_anonymous=community.includes_anonymous,
            )

    for module in (authorization, manifest_sharing):
        monkeypatch.setattr(module, "get_permission_extension", _DeniesAMember)

    reads, without = await _dry_run_maps(
        test_db_session,
        user,
        await _uploaded(
            client,
            admin_auth_header,
            key,
            groups=[str(admitted.id), str(narrowed.id)],
        ),
        _map("groups-pending-admitted", layer, groups=[str(admitted.id)]),
        _map("groups-pending-narrowed", layer, groups=[str(narrowed.id)]),
    )

    assert _layer_gaps(reads) == []
    [(gap_layer, gap)] = _layer_gaps(without)
    assert (gap_layer, narrowed.name in gap) == ("parks", True)


async def test_a_dry_run_judges_a_reused_job_on_the_groups_it_will_publish(
    client, admin_auth_header, test_db_session, clean_tables
):
    """A queued replacement kept groups A and B, and B was taken off the
    dataset before it ran: the job won't restore B, so the same manifest sent
    again answers for a dataset shared with A only."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    _, reader = await _editor(client, test_db_session, admin_auth_header)
    _, other = await _editor(client, test_db_session, admin_auth_header)
    kept = await _group(test_db_session, reader.id)
    revoked = await _group(test_db_session, other.id)
    key = "groups-pending-reused"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "restricted", "published"
    )
    test_db_session.add_all(
        [
            DatasetGroupGrant(dataset_id=dataset_id, group_id=kept.id),
            DatasetGroupGrant(dataset_id=dataset_id, group_id=revoked.id),
        ]
    )
    await test_db_session.commit()
    entry = await _uploaded(
        client, admin_auth_header, key, groups=[str(kept.id), str(revoked.id)]
    )
    queued, task = await _queue_update(test_db_session, user, entry)
    assert (queued.action, _codes(queued)) == ("update", [])
    await test_db_session.execute(
        delete(DatasetGroupGrant).where(
            DatasetGroupGrant.dataset_id == dataset_id,
            DatasetGroupGrant.group_id == revoked.id,
        )
    )
    await test_db_session.commit()
    layer = _layer(dataset_id=str(dataset_id))

    response, _ = await _apply_entries(
        test_db_session,
        user,
        _entries_request(
            entry,
            dry_run=True,
            maps=[
                _map("groups-pending-reused-kept", layer, groups=[str(kept.id)]),
                _map("groups-pending-reused-gone", layer, groups=[str(revoked.id)]),
            ],
        ),
    )

    [reused] = response.results
    assert (reused.action, reused.job_id) == ("skip", queued.job_id)
    _assert_maps_written(response.maps)
    reads, without = response.maps
    assert _layer_gaps(reads) == []
    [(gap_layer, gap)] = _layer_gaps(without)
    assert (gap_layer, revoked.name in gap) == ("parks", True)
    assert reused.groups == [kept.name]
    job = await _run_update(test_db_session, queued, task)
    assert (job.status, job.error_message) == ("complete", None)
    assert await _dataset_grants(test_db_session, dataset_id) == {kept.id}


async def test_a_dry_run_over_a_reused_job_follows_a_renamed_group(
    client, admin_auth_header, test_db_session, clean_tables
):
    """A queued job shares by group id, so a rename since changes neither
    the job reused nor who reads the layer."""
    _stage_fixture()
    user = await _admin(test_db_session)
    _, reader = await _editor(client, test_db_session, admin_auth_header)
    _, other = await _editor(client, test_db_session, admin_auth_header)
    shared = await _group(test_db_session, user.id, reader.id)
    others = await _group(test_db_session, user.id, other.id)
    key = "groups-pending-renamed"
    entry = _entry(key, visibility="private", groups=[str(shared.id)])
    job = await _in_flight(
        test_db_session,
        user,
        entry,
        manifest_version="2",
        manifest_requested_visibility="private",
        visibility="private",
        manifest_groups=[str(shared.id)],
    )
    job_id = job.id
    renamed = f"zeta-{uuid.uuid4().hex[:8]}"
    await _commit(update(Group).where(Group.id == shared.id).values(name=renamed))
    layer = _layer(dataset_key=key)

    response, _ = await _apply_entries(
        test_db_session,
        user,
        _entries_request(
            entry,
            dry_run=True,
            maps=[
                _map("groups-pending-renamed-map", layer, groups=[str(shared.id)]),
                _map("groups-pending-others-map", layer, groups=[str(others.id)]),
            ],
        ),
    )

    [reused] = response.results
    assert (reused.action, reused.job_id) == ("skip", job_id)
    assert reused.groups == [renamed]
    _assert_maps_written(response.maps)
    reads, without = response.maps
    assert (reads.groups, _layer_gaps(reads)) == ([renamed], [])
    [(gap_layer, gap)] = _layer_gaps(without)
    assert (gap_layer, others.name in gap) == ("parks", True)


async def test_a_reused_job_isnt_answered_for_once_edit_metadata_is_revoked(
    client, admin_auth_header, test_db_session, clean_tables, monkeypatch
):
    """The job will keep the dataset's groups, which the entry can't promise,
    so the entry is refused and its layer has no dataset to be judged on."""
    _stage_fixture()
    headers, editor = await _editor(client, test_db_session, admin_auth_header)
    mine = await _group(test_db_session, editor.id)
    key = "groups-pending-revoked-permission"
    entry = await _uploaded(client, headers, key, groups=[str(mine.id)])
    [queued] = (await _apply_entries(test_db_session, editor, _entries_request(entry)))[
        0
    ].results
    assert queued.action == "create"
    _editors_without(monkeypatch, "edit_metadata")

    response, _ = await _apply_entries(
        test_db_session,
        editor,
        _entries_request(
            entry,
            dry_run=True,
            maps=[
                _map(
                    "groups-pending-revoked-map",
                    _layer(dataset_key=key),
                    groups=[str(mine.id)],
                )
            ],
        ),
    )

    [refused] = response.results
    assert (refused.action, refused.errors) == (
        "error",
        ["Missing permission: edit_metadata"],
    )
    [checked] = response.maps
    assert checked.action == "error"
    assert ("A052", "parks") in [(m.code, m.layer) for m in checked.messages]
    assert _layer_gaps(checked) == []


# A queued replacement's share, one row per way it can end: the dataset's
# level and groups when the entry was applied, the groups the entry names,
# whether a publish key applied it, what changed before the job runs, and the
# groups the dataset is left with. "held-back" rows publish with group b held
# back, which the dry run warns of with A056; "refused" rows fail the job with
# GroupsOutsideEntry and leave the groups as they were.
_QUEUED_SHARES = {
    "unchanged": ("restricted", "ab", "ab", False, None, "published", "ab"),
    "revoked-since": ("restricted", "ab", "ab", False, "revoke-b", "held-back", "a"),
    "granted-since": ("restricted", "a", "a", False, "grant-c", "published", "a"),
    "swap": ("restricted", "a", "b", False, None, "published", "b"),
    "removed": ("restricted", "a", "", False, None, "published", ""),
    "narrowed-addition": ("internal", "a", "ab", False, "narrow", "held-back", "a"),
    "narrowed-swap": ("internal", "a", "b", False, "narrow", "refused", "a"),
    "key-addition": ("restricted", "a", "ab", True, None, "held-back", "a"),
    "key-addition-granted-since": (
        "restricted",
        "a",
        "ab",
        True,
        "grant-c",
        "refused",
        "ac",
    ),
}


def _job_refusals(answer) -> list[tuple[str, str]]:
    """The A056 an entry carries for a matched job that will be refused."""
    return [
        (m.code, m.severity)
        for m in answer.messages
        if "will not replace its data" in m.message
    ]


def _assert_held_back_b(answer, groups, *, held_back: bool) -> None:
    """The answer warns A056 that group b is held back, and of nothing else."""
    assert [(m.code, m.severity) for m in answer.messages] == (
        [("A056", "warning")] if held_back else []
    ), answer.messages
    if held_back:
        assert groups["b"].name in answer.messages[0].message


async def _change_dataset(session, dataset_id, change, groups) -> None:
    if change == "revoke-b":
        await session.execute(
            delete(DatasetGroupGrant).where(
                DatasetGroupGrant.dataset_id == dataset_id,
                DatasetGroupGrant.group_id == groups["b"].id,
            )
        )
    elif change == "grant-c":
        session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=groups["c"].id))
    elif change == "narrow":
        await _set_record(session, dataset_id, "restricted", "published")
    await session.commit()


@pytest.mark.parametrize(
    ("level", "granted", "named", "by_key", "change", "outcome", "left_with"),
    list(_QUEUED_SHARES.values()),
    ids=list(_QUEUED_SHARES),
)
async def test_a_dry_run_over_a_queued_replacement_answers_as_its_job_ends(
    client,
    admin_auth_header,
    test_db_session,
    clean_tables,
    level,
    granted,
    named,
    by_key,
    change,
    outcome,
    left_with,
):
    """The same manifest sent again as a dry run while its replacement is
    queued names the groups the job then leaves, and is refused where the
    job is."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    groups = {letter: await _group(test_db_session, user.id) for letter in "abc"}
    key = f"groups-queued-{uuid.uuid4().hex[:8]}"
    dataset_id = await _manifest_dataset(test_db_session, user, key, level, "published")
    test_db_session.add_all(
        DatasetGroupGrant(dataset_id=dataset_id, group_id=groups[letter].id)
        for letter in granted
    )
    await test_db_session.commit()
    entry = await _uploaded(
        client,
        admin_auth_header,
        key,
        groups=[str(groups[letter].id) for letter in named],
    )

    def scope():
        return _publish_key(test_db_session) if by_key else contextlib.nullcontext()

    with scope():
        queued, task = await _queue_update(test_db_session, user, entry)
    assert queued.action == "update", queued
    await _change_dataset(test_db_session, dataset_id, change, groups)

    with scope():
        response, _ = await _apply_entries(
            test_db_session, user, _entries_request(entry, dry_run=True)
        )
    [answer] = response.results
    # A refused dry run rolled the session back, which expires the user row.
    user = await _admin_user(test_db_session)
    with scope():
        applied, _ = await _apply_entries(
            test_db_session, user, _entries_request(entry)
        )
    [again] = applied.results
    if outcome == "refused" and by_key:
        # The share planned now is refused too, so the job isn't this entry's.
        assert again.errors == ["dataset_busy"], again
    else:
        assert (again.action, again.job_id) == ("skip", queued.job_id)
        assert _job_refusals(again) == (
            [("A056", "warning")] if outcome == "refused" else []
        )

    if outcome != "refused":
        assert (answer.action, answer.job_id) == ("skip", queued.job_id)
        assert sorted(answer.groups) == sorted(groups[g].name for g in left_with)
        _assert_held_back_b(answer, groups, held_back=outcome == "held-back")
        job = await _run_update(test_db_session, queued, task)
        assert (job.status, job.error_message) == ("complete", None)
        # A key's share held back at the apply stores none, so its job has
        # nothing left to hold back.
        assert await _held_back_warnings(job) == (
            [{"group_ids": [str(groups["b"].id)], "reason": "held_back"}]
            if outcome == "held-back" and not by_key
            else []
        )
    else:
        assert answer.action == "error", answer
        with pytest.raises(ValueError, match="groups this publish leaves out"):
            await _run_update(test_db_session, queued, task)
        assert (await _failed_job(test_db_session, queued)).status == "failed"
    assert await _dataset_grants(test_db_session, dataset_id) == {
        groups[letter].id for letter in left_with
    }


async def test_a_dry_run_refuses_a_queued_replacement_its_job_will_refuse(
    client, admin_auth_header, test_db_session, clean_tables
):
    """An internal dataset shared with A, a replacement queued for B, then the
    dataset narrowed: the job holds the swap back and keeps A, which the entry
    leaves out, so the dry run refuses the entry with A056 and its layer has
    no dataset to be judged on. The apply still answers for the queued job,
    with the refusal as a warning."""
    _stage_fixture()
    user = await _admin_user(test_db_session)
    kept = await _group(test_db_session, user.id)
    named = await _group(test_db_session, user.id)
    key = "groups-queued-refused"
    dataset_id = await _manifest_dataset(
        test_db_session, user, key, "internal", "published"
    )
    test_db_session.add(DatasetGroupGrant(dataset_id=dataset_id, group_id=kept.id))
    await test_db_session.commit()
    entry = await _uploaded(client, admin_auth_header, key, groups=[str(named.id)])
    queued, _ = await _queue_update(test_db_session, user, entry)
    assert queued.action == "update", queued
    await _set_record(test_db_session, dataset_id, "restricted", "published")
    layer = _layer(dataset_key=key)
    maps = [_map("groups-queued-refused-map", layer, groups=[str(named.id)])]

    response, _ = await _apply_entries(
        test_db_session, user, _entries_request(entry, dry_run=True, maps=maps)
    )

    [refused] = response.results
    assert refused.action == "error"
    assert [(m.code, m.severity) for m in refused.messages] == [("A056", "error")]
    assert "made visible to fewer people" in refused.messages[0].message
    [checked] = response.maps
    assert ("A052", "parks") in [(m.code, m.layer) for m in checked.messages]
    assert _layer_gaps(checked) == []

    # The refused entry rolled the session back, which expires the user row.
    user = await _admin_user(test_db_session)
    response, _ = await _apply_entries(test_db_session, user, _entries_request(entry))

    [reused] = response.results
    assert (reused.action, reused.job_id) == ("skip", queued.job_id)
    assert reused.groups == [kept.name]
    assert [(m.code, m.severity) for m in reused.messages] == [("A056", "warning")]
    assert reused.messages[0].message == refused.messages[0].message


@pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="needs ogr2ogr")
@pytest.mark.requires_ogr2ogr
@pytest.mark.parametrize(
    ("level", "granted", "named", "change", "accepted", "left_with"),
    [
        ("restricted", "ab", "ab", "revoke-b", True, "a"),
        ("internal", "a", "b", "narrow", False, "a"),
    ],
    ids=["revoked-since", "narrowed-swap"],
)
async def test_a_dry_run_over_a_held_replacement_answers_as_its_accept_ends(
    test_db_session, clean_tables, level, granted, named, change, accepted, left_with
):
    """A dry run of a held replacement's unchanged entry names the groups
    Accept leaves the dataset with, and is refused where Accept's publish is."""
    user = await _admin_user(test_db_session)
    groups = {letter: await _group(test_db_session, user.id) for letter in "ab"}
    request = ManifestApplyRequest.model_validate(
        {
            "manifest_version": "2",
            "catalog": {"title": "Manifest catalog"},
            "client": {"id": "geolens-qgis", "version": "0.2.0"},
            "datasets": [
                {
                    **_held_entry(
                        _HELD_KEY, title="Resurveyed roads", intent="published"
                    ),
                    "groups": [str(groups[letter].id) for letter in named],
                }
            ],
        }
    )
    held = await _held_apply(
        test_db_session,
        request,
        visibility=level,
        group_ids=[groups[letter].id for letter in granted],
    )
    await _change_dataset(test_db_session, held.dataset_id, change, groups)

    with _reupload_task():
        response = await apply_manifest(
            test_db_session,
            request.model_copy(update={"dry_run": True}),
            held.user,
            _held_http_request(),
        )
    [answer] = response.results
    # A refused dry run rolled the session back, which expires the user row.
    held = dataclasses.replace(held, user=await _admin_user(test_db_session))
    with _reupload_task():
        applied = await apply_manifest(
            test_db_session, request, held.user, _held_http_request()
        )
    [again] = applied.results
    assert (again.action, again.run_id) == ("blocked", held.run_id)
    assert _job_refusals(again) == ([] if accepted else [("A056", "warning")])
    held = dataclasses.replace(held, user=await _admin_user(test_db_session))

    if accepted:
        assert (answer.action, answer.run_id) == ("blocked", held.run_id)
        assert sorted(answer.groups) == sorted(groups[g].name for g in left_with)
        _assert_held_back_b(answer, groups, held_back=True)
        job = await _accept(test_db_session, held, publish_key=False)
        assert (job.status, job.error_message) == ("complete", None)
    else:
        assert answer.action == "error", answer
        assert [(m.code, m.severity) for m in answer.messages] == [("A056", "error")]
        with pytest.raises(ValueError, match="groups this publish leaves out"):
            await _accept(test_db_session, held, publish_key=False)
    assert await _dataset_grants(test_db_session, held.dataset_id) == {
        groups[letter].id for letter in left_with
    }
