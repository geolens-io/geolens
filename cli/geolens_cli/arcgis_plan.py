# SPDX-License-Identifier: Apache-2.0
"""Turn an ArcGIS inventory into an editable migration plan.

Hand-maintained. The plan file's shape is pinned by
``manifest/schemas/arcgis-migration-plan-v2.schema.json``; v1 plans are still
read. Nothing here contacts a portal or GeoLens: it reads one inventory JSON,
and the plan already in the output directory, and writes one plan.
"""

from __future__ import annotations

import copy
import json
import os
from collections import Counter
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import best_match

from . import arcgis_report as _report
from . import output as _output
from ._sdk_helpers import EXIT_GENERIC, EXIT_OK, EXIT_USAGE
from .arcgis_portal import portal_root

SCHEMA_VERSION = "2"
PLAN_FILENAME = "arcgis-migration-plan.json"
CONFLICT_LINES = 10
_PLAN_SCHEMAS = {
    "1": "arcgis-migration-plan-v1.schema.json",
    "2": "arcgis-migration-plan-v2.schema.json",
}
_INVENTORY_VERSION = "2"

IMPORT_LAYERS = "import_layers"
IMPORT_FILE = "import_file"
IMPORT_MAP = "import_map"
EXPORT_ONLY = "export_only"
SKIP = "skip"
ACTIONS = (IMPORT_LAYERS, IMPORT_FILE, IMPORT_MAP, EXPORT_ONLY, SKIP)

DEFAULTS = {"visibility": "private", "collection_from": "folder"}
_ACCESS_VISIBILITY = {"private": "private", "org": "internal", "public": "public"}
# Roles whose target must exist before the item that names it.
_ORDERING_ROLES_EXCLUDED = frozenset({"published_from"})
# Item values an operator may edit, as paths into the item and its defaults.
_EDITABLE = (
    ("action",),
    ("depends_on",),
    ("superseded_by",),
    ("target", "owner"),
    ("target", "visibility"),
    ("target", "collections"),
    ("target", "groups"),
    ("target", "title"),
    ("target", "tags"),
)
# Item values that describe the portal item; a merge takes the inventory's.
_PORTAL_FACTS = ("type", "title", "owner", "reason")


class PlanError(Exception):
    """The inventory or owner map can't be turned into a plan."""


def _unread_dependencies(row: Mapping[str, Any]) -> bool:
    return row["dependencies_status"] in ("error", "unparsed", "not_fetched")


def _default_action(row: Mapping[str, Any]) -> str:
    if row["type"] == "Web Map":
        if _unread_dependencies(row):
            return EXPORT_ONLY
        return IMPORT_MAP
    if row["class"] == "supported":
        return IMPORT_LAYERS
    if row["reason"] == "data_file_import_candidate":
        return IMPORT_FILE
    return EXPORT_ONLY


def _visibility(access: str, fallback: str) -> str:
    return _ACCESS_VISIBILITY.get(access, fallback)


def _group_defaults(
    items: list[Mapping[str, Any]], fallback: str
) -> dict[str, dict[str, str]]:
    groups: dict[str, dict[str, str]] = {}
    for row in items:
        for group in row["groups"] or []:
            groups.setdefault(
                group["id"],
                {
                    "collection": group["title"] or group["id"],
                    "visibility": _visibility(group["access"] or "", fallback),
                },
            )
    return dict(sorted(groups.items()))


def _collections(row: Mapping[str, Any]) -> list[str]:
    folder = row["folder"]
    return [folder["title"] or folder["id"]] if folder else []


def _group_ids(row: Mapping[str, Any]) -> list[str] | None:
    if row["groups"] is None:
        return None
    return sorted({g["id"] for g in row["groups"] or []})


