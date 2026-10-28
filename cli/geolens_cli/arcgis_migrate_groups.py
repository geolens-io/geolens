# SPDX-License-Identifier: Apache-2.0
"""Share migrated items the way the portal shared them.

Hand-maintained. An item shared only with ArcGIS groups gets the plan
visibility ``restricted``. Before the items run, each such group resolves to
a GeoLens group through ``group_map``: the existing group its
``geolens_group`` names, or one this command creates, named after the
ArcGIS group, and fills with the group's members. Members resolve like
owners, through ``owner_map`` or else by the same name in GeoLens, when the
email the inventory read for them is the account's; one that doesn't resolve
yet, or whose add GeoLens refused, stays pending and is added by a later run.
A member this command added to a group it created is removed again once
none of the ArcGIS names it added them for is listed; members added or
removed in GeoLens stay as they are.
Members of an existing group are left as they are, since adding to it would
also give them everything else that group can read; the ArcGIS members it
lacks are recorded instead.

An item's datasets and map are then shared with those groups as the
operator, an admin. A rerun follows the plan: it adds the groups the item now
names and removes those its own writes added that the item no longer names.
Groups shared in GeoLens stay, and one this command shared a dataset or map
with is not added to it again, so a group someone removed in GeoLens stays
removed. A restricted item none of whose groups maps to a GeoLens group
becomes private. Under ``restrict_public_visibility`` a public
item whose owner isn't an admin becomes internal, as GeoLens would refuse
that owner public.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from .arcgis_migrate_session import GeoLensError, ItemFailed, MigrationContext
from .arcgis_migrate_state import ItemState, MigrationState

RESTRICTED = "restricted"
MAX_NAME = 255
GROUP_PAGE = 200
# The most users one add-members request accepts.
MEMBER_BATCH = 500
FALLBACK_PREFIX = "ArcGIS"
# The plan actions whose datasets or map are shared with groups.
_SHARED_ACTIONS = ("import_layers", "import_file", "import_map")


class GroupUsageError(Exception):
    """``group_map`` names a GeoLens group that can't be used."""


@dataclass
class Sharing:
    """How this run turns the plan's sharing into GeoLens sharing."""

    # ArcGIS group id -> GeoLens group id; None when it maps to none.
    groups: dict[str, str | None] = field(default_factory=dict)
    restrict_public: bool = False
    # GeoLens user ids holding the admin role.
    admins: frozenset[str] = frozenset()

    def target(
        self, item: Mapping[str, Any], owner_id: str | None
    ) -> tuple[Mapping[str, Any], list[str]]:
        """*item* with the visibility and GeoLens groups this run gives it,
        and notes saying where that differs from the plan."""
        target = dict(item["target"])
        wanted = target["visibility"]
        notes: list[str] = []
        target["geolens_groups"] = []
        if wanted == RESTRICTED:
            ids = sorted(
                {g for a in target["groups"] or [] if (g := self.groups.get(a))}
            )
            if ids:
                target["geolens_groups"] = ids
            else:
                target["visibility"] = "private"
                notes.append(
                    "made private: it is shared only with ArcGIS groups, and none "
                    "of them maps to a GeoLens group"
                )
        elif (
            wanted == "public" and self.restrict_public and owner_id not in self.admins
        ):
            target["visibility"] = "internal"
            notes.append(
                "made internal, not public: restrict_public_visibility is on and "
                "its owner isn't a GeoLens admin"
            )
        return {**item, "target": target}, notes


def _list_groups(geolens: Any) -> list[Any]:
    from geolens.api.admin import list_groups_admin_groups_get as list_groups

    groups: list[Any] = []
    while True:
        page = geolens.call(
            list_groups.sync_detailed, skip=len(groups), limit=GROUP_PAGE
        )
        groups.extend(page.groups)
        if not page.groups or len(groups) >= page.total:
            return groups


def _member_ids(geolens: Any, group_id: str) -> set[str]:
    from geolens.api.admin import (
        list_group_members_admin_groups_group_id_members_get as list_members,
    )

    members: list[Any] = []
    while True:
        page = geolens.call(
            list_members.sync_detailed,
            group_id=UUID(group_id),
            skip=len(members),
            limit=GROUP_PAGE,
        )
        members.extend(page.members)
        if not page.members or len(members) >= page.total:
            return {str(m.id) for m in members}


