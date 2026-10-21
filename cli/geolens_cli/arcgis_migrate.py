# SPDX-License-Identifier: Apache-2.0
"""Execute an ArcGIS migration plan: ``geolens arcgis migrate``.

Hand-maintained. Reads a plan written by ``geolens arcgis plan``, runs its
items one at a time in ``depends_on`` order, and records progress in a state
file so a rerun resumes where the last one stopped. Items are imported as
the operator, who must be a GeoLens admin, then handed to the owner the plan
maps them to through the admin ownership transfer on ``PATCH /datasets/{id}``
and ``PATCH /maps/{id}``. No credential is minted for the owners.

GeoLens is reached only through the SDK client for the configured instance;
see ``arcgis_portal`` for the portal side of the egress contract.
"""

from __future__ import annotations

import heapq
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer

from . import arcgis_plan as _plan
from . import output as _output
from ._sdk_helpers import (
    EXIT_GENERIC,
    EXIT_OK,
    EXIT_USAGE,
    call_sdk_with_reauth,
    detail_text,
)
from .arcgis_migrate_state import (
    DONE,
    FAILED,
    FINISHED,
    SKIPPED,
    STATE_FILENAME,
    ItemState,
    MigrationState,
    StateError,
)
from .arcgis_portal import Redactor

# The permission the server checks before it transfers what each action
# creates: datasets need upload, a map needs edit_metadata.
TRANSFER_PERMISSION = {
    _plan.IMPORT_LAYERS: "upload",
    _plan.IMPORT_FILE: "upload",
    _plan.IMPORT_MAP: "edit_metadata",
}
USER_PAGE_SIZE = 200
EXIT_INTERRUPTED = 130


class UsageError(Exception):
    """The plan, state or owner mapping can't be run; nothing was imported."""


class GeoLensError(Exception):
    """A GeoLens request answered with an error status."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class ItemFailed(Exception):
    """An item could not be migrated; the message goes to the state file."""


@dataclass
class ItemResult:
    """What an action handler created or found for one item."""

    status: str = DONE
    dataset_ids: list[str] = field(default_factory=list)
    record_ids: list[str] = field(default_factory=list)
    map_id: str | None = None
    job_ids: list[str] = field(default_factory=list)


class GeoLens:
    """The operator's SDK session; a 401 spends a stored refresh token once."""

    def __init__(self, sdk: Any, instance: str) -> None:
        self._sdk = sdk
        self._instance = instance
        self.client = sdk.client

    def call(
        self, fn: Callable[..., Any], *, expected: int = 200, **kwargs: Any
    ) -> Any:
        from geolens.models.problem_detail import ProblemDetail  # lazy

        def replace_client(replacement: Any) -> None:
            self.client = replacement

        resp = call_sdk_with_reauth(
            fn,
            instance=self._instance,
            credential_kind=self._sdk.credential_kind,
            credential_provenance=self._sdk.credential_provenance,
            on_reauthenticated=replace_client,
            client=self.client,
            **kwargs,
        )
        status = int(resp.status_code)
        if status != expected or isinstance(resp.parsed, ProblemDetail):
            detail = (
                detail_text(resp.parsed.detail)
                if isinstance(resp.parsed, ProblemDetail)
                else "no detail"
            )
            raise GeoLensError(f"HTTP {status}: {detail}", status)
        return resp.parsed


Handler = Callable[[GeoLens, Mapping[str, Any], ItemState], ItemResult]
# Action -> handler. An action without one is reported as not available in
# this version and left pending, so a later version can run it.
HANDLERS: dict[str, Handler] = {}


@dataclass(frozen=True)
class Owner:
    id: str
    username: str


@dataclass
class MigrateOptions:
    plan_path: Path
    state_path: Path | None
    only: list[str]
    dry_run: bool
    no_retry: bool
    unmapped_owner: str | None


