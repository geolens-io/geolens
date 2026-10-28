# SPDX-License-Identifier: Apache-2.0
"""Share migrated items the way the portal shared them.

Hand-maintained. An item shared only with ArcGIS groups gets the plan
visibility ``restricted``. Before the items run, each such group resolves to
a GeoLens group through ``group_map``: the existing group its
``geolens_group`` names, or one this command creates, named after the
ArcGIS group, and fills with the group's members. Members resolve like
owners, through ``owner_map`` or else by the same name in GeoLens; one that
doesn't resolve yet stays pending and is added by a later run. Members of an
existing group are left as they are, since adding to it would also give them
everything else that group can read.

An item's datasets and map are then shared with those groups as the
operator, an admin. Groups are only ever added, never removed, and one this
command shared an item with is not added again, so a group someone removed
in GeoLens stays removed. A restricted item none of whose groups maps to a
GeoLens group becomes private. Under ``restrict_public_visibility`` a public
item whose owner isn't an admin becomes internal, as GeoLens would refuse
that owner public.
"""

from __future__ import annotations

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


def _find(groups: Iterable[Any], name: str) -> Any | None:
    wanted = name.strip().casefold()
    return next((g for g in groups if g.name.casefold() == wanted), None)


def _create(geolens: Any, name: str) -> str | None:
    """The new group's id, or None when the name is taken."""
    from geolens.api.admin import create_group_admin_groups_post as create
    from geolens.models.group_write import GroupWrite

    try:
        created = geolens.call(
            create.sync_detailed, body=GroupWrite(name=name[:MAX_NAME]), expected=201
        )
    except GeoLensError as exc:
        if exc.status == 409:
            return None
        raise
    return str(created.id)


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
    """The ArcGIS groups that *items* shared only with groups are shared with."""
    return sorted(
        {
            group
            for item in items
            if not item.get("removed") and item["target"]["visibility"] == RESTRICTED
            for group in item["target"]["groups"] or []
        }
    )


@dataclass
class GroupPlan:
    """What preparing the groups did, or in a dry run would do."""

    # ArcGIS group id -> {"name", "id", "created", "added", "pending", ...}.
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _resolve_member(
    directory: Any, plan: Mapping[str, Any], username: str
) -> tuple[Any, str | None]:
    """The active GeoLens user an ArcGIS member is, or why there's none yet."""
    from .arcgis_migrate import UsageError

    name = plan["owner_map"].get(username) or username
    try:
        user = directory.find(name)
    except UsageError as exc:
        return None, str(exc)
    if user is None:
        return None, f"{name} is not a GeoLens user yet"
    inactive = directory.inactive(user)
    return (None, inactive) if inactive else (user, None)


def _add_members(geolens: Any, group_id: str, user_ids: list[str]) -> None:
    from geolens.api.admin import (
        add_group_members_admin_groups_group_id_members_post as add,
    )
    from geolens.models.group_members_add import GroupMembersAdd

    for start in range(0, len(user_ids), MEMBER_BATCH):
        geolens.call(
            add.sync_detailed,
            group_id=UUID(group_id),
            body=GroupMembersAdd(
                user_ids=[UUID(u) for u in user_ids[start : start + MEMBER_BATCH]]
            ),
        )


def _fill(
    geolens: Any,
    record: dict[str, Any],
    members: Mapping[str, Any],
    plan: Mapping[str, Any],
    directory: Any,
    dry_run: bool,
) -> str | None:
    """Add the ArcGIS group's members who resolve to the group this command
    created, and record those who don't yet; why adding them failed, or None."""
    record["members_unread"] = (
        None
        if members.get("members") is not None
        else members.get("members_unread") or "the inventory didn't read its members"
    )
    record["pending"] = []
    new: list[str] = []
    for username in members.get("members") or []:
        user, reason = _resolve_member(directory, plan, username)
        if user is None:
            record["pending"].append({"member": username, "reason": reason})
        elif str(user.id) not in record["added"] and str(user.id) not in new:
            new.append(str(user.id))
    if new and not dry_run:
        try:
            _add_members(geolens, record["id"], new)
        except GeoLensError as exc:
            return (
                f"adding members to GeoLens group {record['name']} failed, {exc}; "
                "a later run tries again"
            )
    record["added"] = sorted({*record["added"], *new})
    return None