def _nfc(name: str) -> str:
    # GeoLens stores group names stripped and NFC-normalized.
    return unicodedata.normalize("NFC", name.strip())


def _find(groups: Iterable[Any], name: str) -> Any | None:
    """The group *name* names: the one with exactly that name, else the only
    one whose name differs from it in case alone. Names are unique only as
    written, so several of those is a ``GroupUsageError``."""
    wanted = _nfc(name)
    groups = list(groups)
    exact = next((g for g in groups if g.name == wanted), None)
    if exact is not None:
        return exact
    folded = [g for g in groups if g.name.casefold() == wanted.casefold()]
    if len(folded) > 1:
        raise GroupUsageError(
            f"GeoLens has several groups named {name} apart from case ("
            + ", ".join(sorted(g.name for g in folded))
            + "); set geolens_group to the exact name"
        )
    return folded[0] if folded else None


def _taken(groups: Iterable[Any], name: str) -> bool:
    """Whether creating a group named *name* would collide, as the server
    compares names."""
    wanted = _nfc(name[:MAX_NAME])
    return any(g.name == wanted for g in groups)


def _create(geolens: Any, name: str) -> Any | None:
    """The new group, or None when the name is taken."""
    from geolens.api.admin import create_group_admin_groups_post as create
    from geolens.models.group_write import GroupWrite

    try:
        return geolens.call(
            create.sync_detailed, body=GroupWrite(name=name[:MAX_NAME]), expected=201
        )
    except GeoLensError as exc:
        if exc.status == 409:
            return None
        raise


def _exists(geolens: Any, group_id: str) -> bool:
    from geolens.api.admin import get_group_admin_groups_group_id_get as get

    try:
        geolens.call(get.sync_detailed, group_id=UUID(group_id))
    except GeoLensError as exc:
        if exc.status == 404:
            return False
        raise
    return True


def _title(
    group_id: str, entry: Mapping[str, Any], inventory: Mapping[str, Any]
) -> str:
    return (
        str((inventory.get(group_id) or {}).get("title") or "")
        or str(entry.get("collection") or "")
        or group_id
    )


def wanted_groups(
    plan: Mapping[str, Any], items: Iterable[Mapping[str, Any]]
) -> list[str]:
    """The ArcGIS groups that *items* to import, shared only with groups, are
    shared with; an item left out, exported or not run makes no group."""
    return sorted(
        {
            group
            for item in items
            if item["action"] in _SHARED_ACTIONS
            and not item.get("removed")
            and not item.get("unlisted")
            and item["target"]["visibility"] == RESTRICTED
            for group in item["target"]["groups"] or []
        }
    )


@dataclass
class GroupPlan:
    """What preparing the groups did, or in a dry run would do."""

    # ArcGIS group id -> {"name", "id", "created", "members", ...}.
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Requests that failed; the run exits non-zero.
    failures: list[str] = field(default_factory=list)
    # ArcGIS group id -> the GeoLens users this run removed from its group.
    removed: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class _Members:
    """How an ArcGIS group's members resolve to GeoLens users."""

    users: list[tuple[str, Any]] = field(default_factory=list)
    pending: list[dict[str, str]] = field(default_factory=list)
    unread: str | None = None
    # Every ArcGIS username the inventory listed, resolved or not, folded.
    listed: set[str] = field(default_factory=set)


def _resolve_member(
    directory: Any, plan: Mapping[str, Any], emails: Mapping[str, str], username: str
) -> tuple[Any, str | None]:
    """The active GeoLens user an ArcGIS member is, or why there's none yet.

    A member found by their ArcGIS name rather than through ``owner_map`` is
    taken only when the email the inventory read for them, if any, is the
    account's, since a same-named account may be somebody else's.
    """
    from .arcgis_migrate import UsageError

    mapped = plan["owner_map"].get(username)
    name = mapped or username
    try:
        user = directory.find(name)
    except UsageError as exc:
        return None, str(exc)
    if user is None:
        return None, f"{name} is not a GeoLens user yet"
    known = emails.get(username)
    if not mapped and known and (user.email or "").lower() != known.lower():
        return None, (
            f"GeoLens user {user.username} has another email than ArcGIS user "
            f"{username}; map them in owner_map if they are the same person"
        )
    inactive = directory.inactive(user)
    return (None, inactive) if inactive else (user, None)