def order_items(items: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """*items* with every item after the plan items it ``depends_on``.

    Ties keep plan order. A dependency missing from the plan doesn't hold an
    item back; a cycle is a ``UsageError``.
    """
    index = {item["id"]: n for n, item in enumerate(items)}
    waiting_on = {
        item["id"]: {d for d in item["depends_on"] if d in index and d != item["id"]}
        for item in items
    }
    dependents: dict[str, list[str]] = {}
    for item_id, deps in waiting_on.items():
        for dep in deps:
            dependents.setdefault(dep, []).append(item_id)
    ready = [index[i] for i, deps in waiting_on.items() if not deps]
    heapq.heapify(ready)
    ordered: list[Mapping[str, Any]] = []
    while ready:
        item = items[heapq.heappop(ready)]
        ordered.append(item)
        for dependent in dependents.get(item["id"], []):
            waiting_on[dependent].discard(item["id"])
            if not waiting_on[dependent]:
                heapq.heappush(ready, index[dependent])
    if len(ordered) < len(items):
        stuck = sorted(i for i, deps in waiting_on.items() if deps)
        raise UsageError(
            f"depends_on forms a cycle among these items: {', '.join(stuck[:10])}"
        )
    return ordered


def _wanted(
    by_id: Mapping[str, Mapping[str, Any]], only: list[str], state: MigrationState
) -> set[str]:
    """The --only items plus every unfinished plan item they depend on."""
    unknown = sorted(set(only) - set(by_id))
    if unknown:
        raise UsageError(f"--only names items not in the plan: {', '.join(unknown)}")
    wanted: set[str] = set()
    stack = list(only)
    while stack:
        item_id = stack.pop()
        if item_id in wanted:
            continue
        wanted.add(item_id)
        for dep in by_id[item_id]["depends_on"]:
            if dep in by_id and state.status(dep) not in FINISHED:
                stack.append(dep)
    return wanted


def _needs_run(item: Mapping[str, Any], status: str, no_retry: bool) -> bool:
    if status in FINISHED:
        return False
    if status == FAILED and no_retry:
        return False
    return not (status == SKIPPED and item["action"] == _plan.SKIP)


def select_items(
    plan: Mapping[str, Any], state: MigrationState, only: list[str], no_retry: bool
) -> list[Mapping[str, Any]]:
    """The plan items this run executes, in order."""
    ordered = order_items(plan["items"])
    by_id = {item["id"]: item for item in ordered}
    wanted = _wanted(by_id, only, state) if only else set(by_id)
    return [
        item
        for item in ordered
        if item["id"] in wanted and _needs_run(item, state.status(item["id"]), no_retry)
    ]


def _target_name(item: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    return item["target"]["owner"] or plan["owner_map"].get(item["owner"], "")


def _list_users(geolens: GeoLens) -> list[Any]:
    from geolens.api.admin import list_users_admin_users_get as list_users

    users: list[Any] = []
    while True:
        page = geolens.call(
            list_users.sync_detailed, skip=len(users), limit=USER_PAGE_SIZE
        )
        users.extend(page.users)
        if not page.users or len(users) >= page.total:
            return users


def _role_permissions(geolens: GeoLens) -> Mapping[str, Mapping[str, bool]] | None:
    """The instance's role permissions, or None when the setting can't be read."""
    from geolens.api.admin import get_all_settings_settings_all_get as get_settings

    try:
        settings = geolens.call(get_settings.sync_detailed)
    except GeoLensError:
        return None
    for items in settings.tabs.additional_properties.values():
        for setting in items:
            if setting.key == "role_permissions" and isinstance(setting.value, dict):
                return setting.value
    return None


class _Directory:
    """GeoLens users by lower-cased username and email."""

    def __init__(
        self, users: Iterable[Any], roles: Mapping[str, Mapping[str, bool]] | None
    ) -> None:
        self._by_name: dict[str, Any] = {}
        for user in users:
            for name in (user.username, user.email):
                if isinstance(name, str) and name:
                    self._by_name.setdefault(name.lower(), user)
        self.roles = roles

    def find(self, name: str) -> Any | None:
        return self._by_name.get(name.strip().lower())

    def unusable(self, user: Any, permission: str) -> str | None:
        """Why *user* can't own what needs *permission*, or None.

        Without the role permissions only the account status is checked; the
        server still vets the new owner on every transfer.
        """
        if not user.is_active or str(user.status) != "active":
            return f"{user.username} is not an active GeoLens user"
        if self.roles is None:
            return None
        if not any((self.roles.get(r) or {}).get(permission) for r in user.roles):
            roles = ", ".join(user.roles) or "none"
            return f"{user.username}'s roles ({roles}) don't grant {permission}"
        return None


@dataclass
class Owners:
    by_item: dict[str, Owner]
    reassigned: list[str]
    changed: list[dict[str, str]]
    roles_checked: bool


def resolve_owners(
    geolens: GeoLens,
    plan: Mapping[str, Any],
    to_run: list[Mapping[str, Any]],
    state: MigrationState,
    unmapped_owner: str | None,
) -> Owners:
    """The GeoLens owner of every importing item, or a ``UsageError``.

    An empty mapping or an owner who can't hold the item (inactive, or a role
    without the permission its transfer needs) falls back to *unmapped_owner*
    when it is given. A name that matches no GeoLens user is always refused,
    since it is most likely a typo.
    """
    directory = _Directory(_list_users(geolens), _role_permissions(geolens))
    fallback = directory.find(unmapped_owner) if unmapped_owner else None
    problems: set[str] = set()
    if unmapped_owner and fallback is None:
        problems.add(f"--unmapped-owner {unmapped_owner} is not a GeoLens user")

    by_item: dict[str, Owner] = {}
    reassigned: list[str] = []
    for item in to_run:
        permission = TRANSFER_PERMISSION.get(item["action"])
        if permission is None:
            continue
        name = _target_name(item, plan)
        user = directory.find(name) if name else None
        if name and user is None:
            problems.add(f"{name} (owner of {item['id']}) is not a GeoLens user")
            continue
        if user is None:
            reason = f"ArcGIS user {item['owner']} has no GeoLens owner in owner_map"
        else:
            reason = directory.unusable(user, permission)
        if reason is None:
            by_item[item["id"]] = Owner(str(user.id), user.username)
            continue
        if fallback is None:
            problems.add(reason)
            continue
        fallback_reason = directory.unusable(fallback, permission)
        if fallback_reason:
            problems.add(f"--unmapped-owner: {fallback_reason}")
        else:
            by_item[item["id"]] = Owner(str(fallback.id), fallback.username)
            reassigned.append(f"{item['id']}: {reason}")
    if problems:
        hint = "" if unmapped_owner else " Fix owner_map, or pass --unmapped-owner."
        raise UsageError(
            "can't assign owners: " + "; ".join(sorted(problems)) + "." + hint
        )
    changed = _changed_owners(directory, plan, to_run, state)
    return Owners(by_item, reassigned, changed, directory.roles is not None)


def _changed_owners(
    directory: _Directory,
    plan: Mapping[str, Any],
    to_run: list[Mapping[str, Any]],
    state: MigrationState,
) -> list[dict[str, str]]:
    """Migrated items whose plan now names a different owner."""
    running = {item["id"] for item in to_run}
    changed = []
    for item in plan["items"]:
        entry = state.items.get(item["id"])
        if item["id"] in running or entry is None or entry.status not in FINISHED:
            continue
        user = directory.find(_target_name(item, plan))
        if user is not None and entry.owner_id and str(user.id) != entry.owner_id:
            changed.append({"item": item["id"], "owner": user.username})
    return changed


def _require_admin(geolens: GeoLens) -> str:
    from geolens.api.auth import me_auth_me_get

    me = geolens.call(me_auth_me_get.sync_detailed)
    if "admin" not in (me.roles or []):
        raise UsageError(
            "migrate needs a GeoLens admin session: it reads the user list and "
            "transfers ownership. Run `geolens login` as an admin."
        )
    return str(me.id)


def transfer(geolens: GeoLens, entry: ItemState, owner: Owner) -> None:
    """Hand every dataset and the map recorded for an item to *owner*."""
    from uuid import UUID

    from geolens.api.datasets import (
        update_dataset_metadata_datasets_dataset_id_patch as patch_dataset,
    )
    from geolens.api.maps import patch_map_endpoint_maps_map_id_patch as patch_map
    from geolens.models.dataset_meta import DatasetMeta
    from geolens.models.map_patch import MapPatch

    owner_id = UUID(owner.id)
    for dataset_id in entry.dataset_ids:
        geolens.call(
            patch_dataset.sync_detailed,
            dataset_id=UUID(dataset_id),
            body=DatasetMeta(owner_id=owner_id),
        )
    if entry.map_id:
        geolens.call(
            patch_map.sync_detailed,
            map_id=UUID(entry.map_id),
            body=MapPatch(owner_id=owner_id),
        )


@dataclass
class RunSummary:
    unavailable: list[str] = field(default_factory=list)
    waiting: list[dict[str, Any]] = field(default_factory=list)


def _unmet(
    item: Mapping[str, Any], by_id: Mapping[str, Any], state: MigrationState
) -> list[str]:
    return [
        dep
        for dep in item["depends_on"]
        if dep in by_id and state.status(dep) not in (*FINISHED, SKIPPED)
    ]


def _migrate_one(
    geolens: GeoLens,
    state: MigrationState,
    item: Mapping[str, Any],
    handler: Handler,
    owner: Owner,
    operator_id: str,
) -> None:
    entry = state.start(item["id"])
    try:
        result = handler(geolens, item, entry)
        entry.dataset_ids = result.dataset_ids
        entry.record_ids = result.record_ids
        entry.map_id = result.map_id
        entry.job_ids = result.job_ids
        state.save()
        if owner.id != operator_id:
            transfer(geolens, entry, owner)
        entry.owner_id = owner.id
    except (ItemFailed, GeoLensError) as exc:
        state.finish(item["id"], FAILED, str(exc))
        return
    except KeyboardInterrupt:
        state.finish(item["id"], FAILED, "interrupted")
        raise
    except typer.Exit:
        state.finish(item["id"], FAILED, "stopped by a failed request")
        raise
    state.finish(item["id"], result.status)


def run_items(
    geolens: GeoLens,
    plan: Mapping[str, Any],
    state: MigrationState,
    to_run: list[Mapping[str, Any]],
    owners: Mapping[str, Owner],
    operator_id: str,
) -> RunSummary:
    by_id = {item["id"]: item for item in plan["items"]}
    summary = RunSummary()
    for item in to_run:
        if item["action"] == _plan.SKIP:
            state.finish(item["id"], SKIPPED, save=False)
            continue
        handler = HANDLERS.get(item["action"])
        if handler is None:
            summary.unavailable.append(item["id"])
            continue
        unmet = _unmet(item, by_id, state)
        if unmet:
            summary.waiting.append({"item": item["id"], "waiting_on": unmet})
            continue
        _migrate_one(geolens, state, item, handler, owners[item["id"]], operator_id)
    state.save()
    return summary


def _report(
    fmt: _output.Formatter,
    opts: MigrateOptions,
    state: MigrationState,
    to_run: list[Mapping[str, Any]],
    owners: Owners,
    summary: RunSummary,
) -> int:
    rows = [
        {
            "id": item["id"],
            "title": item["title"],
            "action": item["action"],
            "status": state.status(item["id"]),
            "owner": owners.by_item[item["id"]].username
            if item["id"] in owners.by_item
            else None,
        }
        for item in to_run
    ]
    counts = Counter(entry.status for entry in state.items.values())
    failed = [r["id"] for r in rows if r["status"] == FAILED]
    payload = {
        "plan": str(opts.plan_path),
        "state": None if opts.dry_run else str(state.path),
        "dry_run": opts.dry_run,
        "items": rows,
        "counts": dict(sorted(counts.items())),
        "owner_reassigned": owners.reassigned,
        "owner_changed": owners.changed,
        "owner_roles_checked": owners.roles_checked,
        "not_available": summary.unavailable,
        "waiting": summary.waiting,
    }
    if fmt.json_mode:
        fmt.json(payload)
    else:
        verb = "Would run" if opts.dry_run else "Ran"
        fmt.info(f"{verb} {len(rows)} item(s).")
        for row in rows:
            owner = f" as {row['owner']}" if row["owner"] else ""
            fmt.info(f"  {row['id']} {row['action']}{owner}: {row['status']}")
        for line in owners.reassigned:
            fmt.warn(f"owner fell back to --unmapped-owner for {line}")
        for change in owners.changed:
            fmt.warn(
                f"{change['item']} was migrated before its owner changed to "
                f"{change['owner']}; it was not imported again. Transfer it by hand."
            )
        if not owners.roles_checked:
            fmt.warn(
                "the instance's role permissions couldn't be read, so owners were "
                "checked for an active account only"
            )
        if summary.unavailable:
            fmt.warn(
                f"{len(summary.unavailable)} item(s) use an action this version "
                "can't run yet and were left pending."
            )
        for wait in summary.waiting:
            fmt.warn(f"{wait['item']} waits on {', '.join(wait['waiting_on'])}")
        if not opts.dry_run:
            fmt.info(f"State: {state.path}")
    left = summary.unavailable or summary.waiting
    return EXIT_GENERIC if failed or left else EXIT_OK


def run_cli(
    fmt: _output.Formatter,
    opts: MigrateOptions,
    *,
    sdk_factory: Callable[[], Any],
    instance: str,
) -> int:
    """Run ``geolens arcgis migrate`` and return its exit code."""
    redact = Redactor()
    try:
        return _run(fmt, opts, redact, sdk_factory, instance)
    except typer.Exit:
        raise
    except (
        Exception
    ) as exc:  # broad: last guard so a traceback can't print a credential
        fmt.error(redact(f"unexpected error: {type(exc).__name__}: {exc}"))
        return EXIT_GENERIC


def _run(
    fmt: _output.Formatter,
    opts: MigrateOptions,
    redact: Redactor,
    sdk_factory: Callable[[], Any],
    instance: str,
) -> int:
    try:
        plan = _plan.load_plan(opts.plan_path)
        state_path = opts.state_path or opts.plan_path.parent / STATE_FILENAME
        state = MigrationState.load(
            state_path, plan["portal"]["url"], redact, persist=not opts.dry_run
        )
        to_run = select_items(plan, state, opts.only, opts.no_retry)
    except (_plan.PlanError, StateError, UsageError) as exc:
        fmt.error(str(exc))
        return EXIT_USAGE

    sdk = sdk_factory()
    redact.add(getattr(sdk.client, "token", None))
    geolens = GeoLens(sdk, instance)
    try:
        operator_id = _require_admin(geolens)
        owners = resolve_owners(geolens, plan, to_run, state, opts.unmapped_owner)
    except UsageError as exc:
        fmt.error(str(exc))
        return EXIT_USAGE
    except GeoLensError as exc:
        fmt.error(f"can't read GeoLens users: {exc}")
        return EXIT_GENERIC

    if opts.dry_run:
        return _report(fmt, opts, state, to_run, owners, RunSummary())
    try:
        summary = run_items(geolens, plan, state, to_run, owners.by_item, operator_id)
    except KeyboardInterrupt:
        fmt.error(
            f"interrupted; rerun with the same state file ({state.path}) to resume"
        )
        return EXIT_INTERRUPTED
    return _report(fmt, opts, state, to_run, owners, summary)