def build_plan(
    inventory: Mapping[str, Any],
    *,
    inventory_path: str,
    owner_map: Mapping[str, str] | None = None,
    defaults: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The default plan for *inventory*; *owner_map* fills the owner mapping
    and *defaults*, a plan's ``defaults``, replaces ``DEFAULTS``."""
    plan_defaults = dict(defaults or DEFAULTS)
    fallback = plan_defaults["visibility"]
    items = inventory["items"]
    by_id = {row["id"]: row for row in items}
    edges: dict[str, list[Mapping[str, Any]]] = {}
    for dep in inventory["dependencies"]:
        edges.setdefault(dep["from_id"], []).append(dep)

    group_map = _group_defaults(items, fallback)
    owners = sorted({row["owner"] for row in items if row["owner"]})
    mapping = {owner: (owner_map or {}).get(owner, "") for owner in owners}
    basemaps = sorted(
        {
            dep["to_url"]
            for dep in inventory["dependencies"]
            if dep["role"] == "basemap"
            and dep["to_url"]
            and by_id.get(dep["from_id"], {}).get("type") == "Web Map"
        }
    )

    superseded: dict[str, str] = {}
    for dep in inventory["dependencies"]:
        if dep["role"] == "published_from" and dep["to_id"] in by_id:
            superseded.setdefault(dep["to_id"], dep["from_id"])

    rows: list[dict[str, Any]] = []
    for row in items:
        action = _default_action(row)
        reason = row["reason"]
        depends_on: list[str] = []
        missing: list[str] = []
        for dep in edges.get(row["id"], []):
            target = dep["to_id"]
            if (
                not target
                or target == row["id"]
                or dep["external"] is True
                or dep["role"] in _ORDERING_ROLES_EXCLUDED
            ):
                continue
            if target not in depends_on:
                depends_on.append(target)
            if not dep["resolved"] and target not in missing:
                missing.append(target)
        if missing:
            reason += "; depends on items not in the inventory: " + ", ".join(missing)
        if _unread_dependencies(row):
            reason += (
                "; its dependencies could not be read, so depends_on may be incomplete"
            )
            if row["type"] == "Web Map":
                reason += (
                    "; rerun the inventory or set the action to import_map by hand"
                )
        entry: dict[str, Any] = {
            "id": row["id"],
            "type": row["type"],
            "title": row["title"],
            "owner": row["owner"],
            "action": action,
            "reason": reason,
            "target": {
                "owner": None,
                "visibility": _visibility(row["sharing"]["access"], fallback),
                "collections": _collections(row),
                "groups": _group_ids(row),
                "title": row["title"],
                "tags": list(row["tags"]),
            },
            "depends_on": depends_on,
        }
        layer = superseded.get(row["id"])
        if layer and action == IMPORT_FILE:
            entry["action"] = EXPORT_ONLY
            entry["superseded_by"] = layer
        entry["defaults"] = {
            "action": entry["action"],
            "target": copy.deepcopy(entry["target"]),
            "depends_on": list(depends_on),
            "superseded_by": entry.get("superseded_by"),
        }
        rows.append(entry)

    portal = inventory["portal"]
    return {
        "schema_version": SCHEMA_VERSION,
        "inventory": {
            "path": inventory_path,
            "generated_at": inventory["generated_at"],
            "complete": bool(inventory["complete"] and not inventory["truncated"]),
            "scope": dict(inventory["scope"]),
            "auth": dict(inventory["auth"]),
        },
        "portal": {"url": portal["url"]},
        "defaults": plan_defaults,
        "owner_map": mapping,
        "group_map": group_map,
        "basemap_map": {url: "" for url in basemaps},
        "items": rows,
    }


def _get(item: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = item
    for key in path:
        value = value.get(key)
    return value


def _put(item: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    *parents, last = path
    for key in parents:
        item = item[key]
    item[last] = copy.deepcopy(value)


def _unread_paths(row: Mapping[str, Any]) -> set[tuple[str, ...]]:
    """Defaults this inventory row can't give, because the portal wasn't read."""
    paths = set()
    folder = row["folder"]
    if folder is not None and folder["title"] is None:
        paths.add(("target", "collections"))
    if row["groups"] is None:
        paths.add(("target", "groups"))
    if _unread_dependencies(row):
        paths.add(("depends_on",))
        if row["type"] == "Web Map":
            paths.add(("action",))
    return paths


def _unread_supersession(
    current: Mapping[str, Any],
    fresh: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
) -> set[tuple[str, ...]]:
    """Defaults a source file can't take from this inventory: no layer claims
    it now, but the layer it was recorded as published into wasn't read or
    isn't listed, so the missing ``published_from`` edge proves nothing."""
    layer = (current.get("defaults") or {}).get("superseded_by")
    if not layer or fresh["defaults"]["superseded_by"] is not None:
        return set()
    row = rows.get(layer)
    if row is None or _unread_dependencies(row):
        return {("action",), ("superseded_by",)}
    return set()


def _merge_item(
    current: Mapping[str, Any],
    fresh: Mapping[str, Any],
    unread: set[tuple[str, ...]],
    conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    """*current* brought up to *fresh*'s defaults, keeping every edited value.

    A value counts as edited when it differs from the default recorded with
    it; an item without recorded defaults (from a v1 plan) counts as all
    edited and gets none.
    An edited value's recorded default doesn't move, so the value stays an
    edit when the portal's default later passes through it.
    """
    merged = copy.deepcopy(dict(current))
    merged.pop("removed", None)
    merged.pop("unlisted", None)
    for key in _PORTAL_FACTS:
        merged[key] = fresh[key]
    old = current.get("defaults")
    recorded = copy.deepcopy(fresh["defaults"])
    for path in _EDITABLE:
        value, new = _get(current, path), _get(fresh["defaults"], path)
        was = _get(old, path) if old is not None else None
        if old is not None and value == was and path not in unread:
            _put(merged, path, new)
            continue
        if old is not None:
            _put(recorded, path, was)
        if path in unread:
            continue
        if value != new and (old is None or new != was):
            conflicts.append(
                {
                    "item": current["id"],
                    "field": ".".join(path),
                    "plan": value,
                    "inventory": new,
                }
            )
    if merged.get("superseded_by") is None:
        merged.pop("superseded_by", None)
    # Without recorded defaults nothing shows which values were edited, so
    # they stay edits on every merge.
    if old is not None:
        merged["defaults"] = recorded
    return merged


def _same_portal(a: str, b: str) -> bool:
    try:
        return portal_root(a, True) == portal_root(b, True)
    except ValueError:
        return a.rstrip("/") == b.rstrip("/")


def other_organization(
    plan: Mapping[str, Any], inventory: Mapping[str, Any]
) -> str | None:
    """The org id of *inventory* when it names another ArcGIS organization
    than *plan* records; None when they match or either is unknown, since
    every ArcGIS Online organization shares one portal URL."""
    ours = (plan["inventory"].get("scope") or {}).get("org_id")
    theirs = inventory["scope"]["org_id"]
    return theirs if ours and theirs and ours != theirs else None


def _recorded_inventory(
    current: Mapping[str, Any], fresh: Mapping[str, Any]
) -> dict[str, Any]:
    """*fresh*'s ``inventory`` block, keeping the plan's org id when the new
    inventory has none, so ``other_organization`` can still catch another
    organization later."""
    block = copy.deepcopy(dict(fresh["inventory"]))
    ours = (current["inventory"].get("scope") or {}).get("org_id")
    if ours and not block["scope"]["org_id"]:
        block["scope"]["org_id"] = ours
    return block


def shows_removals(inventory: Mapping[str, Any]) -> bool:
    """Whether an inventory not listing an item shows the item is gone.

    Only a complete, org-scope inventory read signed in can. A user-scope
    inventory misses items moved to another owner, and an anonymous one
    misses everything not public. The inventory doesn't record whether the
    reader is an org admin, so a non-admin reader counts too.
    """
    return bool(
        inventory["complete"]
        and inventory["scope"]["mode"] == "org"
        and inventory["auth"]["mode"] != "anonymous"
    )


def merge_plan(
    current: Mapping[str, Any],
    fresh: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """*fresh*, the default plan of *inventory*, merged into the *current* plan.

    Edited values stay; a value still equal to its recorded default takes the
    new default. Items keep the plan's order, and items new to the portal are
    appended with defaults. An item missing from an inventory that
    ``shows_removals`` is kept and marked ``removed``, so the state file's
    record of what it migrated still has a plan item. Any other inventory
    removes nothing: an item it doesn't list is marked ``unlisted`` until a
    merge lists it again. Returns the plan and what the merge changed.
    """
    if not _same_portal(current["portal"]["url"], fresh["portal"]["url"]):
        raise PlanError(
            f"the plan is for {current['portal']['url']}, not {fresh['portal']['url']}"
        )
    other = other_organization(current, inventory)
    if other is not None:
        raise PlanError(
            f"the plan is for ArcGIS organization "
            f"{current['inventory']['scope']['org_id']}, not {other}"
        )
    rows = {row["id"]: row for row in inventory["items"]}
    listed = {item["id"]: item for item in fresh["items"]}
    complete = shows_removals(fresh["inventory"])
    changes: dict[str, list[Any]] = {
        "added": [],
        "removed": [],
        "restored": [],
        "unlisted": [],
        "conflicts": [],
        "owner_conflicts": [],
    }
    items: list[dict[str, Any]] = []
    for mine in current["items"]:
        item = listed.get(mine["id"])
        if item is not None:
            if mine.get("removed"):
                changes["restored"].append(mine["id"])
            items.append(
                _merge_item(
                    mine,
                    item,
                    _unread_paths(rows[item["id"]])
                    | _unread_supersession(mine, item, rows),
                    changes["conflicts"],
                )
            )
            continue
        kept = copy.deepcopy(dict(mine))
        if complete:
            kept.pop("unlisted", None)
            if not kept.get("removed"):
                kept["removed"] = True
                changes["removed"].append(mine["id"])
        elif not kept.get("removed"):
            kept["unlisted"] = True
            changes["unlisted"].append(mine["id"])
        items.append(kept)
    known = {item["id"] for item in current["items"]}
    for item in fresh["items"]:
        if item["id"] not in known:
            changes["added"].append(item["id"])
            items.append(item)

    owner_map = dict(fresh["owner_map"])
    for owner, name in current["owner_map"].items():
        given = owner_map.get(owner, "")
        if name and given and given != name:
            changes["owner_conflicts"].append(
                {"owner": owner, "plan": name, "owner_map": given}
            )
        if name or owner not in owner_map:
            owner_map[owner] = name
    return {
        "schema_version": SCHEMA_VERSION,
        "inventory": _recorded_inventory(current, fresh),
        "portal": dict(fresh["portal"]),
        "defaults": dict(current["defaults"]),
        "owner_map": dict(sorted(owner_map.items())),
        "group_map": dict(
            sorted({**fresh["group_map"], **current["group_map"]}.items())
        ),
        "basemap_map": dict(
            sorted({**fresh["basemap_map"], **current["basemap_map"]}.items())
        ),
        "items": items,
    }, changes


def _load_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PlanError(f"can't read the {what} {path}: {exc.strerror}") from None
    except ValueError:
        raise PlanError(f"the {what} {path} is not valid JSON") from None


def _schema_error(data: Any, schema: Mapping[str, Any]) -> str | None:
    """``"<where>: <message>"`` for the most relevant schema error, or None."""
    error = best_match(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data)
    )
    if error is None:
        return None
    where = "/".join(str(p) for p in error.absolute_path) or "(root)"
    return f"{where}: {error.message}"


def load_inventory(path: Path) -> dict[str, Any]:
    data = _load_json(path, "inventory")
    version = data.get("schema_version") if isinstance(data, dict) else None
    if version != _INVENTORY_VERSION:
        raise PlanError(
            f"{path} is not an inventory v{_INVENTORY_VERSION} report "
            f"(schema_version {version!r}). Rerun `geolens arcgis inventory -o <dir>` "
            "with this version of the CLI and pass the new arcgis-inventory.json."
        )
    error = _schema_error(data, _report.inventory_schema())
    if error is not None:
        raise PlanError(
            f"{path} is malformed at {error}; rerun `geolens arcgis inventory`"
        )
    return data


def load_plan(path: Path) -> dict[str, Any]:
    """A v1 or v2 plan file, validated against its schema; ``PlanError``
    otherwise."""
    data = _load_json(path, "plan")
    version = data.get("schema_version") if isinstance(data, dict) else None
    resource = _PLAN_SCHEMAS.get(
        version if isinstance(version, str) else SCHEMA_VERSION,
        _PLAN_SCHEMAS[SCHEMA_VERSION],
    )
    schema_path = files("geolens_cli.manifest.schemas").joinpath(resource)
    error = _schema_error(data, json.loads(schema_path.read_text(encoding="utf-8")))
    if error is not None:
        raise PlanError(f"{path} is not a valid migration plan at {error}")
    counts = Counter(item["id"] for item in data["items"])
    repeated = sorted(i for i, n in counts.items() if n > 1)
    if repeated:
        raise PlanError(
            f"{path} lists these item ids more than once: {', '.join(repeated)}"
        )
    return data


def load_owner_map(path: Path) -> dict[str, str]:
    data = _load_json(path, "owner map")
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise PlanError(
            f"{path} must be a JSON object of ArcGIS usernames to GeoLens usernames or emails"
        )
    return data


def summary(plan: Mapping[str, Any], inventory: Mapping[str, Any]) -> dict[str, Any]:
    present = [item for item in plan["items"] if not item.get("removed")]
    by_action = Counter(item["action"] for item in present)
    mapped_owners = {i["owner"] for i in present if i["target"]["owner"] is None}
    ids = {item["id"] for item in plan["items"]}
    unresolved = sorted(
        {
            (item["id"], target)
            for item in plan["items"]
            for target in item["depends_on"]
            if target not in ids
        }
    )
    external = sum(1 for d in inventory["dependencies"] if d["external"] is True)
    return {
        "items": len(present),
        "removed": len(plan["items"]) - len(present),
        "by_action": {a: by_action.get(a, 0) for a in ACTIONS},
        "owners_to_map": sum(
            1 for k, v in plan["owner_map"].items() if not v and k in mapped_owners
        ),
        "groups": len(plan["group_map"]),
        "basemaps": len(plan["basemap_map"]),
        "unresolved_dependencies": [
            {"item": item, "missing": target} for item, target in unresolved
        ],
        "external_dependencies": external,
        "group_sharing_unknown": sorted(
            row["id"] for row in inventory["items"] if row["groups"] is None
        ),
        "dependency_read_errors": sorted(
            row["id"] for row in inventory["items"] if _unread_dependencies(row)
        ),
        "inventory_complete": plan["inventory"]["complete"],
    }


def _render(plan: Mapping[str, Any]) -> str:
    return json.dumps(plan, indent=2) + "\n"


def _report_merge(
    fmt: _output.Formatter, path: Path, changes: Mapping[str, list[Any]]
) -> None:
    fmt.success(
        f"Merged the inventory into {path}: {len(changes['added'])} new item(s), "
        f"{len(changes['removed'])} gone from the portal, "
        f"{len(changes['restored'])} back on the portal"
    )
    if changes["removed"]:
        fmt.warn(
            "marked removed, never run again; what they migrated stays in GeoLens: "
            + ", ".join(changes["removed"][:5])
        )
    if changes["unlisted"]:
        fmt.warn(
            f"{len(changes['unlisted'])} plan item(s) are missing from this inventory "
            "and were marked unlisted, not removed, since only a complete --scope "
            "org inventory read signed in marks items removed: "
            + ", ".join(changes["unlisted"][:5])
        )
    conflicts = changes["conflicts"]
    for c in conflicts[:CONFLICT_LINES]:
        fmt.warn(
            f"{c['item']} {c['field']}: kept the plan's {json.dumps(c['plan'])}; "
            f"the inventory now gives {json.dumps(c['inventory'])}"
        )
    if len(conflicts) > CONFLICT_LINES:
        fmt.warn(
            f"{len(conflicts) - CONFLICT_LINES} more value(s) kept against the "
            "inventory; --json lists them all under merge.conflicts"
        )
    for c in changes["owner_conflicts"]:
        fmt.warn(
            f"owner_map {c['owner']}: kept the plan's {c['plan']}, "
            f"not {c['owner_map']} from --owner-map"
        )


def run_cli(
    fmt: _output.Formatter,
    *,
    inventory_path: Path,
    output_dir: Path | None,
    owner_map_path: Path | None,
    force: bool,
) -> int:
    try:
        inventory = load_inventory(inventory_path)
        owners = load_owner_map(owner_map_path) if owner_map_path else None
        out_dir = output_dir or inventory_path.resolve().parent
        try:
            recorded = os.path.relpath(inventory_path.resolve(), out_dir.resolve())
        except ValueError:  # a different drive has no relative path
            recorded = str(inventory_path.resolve())
    except PlanError as exc:
        fmt.error(str(exc))
        return EXIT_USAGE
    path = out_dir / PLAN_FILENAME
    changes = None
    if force or not path.exists():
        plan = build_plan(inventory, inventory_path=recorded, owner_map=owners)
    else:
        try:
            current = load_plan(path)
            fresh = build_plan(
                inventory,
                inventory_path=recorded,
                owner_map=owners,
                defaults=current["defaults"],
            )
            plan, changes = merge_plan(current, fresh, inventory)
        except PlanError as exc:
            fmt.error(
                f"can't merge this inventory into the existing plan: {exc}. Pass "
                "--force to replace it, or choose another --output-dir."
            )
            return EXIT_GENERIC
    if owners:
        unknown = sorted(set(owners) - set(plan["owner_map"]))
        if unknown:
            fmt.warn(
                f"{len(unknown)} owner(s) in --owner-map own no inventory item "
                f"and were ignored: {', '.join(unknown[:5])}"
            )
    stats = summary(plan, inventory)
    unread = stats["dependency_read_errors"]
    if unread:
        fmt.warn(
            f"{len(unread)} item(s) have dependencies the inventory could not read, "
            f"so depends_on may be incomplete: {', '.join(unread[:5])}"
        )
    unknown_groups = stats["group_sharing_unknown"]
    if unknown_groups:
        fmt.warn(
            f"{len(unknown_groups)} item(s) have no group sharing in the inventory, "
            "so their group collections are missing; rerun the inventory signed in "
            f"and without --no-groups: {', '.join(unknown_groups[:5])}"
        )
    if not plan["inventory"]["complete"]:
        fmt.warn(
            "the inventory is partial or truncated, so the plan misses items; "
            "rerun the inventory before migrating"
        )
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        _report.write_private(path, _render(plan))
    except (OSError, ValueError) as exc:
        fmt.error(f"can't write {path}: {getattr(exc, 'strerror', None) or exc}")
        return EXIT_GENERIC
    if fmt.json_mode:
        fmt.json({"plan": str(path), **stats, "merge": changes})
        return EXIT_OK
    if changes is None:
        fmt.success(f"Wrote {path}")
    else:
        _report_merge(fmt, path, changes)
    actions = ", ".join(f"{a}: {n}" for a, n in stats["by_action"].items())
    fmt.info(f"{stats['items']} item(s): {actions}")
    fmt.info(
        f"Fill in owner_map for {stats['owners_to_map']} owner(s); "
        f"{stats['groups']} group(s), {stats['basemaps']} basemap(s) listed."
    )
    if stats["external_dependencies"]:
        fmt.info(
            f"{stats['external_dependencies']} dependency(ies) point at other "
            "organizations' content and are never imported."
        )
    for entry in stats["unresolved_dependencies"]:
        fmt.warn(f"{entry['item']} depends on {entry['missing']}, not in the inventory")
    return EXIT_OK