def _resolve_members(
    directory: Any,
    plan: Mapping[str, Any],
    emails: Mapping[str, str],
    members: Mapping[str, Any],
) -> _Members:
    out = _Members()
    if members.get("members") is None:
        out.unread = (
            members.get("members_unread") or "the inventory didn't read its members"
        )
    for username in members.get("members") or []:
        out.listed.add(username.casefold())
        user, reason = _resolve_member(directory, plan, emails, username)
        if user is None:
            out.pending.append({"member": username, "reason": str(reason)})
        else:
            out.users.append((username, user))
    return out


def _fill(
    geolens: Any,
    record: dict[str, Any],
    members: _Members,
    dry_run: bool,
) -> str | None:
    """Add the members who resolve to the group this command created, and
    record those who don't yet, a refused add among them; why adding failed,
    or None.

    Every user it adds, or finds already in the group, is recorded in
    ``added`` and never added again, so a member someone removes in GeoLens
    stays removed. Only those it adds itself go in ``joined``, with the
    ArcGIS names they were added for; one no longer in the group is dropped
    from it, so a member someone removed and added back by hand is theirs.
    """
    from geolens.api.admin import (
        add_group_members_admin_groups_group_id_members_post as add,
    )
    from geolens.models.group_members_add import GroupMembersAdd

    record["members_unread"] = members.unread
    record["pending"] = list(members.pending)
    record["members"] = {name: user.username for name, user in members.users}
    added = set(record.get("added") or [])
    joined = {u: set(names) for u, names in (record.get("joined") or {}).items()}
    present = _member_ids(geolens, record["id"]) if record.get("id") else None
    if present is not None:
        joined = {u: names for u, names in joined.items() if u in present}
    new: dict[str, set[str]] = {}
    for name, user in members.users:
        user_id = str(user.id)
        if user_id in joined:
            joined[user_id].add(name)
        elif user_id in added:
            continue
        elif present is not None and user_id in present:
            added.add(user_id)
        else:
            new.setdefault(user_id, set()).add(name)
    pending = list(new.items())
    failed = None
    for start in range(0, len(pending), MEMBER_BATCH):
        batch = pending[start : start + MEMBER_BATCH]
        if not dry_run:
            try:
                geolens.call(
                    add.sync_detailed,
                    group_id=UUID(record["id"]),
                    body=GroupMembersAdd(user_ids=[UUID(u) for u, _n in batch]),
                )
            except GeoLensError as exc:
                failed = (
                    f"adding members to GeoLens group {record['name']} failed, {exc}"
                )
                for _user_id, names in pending[start:]:
                    for name in sorted(names):
                        record["members"].pop(name, None)
                        record["pending"].append(
                            {
                                "member": name,
                                "reason": f"{failed}; a later run tries again",
                            }
                        )
                break
        for user_id, names in batch:
            added.add(user_id)
            joined[user_id] = names
    record["added"] = sorted(added)
    record["joined"] = {u: sorted(names) for u, names in sorted(joined.items())}
    return failed


def _prune(
    geolens: Any,
    record: dict[str, Any],
    members: _Members,
    names: Mapping[str, str],
    dry_run: bool,
    earlier: list[str] | None = None,
) -> tuple[list[str], str | None, list[str]]:
    """Remove from the group this command created each member it added once
    none of the ArcGIS names they were added for is listed any more. Returns
    who it removed, why a removal failed or None, and warnings.

    Nothing is removed while the ArcGIS members weren't read, and a listed
    member who no longer resolves keeps the user they were added as.
    *earlier* lists the members a group record from before ``joined`` was
    kept says this command added, which it can't tell from anyone else's: it
    removes none of them and says so, once, since the record then has
    ``joined``. *names* maps GeoLens user ids to usernames for the report.
    """
    from geolens.api.admin import (
        remove_group_member_admin_groups_group_id_members_user_id_delete as remove,
    )

    warnings = []
    if earlier:
        warnings.append(
            f"GeoLens group {record['name']} has members an earlier version of "
            "this command added without recording which ArcGIS member each was "
            "for, so none of them is removed when they leave the ArcGIS group; "
            "check them by hand: " + ", ".join(names.get(u, u) for u in earlier)
        )
    if members.unread is not None:
        return [], None, warnings
    joined = dict(record.get("joined") or {})
    removed: list[str] = []
    for user_id, given in sorted(joined.items()):
        if any(name.casefold() in members.listed for name in given):
            continue
        if not dry_run:
            try:
                geolens.call(
                    remove.sync_detailed,
                    group_id=UUID(record["id"]),
                    user_id=UUID(user_id),
                    expected=204,
                )
            except GeoLensError as exc:
                if exc.status != 404:
                    return (
                        removed,
                        f"removing a member who left ArcGIS group "
                        f"{record['name']} from its GeoLens group failed, {exc}",
                        warnings,
                    )
                # Someone removed them in GeoLens already; that stays.
                del joined[user_id]
                record["joined"] = joined
                continue
            del joined[user_id]
            record["joined"] = joined
            record["added"] = sorted(set(record.get("added") or []) - {user_id})
        removed.append(names.get(user_id, user_id))
    return removed, None, warnings