def prepare_groups(
    geolens: Any,
    plan: Mapping[str, Any],
    inventory_groups: Mapping[str, Mapping[str, Any]],
    state: MigrationState,
    directory: Any,
    items: Iterable[Mapping[str, Any]],
    *,
    dry_run: bool,
) -> GroupPlan:
    """Resolve every ArcGIS group *items* need to a GeoLens group, creating
    and filling it unless ``group_map`` points at an existing one.

    Each group this command creates is recorded in the state as soon as it
    exists, so a rerun fills it rather than creating another. A
    ``GroupUsageError`` when ``group_map`` names a group GeoLens doesn't have,
    or a group's name and its prefixed form are both taken by groups this
    command didn't create.
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
            out.groups[arcgis_id] = {"id": None, "name": None, "created": False}
            continue
        if named:
            found = _find(existing, named)
            if found is None:
                raise GroupUsageError(
                    f"group_map {arcgis_id} names GeoLens group {named}, which "
                    "doesn't exist; create it or change geolens_group"
                )
            out.groups[arcgis_id] = {
                "id": str(found.id),
                "name": found.name,
                "created": False,
            }
            continue
        title = _title(arcgis_id, entry, inventory_groups)
        if recorded and recorded.get("created") and recorded.get("id"):
            record = dict(recorded)
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
            taken = [n for n in (title, f"{prefix} - {title}") if _find(existing, n)]
            if len(taken) == 2:
                out.warnings.append(
                    f"GeoLens already has groups named {title} and {prefix} - "
                    f"{title}, so the run will stop; set group_map {arcgis_id} "
                    "geolens_group to the one to share with"
                )
            record = {
                "id": None,
                "name": f"{prefix} - {title}" if title in taken else title,
                "created": True,
                "added": [],
            }
        else:
            record = None
            for name in (title, f"{prefix} - {title}"):
                created = _create(geolens, name)
                if created:
                    record = {
                        "id": created,
                        "name": name[:MAX_NAME],
                        "created": True,
                        "added": [],
                    }
                    break
            if record is None:
                raise GroupUsageError(
                    f"GeoLens already has groups named {title} and "
                    f"{prefix} - {title}; set group_map {arcgis_id} geolens_group "
                    "to the one to share with"
                )
            state.groups[arcgis_id] = record
            state.save()
        failed = _fill(
            geolens,
            record,
            inventory_groups.get(arcgis_id) or {},
            plan,
            directory,
            dry_run,
        )
        if failed:
            out.warnings.append(failed)
        if not dry_run:
            state.groups[arcgis_id] = record
            state.save()
        out.groups[arcgis_id] = record
    return out


def _dataset_groups(dataset: Any) -> set[str]:
    groups = getattr(dataset, "groups", None)
    return {str(g.id) for g in groups} if isinstance(groups, list) else set()


def share(
    ctx: MigrationContext,
    item: Mapping[str, Any],
    entry: ItemState,
    *,
    with_map: bool = True,
) -> None:
    """Share the item's datasets, and with *with_map* its map, with the GeoLens
    groups its target names that this command hasn't shared it with yet;
    each keeps the groups it already has."""
    from geolens.api.datasets_metadata import (
        set_dataset_groups_endpoint_datasets_dataset_id_groups_put as put_dataset,
    )
    from geolens.models.dataset_groups_update import DatasetGroupsUpdate

    from .arcgis_migrate_refresh import get_dataset, record

    new = set(item["target"].get("geolens_groups") or []) - set(entry.groups)
    if not new:
        return
    try:
        for dataset_id in entry.dataset_ids:
            current = _dataset_groups(get_dataset(ctx, dataset_id))
            if new <= current:
                continue
            ctx.geolens.call(
                put_dataset.sync_detailed,
                dataset_id=UUID(dataset_id),
                body=DatasetGroupsUpdate(
                    group_ids=[UUID(g) for g in sorted(current | new)]
                ),
            )
            if dataset_id in entry.last_update:
                record(entry, dataset_id, get_dataset(ctx, dataset_id))
        if with_map and entry.map_id:
            _share_map(ctx, entry.map_id, new)
    except GeoLensError as exc:
        raise ItemFailed(f"sharing it with its GeoLens groups failed, {exc}") from None
    entry.groups = sorted({*entry.groups, *new})
    ctx.save()


def _share_map(ctx: MigrationContext, map_id: str, new: set[str]) -> None:
    from geolens.api.maps import set_map_groups_endpoint_maps_map_id_groups_put as put
    from geolens.models.map_groups_update import MapGroupsUpdate

    from .arcgis_migrate_webmaps import get_map

    current = _dataset_groups(get_map(ctx.geolens, map_id))
    if new <= current:
        return
    # Each layer's dataset is shared as its own plan item says, so layers
    # a group can't read stay hidden from it rather than being widened.
    ctx.geolens.call(
        put.sync_detailed,
        map_id=UUID(map_id),
        body=MapGroupsUpdate(
            group_ids=[UUID(g) for g in sorted(current | new)], confirm="map_only"
        ),
    )
