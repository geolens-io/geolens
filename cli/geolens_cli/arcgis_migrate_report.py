# SPDX-License-Identifier: Apache-2.0
"""The run report of `geolens arcgis migrate`.

Hand-maintained. After a run, ``arcgis-migration-report.md`` and ``.json``
next to the state file cover every item of the plan, not only the ones this
run touched: counts by status, a row per item with its GeoLens ids and the
reason it ended as it did, what each unsupported type was saved as, and a
list of manual follow-ups. Both files are written at mode 0600 and pass
through the run's redactor, so a token that reached an error message is not
in them.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import arcgis_report as _report
from .arcgis_migrate_export import replacement_note
from .arcgis_migrate_state import FAILED, PENDING, MigrationState
from .arcgis_portal import Redactor, redact_json

REPORT_JSON = "arcgis-migration-report.json"
REPORT_MD = "arcgis-migration-report.md"
_SKIPPED_LAYER = ("layer, not imported", "layer not imported")


def _follow_ups(
    plan: Mapping[str, Any],
    state: MigrationState,
    unavailable: Iterable[str],
    waiting: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """What the operator still has to do, one entry per item and reason."""
    items = {item["id"]: item for item in plan["items"]}
    out: list[dict[str, str]] = []

    def add(item_id: str, kind: str, text: str) -> None:
        out.append({"item": item_id, "kind": kind, "text": text})

    for item in plan["items"]:
        entry = state.items.get(item["id"])
        status = state.status(item["id"])
        notes = list(entry.notes) if entry else []
        if status == FAILED and entry is not None:
            kind = "quota" if "refused the upload" in (entry.error or "") else "failed"
            add(item["id"], kind, entry.error or "failed")
        for note in notes:
            if any(marker in note for marker in _SKIPPED_LAYER):
                add(item["id"], "skipped_layer", note)
            elif note.startswith("skipped"):
                add(item["id"], "skipped", note)
        if item["target"].get("groups") and status != PENDING:
            add(
                item["id"],
                "group_sharing",
                "shared with ArcGIS groups "
                + ", ".join(item["target"]["groups"])
                + "; GeoLens groups are not migrated yet, so set its audience by hand",
            )
        layer = item.get("superseded_by")
        if layer:
            layer_entry = state.items.get(layer)
            ids = ", ".join(layer_entry.dataset_ids) if layer_entry else "not migrated"
            add(
                item["id"],
                "superseded",
                f"a data file saved as a hosted layer; GeoLens dataset: {ids}",
            )
        if entry is not None and entry.export:
            if entry.export["partial"]:
                add(
                    item["id"],
                    "export_partial",
                    "over the export size cap; see the folder",
                )
            for error in entry.export["errors"]:
                add(item["id"], "export_error", error)
    for item_id in unavailable:
        add(
            item_id,
            "not_available",
            f"the {items[item_id]['action']} action can't run yet",
        )
    for wait in waiting:
        add(
            wait["item"],
            "unresolved_dependency",
            "waits on " + ", ".join(wait["waiting_on"]),
        )
    for item in plan["items"]:
        for dep in item["depends_on"]:
            if dep not in items:
                add(
                    item["id"],
                    "unresolved_dependency",
                    f"depends on {dep}, not in the plan",
                )
    return out


def _export_section(
    plan: Mapping[str, Any], state: MigrationState
) -> list[dict[str, Any]]:
    rows = []
    for item in plan["items"]:
        entry = state.items.get(item["id"])
        if entry is not None and entry.export:
            rows.append(
                {
                    "item": item["id"],
                    "type": item["type"],
                    "title": item["title"],
                    "path": entry.export["path"],
                    "bytes": entry.export["bytes"],
                    "partial": entry.export["partial"],
                    "errors": entry.export["errors"],
                    "replacement": replacement_note(item["type"]),
                }
            )
    return rows


def build_run_report(
    plan: Mapping[str, Any],
    state: MigrationState,
    *,
    unavailable: Iterable[str] = (),
    waiting: Iterable[Mapping[str, Any]] = (),
    stopped: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """The report of the whole plan as of *state*."""
    unavailable = list(unavailable)
    waiting = list(waiting)
    rows = []
    for item in plan["items"]:
        entry = state.items.get(item["id"])
        rows.append(
            {
                "id": item["id"],
                "title": item["title"],
                "type": item["type"],
                "action": item["action"],
                "status": state.status(item["id"]),
                "dataset_ids": list(entry.dataset_ids) if entry else [],
                "map_id": entry.map_id if entry else None,
                "owner_id": entry.owner_id if entry else None,
                "reason": (entry.error or None) if entry else None,
                "notes": list(entry.notes) if entry else [],
                "loss_report": entry.loss_report_path if entry else None,
            }
        )
    counts = Counter(row["status"] for row in rows)
    return {
        "generated_at": generated_at
        or datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "portal": plan["portal"]["url"],
        "counts": dict(sorted(counts.items())),
        "stopped": stopped,
        "items": rows,
        "unsupported": _export_section(plan, state),
        "follow_ups": _follow_ups(plan, state, unavailable, waiting),
        "loss_reports": sorted(
            {row["loss_report"] for row in rows if row["loss_report"]}
        ),
    }


def render_run_markdown(report: Mapping[str, Any]) -> str:
    esc = _report.md_escape
    lines = [
        "# ArcGIS migration report",
        "",
        f"Portal: {esc(report['portal'])}  ",
        f"Generated: {esc(report['generated_at'])}",
        "",
    ]
    if report["stopped"]:
        lines += [f"**The run stopped:** {esc(report['stopped'])}", ""]
    lines += ["## Counts", ""]
    lines += _report.md_table(
        ["Status", "Items"], ([esc(s), str(n)] for s, n in report["counts"].items())
    )
    lines += ["", "## Manual follow-ups", ""]
    if report["follow_ups"]:
        for follow in report["follow_ups"]:
            lines.append(
                f"- `{follow['kind']}` {esc(follow['item'])}: {esc(follow['text'])}"
            )
    else:
        lines.append("None.")
    lines += ["", "## Items", ""]
    lines += _report.md_table(
        ["Item", "Title", "Type", "Action", "Status", "GeoLens", "Reason"],
        (
            [
                esc(r["id"]),
                esc(r["title"]),
                esc(r["type"]),
                esc(r["action"]),
                esc(r["status"]),
                esc(", ".join(r["dataset_ids"]) or r["map_id"] or ""),
                esc(r["reason"] or "; ".join(r["notes"])),
            ]
            for r in report["items"]
        ),
    )
    if report["unsupported"]:
        lines += ["", "## Items GeoLens can't host", ""]
        by_type: dict[str, list[Mapping[str, Any]]] = {}
        for row in report["unsupported"]:
            by_type.setdefault(row["type"], []).append(row)
        for item_type, rows in sorted(by_type.items()):
            lines += [f"### {esc(item_type)}", "", esc(rows[0]["replacement"]), ""]
            for row in rows:
                flag = " (partial)" if row["partial"] else ""
                lines.append(f"- {esc(row['title'])}: `{row['path']}`{flag}")
            lines.append("")
    if report["loss_reports"]:
        lines += ["## Loss reports", ""]
        lines += [f"- `{path}`" for path in report["loss_reports"]]
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def write_run_report(
    directory: Path, report: Mapping[str, Any], redact: Redactor
) -> tuple[Path, Path]:
    """Write both report files into *directory* and return their paths."""
    directory.mkdir(parents=True, exist_ok=True)
    safe = redact_json(report, redact)
    json_path, md_path = directory / REPORT_JSON, directory / REPORT_MD
    _report.write_private(json_path, json.dumps(safe, indent=2, sort_keys=True) + "\n")
    _report.write_private(md_path, redact(render_run_markdown(safe)))
    return json_path, md_path