def _named(geolens: Any, found: Any, members: _Members) -> dict[str, Any]:
    """The record of an existing group ``group_map`` names: which ArcGIS
    members it lacks, since this command leaves its members as they are."""
    in_group = _member_ids(geolens, str(found.id))
    record: dict[str, Any] = {
        "id": str(found.id),
        "name": found.name,
        "created": False,
        "members_unread": members.unread,
        "members": {},
        "unsynced": list(members.pending),
    }
    for name, user in members.users:
        if str(user.id) in in_group:
            record["members"][name] = user.username
        else:
            record["unsynced"].append(
                {"member": name, "reason": f"GeoLens user {user.username} isn't in it"}
            )
    return record


def _both_taken(arcgis_id: str, title: str, prefix: str) -> GroupUsageError:
    return GroupUsageError(
        f"GeoLens already has groups named {title} and {prefix} - {title}; set "
        f"group_map {arcgis_id} geolens_group to the one to share with"
    )


def prepare_groups(
    geolens: Any,
    plan: Mapping[str, Any],
    inventory_groups: Mapping[str, Mapping[str, Any]],
    state: MigrationState,
    directory: Any,
    items: Iterable[Mapping[str, Any]],
    *,
    dry_run: bool,
    emails: Mapping[str, str] | None = None,
) -> GroupPlan:
    """Resolve every ArcGIS group *items* need to a GeoLens group, creating
    and filling it unless ``group_map`` points at an existing one.

    *emails* holds what the inventory read of ArcGIS users' addresses. Each
    group this command creates is recorded in the state as soon as it exists,
    so a rerun fills it rather than creating another. A ``GroupUsageError``
    when ``group_map`` names a group GeoLens doesn't have, or one several
    groups' names match apart from case, or a group's name and its prefixed
    form are both taken by groups this command didn't create.
    """
    out = GroupPlan()
    wanted = wanted_groups(plan, items)
    if not wanted:
        return out
    existing = _list_groups(geolens)
    prefix = FALLBACK_PREFIX
    for arcgis_id in wanted:
        entry = plan["group_map"].get(arcgis_id) or {}
        named = entry.get("geolens_group")
        recorded = state.groups.get(arcgis_id)
        if named == "":
            # Recorded, so cutover and the report follow the current choice;
            # a group this command made is kept for a later remap to reuse.
            state.groups[arcgis_id] = {
                **(recorded or {"id": None, "name": None, "created": False}),
                "unmapped": True,
            }
            state.save()
            out.groups[arcgis_id] = {"id": None, "name": None, "created": False}
            continue
        members = _resolve_members(
            directory, plan, emails or {}, inventory_groups.get(arcgis_id) or {}
        )
        if named:
            found = _find(existing, named)
            if found is None:
                raise GroupUsageError(
                    f"group_map {arcgis_id} names GeoLens group {named}, which "
                    "doesn't exist; create it or change geolens_group"
                )
            record = _named(geolens, found, members)
            if not dry_run:
                state.groups[arcgis_id] = record
                state.save()
            out.groups[arcgis_id] = record
            continue
        title = _title(arcgis_id, entry, inventory_groups)
        if recorded and recorded.get("created") and recorded.get("id"):
            record = dict(recorded)
            record.pop("unmapped", None)
            if record.get("deleted") or not _exists(geolens, record["id"]):
                out.warnings.append(
                    f"the GeoLens group {record['name']} this command created for "
                    f"ArcGIS group {arcgis_id} was deleted in GeoLens, so its items "
                    "are shared with no group for it; set geolens_group to share "
                    "with another"
                )
                if not dry_run and not record.get("deleted"):
                    state.groups[arcgis_id] = {**record, "deleted": True}
                    state.save()
                out.groups[arcgis_id] = {"id": None, "name": None, "created": False}
                continue
        elif dry_run:
            names = (title, f"{prefix} - {title}")
            free = [n for n in names if not _taken(existing, n)]
            if not free:
                raise _both_taken(arcgis_id, title, prefix)
            record = {
                "id": None,
                "name": free[0],
                "created": True,
                "added": [],
                "joined": {},
            }
        else:
            record = None
            for name in (title, f"{prefix} - {title}"):
                created = _create(geolens, name)
                if created is not None:
                    record = {
                        "id": str(created.id),
                        "name": created.name,
                        "created": True,
                        "added": [],
                        "joined": {},
                    }
                    break
            if record is None:
                raise _both_taken(arcgis_id, title, prefix)
            state.groups[arcgis_id] = record
            state.save()
        earlier = None if "joined" in record else sorted(record.get("added") or [])
        failed = _fill(geolens, record, members, dry_run)
        if failed:
            out.failures.append(failed)
        removed, failed, notes = _prune(
            geolens,
            record,
            members,
            getattr(directory, "usernames", {}),
            dry_run,
            earlier,
        )
        out.warnings.extend(notes)
        if failed:
            out.failures.append(failed)
        if not dry_run:
            state.groups[arcgis_id] = record
            state.save()
        out.removed[arcgis_id] = removed
        out.groups[arcgis_id] = {**record, "removed": removed}
    return out


