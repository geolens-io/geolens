# SPDX-License-Identifier: Apache-2.0
"""Turn an ArcGIS inventory into an editable migration plan.

Hand-maintained. The plan file's shape is pinned by
``manifest/schemas/arcgis-migration-plan-v1.schema.json``. Nothing here
contacts a portal or GeoLens: it reads one inventory JSON and writes one plan.
"""

from __future__ import annotations

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

SCHEMA_VERSION = "1"
PLAN_FILENAME = "arcgis-migration-plan.json"
_PLAN_SCHEMA_RESOURCE = "arcgis-migration-plan-v1.schema.json"
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


def _visibility(access: str) -> str:
    return _ACCESS_VISIBILITY.get(access, DEFAULTS["visibility"])


def _group_defaults(
    items: list[Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    groups: dict[str, dict[str, str]] = {}
    for row in items:
        for group in row["groups"] or []:
            groups.setdefault(
                group["id"],
                {
                    "collection": group["title"] or group["id"],
                    "visibility": _visibility(group["access"] or ""),
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
) -> dict[str, Any]:
    """The default plan for *inventory*; *owner_map* fills the owner mapping."""
    items = inventory["items"]
    by_id = {row["id"]: row for row in items}
    edges: dict[str, list[Mapping[str, Any]]] = {}
    for dep in inventory["dependencies"]:
        edges.setdefault(dep["from_id"], []).append(dep)

    group_map = _group_defaults(items)
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
                "visibility": _visibility(row["sharing"]["access"]),
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
        rows.append(entry)

    portal = inventory["portal"]
    return {
        "schema_version": SCHEMA_VERSION,
        "inventory": {
            "path": inventory_path,
            "generated_at": inventory["generated_at"],
            "complete": bool(inventory["complete"] and not inventory["truncated"]),
        },
        "portal": {"url": portal["url"]},
        "defaults": dict(DEFAULTS),
        "owner_map": mapping,
        "group_map": group_map,
        "basemap_map": {url: "" for url in basemaps},
        "items": rows,
    }


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
    """A plan file, validated against the plan schema; ``PlanError`` otherwise."""
    data = _load_json(path, "plan")
    schema_path = files("geolens_cli.manifest.schemas").joinpath(_PLAN_SCHEMA_RESOURCE)
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
    by_action = Counter(item["action"] for item in plan["items"])
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
        "items": len(plan["items"]),
        "by_action": {a: by_action.get(a, 0) for a in ACTIONS},
        "owners_to_map": sum(1 for v in plan["owner_map"].values() if not v),
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
        plan = build_plan(inventory, inventory_path=recorded, owner_map=owners)
    except PlanError as exc:
        fmt.error(str(exc))
        return EXIT_USAGE
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
    text = _render(plan)
    path = out_dir / PLAN_FILENAME
    try:
        if path.exists() and path.read_text(encoding="utf-8") != text and not force:
            fmt.error(
                f"{path} already exists and differs from this plan, so it may hold "
                "your edits. Pass --force to replace it, or choose another --output-dir."
            )
            return EXIT_GENERIC
        out_dir.mkdir(parents=True, exist_ok=True)
        _report.write_private(path, text)
    except (OSError, ValueError) as exc:
        fmt.error(f"can't write {path}: {getattr(exc, 'strerror', None) or exc}")
        return EXIT_GENERIC
    if fmt.json_mode:
        fmt.json({"plan": str(path), **stats})
        return EXIT_OK
    fmt.success(f"Wrote {path}")
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
