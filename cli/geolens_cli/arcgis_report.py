# SPDX-License-Identifier: Apache-2.0
"""JSON and Markdown renderings of an ArcGIS inventory.

Hand-maintained. The JSON shape is pinned by
``manifest/schemas/arcgis-inventory-v1.schema.json``.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from .arcgis_inventory import Inventory

SCHEMA_VERSION = "1"
JSON_FILENAME = "arcgis-inventory.json"
MARKDOWN_FILENAME = "arcgis-inventory.md"
_SCHEMA_RESOURCE = "arcgis-inventory-v1.schema.json"

_CLASS_HEADINGS = {
    "supported": "Supported",
    "partial": "Partial",
    "unsupported": "Unsupported",
}
_MD_SPECIAL = "\\`*_[]#|!~"


def inventory_schema() -> dict[str, Any]:
    """Return the packaged inventory report JSON Schema."""
    path = files("geolens_cli.manifest.schemas").joinpath(_SCHEMA_RESOURCE)
    return json.loads(path.read_text(encoding="utf-8"))


def build_report(
    inv: Inventory,
    *,
    tool_version: str,
    generated_at: str,
    max_items: int,
    retirements: Mapping[str, Mapping[str, str | None]],
    classes: Iterable[str],
) -> dict[str, Any]:
    by_class = {name: 0 for name in classes}
    by_type: Counter[str] = Counter()
    by_retirement: Counter[str] = Counter()
    for row in inv.items:
        by_class[row["class"]] += 1
        by_type[row["type"] or "(none)"] += 1
        if row["retirement"]:
            by_retirement[row["retirement"]["id"]] += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "tool_version": tool_version,
        "complete": inv.abort is None,
        "abort_reason": str(inv.abort) if inv.abort is not None else None,
        "truncated": inv.truncated,
        "max_items": max_items,
        "portal": inv.portal,
        "auth": inv.auth,
        "scope": inv.scope,
        "counts": {
            "total": len(inv.items),
            "by_class": by_class,
            "by_type": dict(sorted(by_type.items())),
            "retired": sum(by_retirement.values()),
            "failed": len(inv.errors),
        },
        "retirements": [
            {
                "id": retirement_id,
                "label": retirements[retirement_id]["label"],
                "status": retirements[retirement_id]["status"],
                "date": retirements[retirement_id]["date"],
                "note": retirements[retirement_id]["note"],
                "source_url": retirements[retirement_id]["source_url"],
                "item_count": count,
            }
            for retirement_id, count in sorted(by_retirement.items())
        ],
        "items": inv.items,
        "dependencies": inv.dependencies,
        "errors": inv.errors,
    }


def md_escape(text: Any) -> str:
    """One line of Markdown-inert text, safe inside a table cell."""
    value = " ".join(str(text if text is not None else "").split())
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "".join(f"\\{ch}" if ch in _MD_SPECIAL else ch for ch in value)


def _size(value: int | None) -> str:
    if value is None:
        return "n/a"
    if value < 1024:
        return f"{value} B"
    size = value / 1024
    for unit in ("KB", "MB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _item_link(report: Mapping[str, Any], item_id: str) -> str:
    target = f"{report['portal']['url']}/home/item.html?id={quote(item_id, safe='')}"
    return f"[{md_escape(item_id)}]({target})"


def _table(header: list[str], rows: Iterable[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def render_markdown(report: Mapping[str, Any]) -> str:
    portal = report["portal"]
    counts = report["counts"]
    kind = "ArcGIS Enterprise" if portal["kind"] == "enterprise" else "ArcGIS Online"
    lines = [f"# ArcGIS inventory: {md_escape(portal['name'] or portal['url'])}", ""]
    version = f", version {md_escape(portal['version'])}" if portal["version"] else ""
    lines.append(f"Portal: {md_escape(portal['url'])} ({kind}{version})  ")
    scope = report["scope"]
    scope_text = (
        f"items owned by {md_escape(scope['owner'])}"
        if scope["mode"] == "user"
        else "the whole organization"
    )
    lines.append(
        f"Scope: {scope_text}. Sign-in: {md_escape(report['auth']['mode'])}.  "
    )
    lines.append(
        f"Generated {md_escape(report['generated_at'])} by geolens-cli "
        f"{md_escape(report['tool_version'])}. Read-only: nothing was changed."
    )
    lines.append("")

    if not report["complete"]:
        lines += [
            f"> **Partial report.** The run stopped early: {md_escape(report['abort_reason'])}",
            "",
        ]
    if report["truncated"]:
        lines += [
            f"> **Item cap reached.** Only the first {report['max_items']} items "
            "were listed; rerun with a higher `--max-items`.",
            "",
        ]

    if report["retirements"]:
        lines += ["## Retirement deadlines", ""]
        for retirement in report["retirements"]:
            when = (
                f" ({md_escape(retirement['status'])}, {md_escape(retirement['date'])})"
                if retirement["date"]
                else f" ({md_escape(retirement['status'])})"
            )
            lines.append(
                f"> **{md_escape(retirement['label'])}**{when}: "
                f"{retirement['item_count']} item(s). {md_escape(retirement['note'])} "
                f"[Esri]({retirement['source_url']})"
            )
            lines.append(">")
        lines[-1] = ""

    lines += ["## Summary", ""]
    lines += _table(
        ["Class", "Items"],
        [
            [_CLASS_HEADINGS.get(name, name), str(count)]
            for name, count in counts["by_class"].items()
        ]
        + [["**Total**", str(counts["total"])]],
    )
    lines += ["", f"Items that could not be read: {counts['failed']}.", ""]

    for name, heading in _CLASS_HEADINGS.items():
        rows = [row for row in report["items"] if row["class"] == name]
        if not rows:
            continue
        lines += [f"## {heading}", ""]
        lines += _table(
            ["Item", "Title", "Type", "Owner", "Sharing", "Size", "Reason"],
            [
                [
                    _item_link(report, row["id"]),
                    md_escape(row["title"]),
                    md_escape(row["type"]),
                    md_escape(row["owner"]),
                    md_escape(row["sharing"]["access"]),
                    _size(row["size_bytes"]),
                    md_escape(row["reason"]),
                ]
                for row in rows
            ],
        )
        lines.append("")

    if report["dependencies"]:
        lines += ["## Dependencies", ""]
        lines += _table(
            ["From", "To", "Role", "Layer type", "Hosted", "In inventory"],
            [
                [
                    _item_link(report, dep["from_id"]),
                    md_escape(dep["to_id"] or dep["to_url"] or "n/a"),
                    md_escape(dep["role"]),
                    md_escape(dep["layer_type"] or ""),
                    {True: "yes", False: "no", None: "unknown"}[dep["hosted"]],
                    "yes" if dep["resolved"] else "no",
                ]
                for dep in report["dependencies"]
            ],
        )
        lines.append("")

    if report["errors"]:
        lines += ["## Errors", ""]
        lines += _table(
            ["Item", "Phase", "Status", "Message"],
            [
                [
                    md_escape(err["item_id"]),
                    md_escape(err["phase"]),
                    md_escape(
                        err["http_status"] if err["http_status"] is not None else ""
                    ),
                    md_escape(err["message"]),
                ]
                for err in report["errors"]
            ],
        )
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _write_private(path: Path, text: str) -> None:
    """Atomic write at mode 0600: the report lists private items."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_report_files(
    output_dir: Path, report: Mapping[str, Any], markdown: str
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / JSON_FILENAME
    md_path = output_dir / MARKDOWN_FILENAME
    _write_private(json_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write_private(md_path, markdown)
    return json_path, md_path