def _dataset_groups(dataset: Any) -> set[str]:
    groups = getattr(dataset, "groups", None)
    return {str(g.id) for g in groups} if isinstance(groups, list) else set()


def _changes(
    target: Mapping[str, Any], entry: ItemState, object_id: str
) -> tuple[set[str], set[str]]:
    """The groups to add to one of the item's objects, those this command
    hasn't shared it with yet, and those to remove: groups its own writes
    added that the target no longer names, none while the item's ArcGIS
    groups weren't read."""
    wanted = set(target["geolens_groups"] or [])
    new = wanted - set(entry.groups.get(object_id) or [])
    granted = set(entry.granted.get(object_id) or [])
    gone = granted - wanted if target.get("groups") is not None else set()
    return new, gone


def pending_sharing(item: Mapping[str, Any], entry: ItemState) -> list[str]:
    """Why a rerun that didn't share the item leaves its groups behind the
    plan: the groups each of its objects would gain or lose."""
    target = item["target"]
    if "geolens_groups" not in target:
        return []
    out = []
    for object_id in [*entry.dataset_ids, *([entry.map_id] if entry.map_id else [])]:
        new, gone = _changes(target, entry, object_id)
        changes = [
            f"{verb} {', '.join(sorted(ids))}"
            for verb, ids in (("add", new), ("remove", gone))
            if ids
        ]
        if changes:
            what = "map" if object_id == entry.map_id else "dataset"
            out.append(
                f"{what} {object_id} still needs its groups changed "
                f"({'; '.join(changes)}), which waits until the item is up to date"
            )
    return out


def share(
    ctx: MigrationContext,
    item: Mapping[str, Any],
    entry: ItemState,
    *,
    with_map: bool = True,
) -> list[str]:
    """Bring the groups each of the item's datasets, and its map, is shared
    with to the ones its target names: add those this command hasn't shared
    that object with yet, and remove those its own writes added that the
    target no longer names. Groups shared in GeoLens stay, and so does a group
    someone removed there. Nothing is removed while the item's ArcGIS groups
    weren't read. Each share is recorded as it lands.

    With *with_map* (the import) the map only gains groups; without it (a
    rerun) the map is changed only while it is as this command left it, and
    the reasons it couldn't be are returned.
    """
    from geolens.api.datasets_metadata import (
        set_dataset_groups_endpoint_datasets_dataset_id_groups_put as put_dataset,
    )
    from geolens.models.dataset_groups_update import DatasetGroupsUpdate

    from .arcgis_migrate_refresh import changed_in_geolens, get_dataset, snapshot

    target = item["target"]
    if "geolens_groups" not in target:
        return []
    try:
        for dataset_id in entry.dataset_ids:
            new, gone = _changes(target, entry, dataset_id)
            if not new and not gone and not entry.granted.get(dataset_id):
                continue
            before = get_dataset(ctx, dataset_id)
            gone &= _held(ctx, entry, dataset_id, _dataset_groups(before))
            if not new and not gone:
                continue
            baseline = dataset_id in entry.last_update
            changed = (
                changed_in_geolens(ctx, entry, dataset_id, before) if baseline else None
            )
            if changed:
                raise ItemFailed(
                    f"dataset {dataset_id} was {changed}, so its groups weren't "
                    "changed; it was left as it is"
                )
            # The write replaces the whole list and takes no precondition, so
            # the grants are read again right before it; a change landing
            # between that read and the write is still overwritten.
            again = get_dataset(ctx, dataset_id)
            if baseline and snapshot(again) != snapshot(before):
                raise ItemFailed(
                    f"dataset {dataset_id} changed in GeoLens while its groups were "
                    "read; it was left as it is"
                )
            current = _dataset_groups(again)
            groups = (current | new) - gone
            # GeoLens makes a private dataset shared with any group restricted.
            if (
                groups != current
                and groups
                and getattr(again, "visibility", None) == "private"
                and target["visibility"] != RESTRICTED
            ):
                raise ItemFailed(
                    f"dataset {dataset_id} is private, and keeping groups "
                    f"{', '.join(sorted(groups))} on it would make it restricted; "
                    "it was left as it is. Remove those groups from it by hand"
                )
            if groups != current:
                ctx.geolens.call(
                    put_dataset.sync_detailed,
                    dataset_id=UUID(dataset_id),
                    body=DatasetGroupsUpdate(
                        group_ids=[UUID(g) for g in sorted(groups)]
                    ),
                )
                if baseline:
                    _record_share(ctx, entry, dataset_id, before)
            _shared(entry, dataset_id, new, gone, added=new - current)
            ctx.save()
        map_id = entry.map_id
        if not map_id:
            return []
        new, gone = _changes(target, entry, map_id)
        if with_map:
            if new:
                added = _share_map(ctx, map_id, new, set())
                _shared(entry, map_id, new, set(), added=added)
                ctx.save()
            return []
        return _merge_map(ctx, target, entry, map_id, new, gone)
    except GeoLensError as exc:
        raise ItemFailed(f"sharing it with its GeoLens groups failed, {exc}") from None


def _held(
    ctx: MigrationContext, entry: ItemState, object_id: str, current: set[str]
) -> set[str]:
    """The groups this command's writes gave the object that it still has.
    One someone removed in GeoLens is no longer counted as this command's, so
    a later run never removes it after they share it again; ``entry.groups``
    still keeps it from being added back."""
    granted = set(entry.granted.get(object_id) or [])
    held = granted & current
    if held != granted:
        if held:
            entry.granted[object_id] = sorted(held)
        else:
            entry.granted.pop(object_id, None)
        ctx.save()
    return held


def _shared(
    entry: ItemState, object_id: str, new: set[str], gone: set[str], *, added: set[str]
) -> None:
    """Record a share of one object: *new* groups it now has from this
    command, *gone* ones it removed, and the groups its write *added*."""
    for record, groups in (
        (entry.groups, (set(entry.groups.get(object_id) or []) | new) - gone),
        (entry.granted, (set(entry.granted.get(object_id) or []) | added) - gone),
    ):
        if groups:
            record[object_id] = sorted(groups)
        else:
            record.pop(object_id, None)


def _merge_map(
    ctx: MigrationContext,
    target: Mapping[str, Any],
    entry: ItemState,
    map_id: str,
    new: set[str],
    gone: set[str],
) -> list[str]:
    """On a rerun, add *new* groups to the item's map and remove *gone* ones
    while the map is as this command left it and its sharing is a matter of
    groups (private or restricted, here and in the target); why the map isn't
    shared as the target says."""
    from .arcgis_migrate_webmaps import get_map, map_state, map_visibility

    found = get_map(ctx.geolens, map_id)
    gone &= _held(ctx, entry, map_id, _dataset_groups(found))
    wanted = target["visibility"]
    if new or gone:
        if entry.map_snapshot is None:
            return [
                "the state doesn't record how this command left its GeoLens map, "
                "so its groups were left as they are; share it by hand"
            ]
        if map_state(found) != entry.map_snapshot:
            return [
                "its GeoLens map was changed in GeoLens since the last run, so its "
                "groups were left as they are; share it by hand"
            ]
        groups = (_dataset_groups(found) | new) - gone
        if map_visibility(found) == "private" and groups and wanted != RESTRICTED:
            return [
                "its GeoLens map is private, and sharing it with groups "
                f"{', '.join(sorted(groups))} would make it restricted, which the "
                "plan doesn't say; its groups were left as they are"
            ]
        if {map_visibility(found), wanted} <= {"private", RESTRICTED}:
            added = _share_map(ctx, map_id, new, gone, entry.map_snapshot)
            if added is None:
                return [
                    "its GeoLens map changed in GeoLens while its groups were "
                    "read, so they were left as they are; share it by hand"
                ]
            after = get_map(ctx.geolens, map_id)
            # A grant change moves the map's timestamp only when it flips the
            # map between private and restricted; any other move is someone
            # else's edit, which a later run reports.
            made = RESTRICTED if groups else "private"
            if (
                str(after.created_by) == str(found.created_by)
                and map_visibility(after) == made
                and (
                    after.updated_at == found.updated_at
                    or map_visibility(found) != made
                )
            ):
                entry.map_snapshot = map_state(after)
            _shared(entry, map_id, new, gone, added=added)
            ctx.save()
            found = after
    current = map_visibility(found)
    if current != wanted:
        return [
            f"the plan gives the web map visibility {wanted} but the GeoLens map "
            f"is {current}; set it by hand"
        ]
    return []


def _record_share(
    ctx: MigrationContext, entry: ItemState, dataset_id: str, before: Any
) -> None:
    """Record the dataset as the share left it as this command's write, only
    while the share is the one change since *before*: the same data and
    feature count, and no other writer. Anything else stays unrecorded, so a
    rerun sees it as a change made in GeoLens and leaves the dataset alone."""
    from .arcgis_migrate_refresh import get_dataset, record, snapshot
    from .refresh import _value

    after = get_dataset(ctx, dataset_id)
    was, now = snapshot(before), snapshot(after)
    writer = str(_value(getattr(after, "updated_by", None)))
    same_writer = writer in (
        str(_value(getattr(before, "updated_by", None))),
        str(ctx.operator_id),
    )
    if (
        now["data_revision"] != was["data_revision"]
        or now["feature_count"] != was["feature_count"]
        or not same_writer
    ):
        raise ItemFailed(
            f"dataset {dataset_id} changed in GeoLens while it was shared with "
            "its new groups; it was left as it is"
        )
    record(entry, dataset_id, after)


def _share_map(
    ctx: MigrationContext,
    map_id: str,
    new: set[str],
    gone: set[str],
    left: Mapping[str, Any] | None = None,
) -> set[str] | None:
    """Share the map with its current groups plus *new* minus *gone*; the
    groups the write added. With *left*, the map as this command left it,
    nothing is written and None returned once the map no longer matches."""
    from geolens.api.maps import set_map_groups_endpoint_maps_map_id_groups_put as put
    from geolens.models.map_groups_update import MapGroupsUpdate

    from .arcgis_migrate_webmaps import get_map, map_state

    read = get_map(ctx.geolens, map_id)
    if left is not None and map_state(read) != left:
        return None
    current = _dataset_groups(read)
    groups = (current | new) - gone
    if groups == current:
        return set()
    # Each layer's dataset is shared as its own plan item says, so layers
    # a group can't read stay hidden from it rather than being widened.
    ctx.geolens.call(
        put.sync_detailed,
        map_id=UUID(map_id),
        body=MapGroupsUpdate(
            group_ids=[UUID(g) for g in sorted(groups)], confirm="map_only"
        ),
    )
    return groups - current
