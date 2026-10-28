"""The run report of `geolens arcgis migrate`."""

from __future__ import annotations

import json
import secrets
import stat
from pathlib import Path

import pytest
import typer

from geolens_cli import arcgis_migrate as migrate
from geolens_cli import arcgis_migrate_report as report_mod
from geolens_cli.arcgis_migrate_state import ItemState, MigrationState
from geolens_cli.arcgis_portal import Redactor
from geolens_cli.main import app

from . import test_arcgis_migrate_layers as layers
from .arcgis_fake import A1, A2, A3, B1, C1, C3, D3
from .test_arcgis_migrate_layers import _write_plan, dataset_id

geolens = layers.geolens
quick = layers.quick


def _plan(tmp_path: Path) -> dict:
    return json.loads(_write_plan(tmp_path).read_text())


def _state(tmp_path: Path, redact: Redactor | None = None) -> MigrationState:
    return MigrationState(
        tmp_path / "arcgis-migration-state.json",
        "https://examplecounty.maps.arcgis.com",
        "https://geolens.example.org/api",
        redact or Redactor(),
        persist=False,
    )


def _set(state: MigrationState, item: str, status: str, **fields) -> ItemState:
    entry = state.item(item)
    entry.status = status
    for name, value in fields.items():
        setattr(entry, name, value)
    return entry


def test_every_status_and_plan_item_appears_in_both_files(tmp_path):
    plan = _plan(tmp_path)
    state = _state(tmp_path)
    _set(state, A1, "done", dataset_ids=[dataset_id("Parcels")])
    _set(state, A2, "exists", dataset_ids=[dataset_id("Owners")])
    _set(state, A3, "failed", error="probe failed, HTTP 500")
    _set(state, D3, "skipped", notes=["skipped: the file is over the limit"])
    _set(state, B1, "running")

    report = report_mod.build_run_report(
        plan, state, generated_at="2026-10-01T00:00:00Z"
    )
    json_path, md_path = report_mod.write_run_report(tmp_path, report, Redactor())

    assert {"done", "exists", "failed", "skipped", "running", "pending"} <= set(
        report["counts"]
    )
    assert [row["id"] for row in report["items"]] == [i["id"] for i in plan["items"]]
    text = md_path.read_text()
    assert "probe failed, HTTP 500" in text and dataset_id("Parcels") in text
    assert json.loads(json_path.read_text())["counts"] == report["counts"]
    for path in (json_path, md_path):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_credential_in_an_error_is_redacted_in_both_files(tmp_path):
    token = secrets.token_urlsafe(16)
    redact = Redactor()
    redact.add(token)
    plan = _plan(tmp_path)
    state = _state(tmp_path, redact)
    # Written past the state's own cleaning, as a regression would.
    _set(state, A1, "failed", error=f"bad request for token {token}")
    _set(state, A2, "done", notes=[f"see https://x.example/?token={token}"])

    report = report_mod.build_run_report(plan, state)
    json_path, md_path = report_mod.write_run_report(tmp_path, report, redact)

    for path in (json_path, md_path):
        assert token not in path.read_text()
    assert "[REDACTED]" in md_path.read_text()


def test_follow_ups_name_what_the_operator_still_has_to_do(tmp_path):
    plan = _plan(tmp_path)
    for item in plan["items"]:
        if item["id"] == A2:
            item["target"]["visibility"] = "restricted"
            item["target"]["groups"] = ["g1"]
        if item["id"] == D3:
            item["superseded_by"] = A1
    state = _state(tmp_path)
    _set(state, A1, "done", dataset_ids=["ds-1"])
    _set(
        state,
        A2,
        "done",
        dataset_ids=["ds-2"],
        notes=["Roads: Raster layer, not imported"],
    )
    _set(
        state,
        A3,
        "failed",
        error="Inspections: GeoLens refused the upload, Storage quota exceeded",
    )
    _set(
        state,
        C3,
        "done",
        export={
            "path": "export/dashboard/x",
            "bytes": 1,
            "partial": True,
            "errors": ["data: boom"],
        },
    )

    report = report_mod.build_run_report(plan, state, runnable={"import_layers"})

    kinds = {(f["item"], f["kind"]) for f in report["follow_ups"]}
    assert (A2, "under_shared") in kinds
    assert (A2, "skipped_layer") in kinds
    assert (D3, "superseded") in kinds
    assert (A3, "quota") in kinds
    assert (C3, "export_partial") in kinds and (C3, "export_error") in kinds
    assert (B1, "not_available") in kinds and (C1, "unresolved_dependency") in kinds
    superseded = next(f for f in report["follow_ups"] if f["kind"] == "superseded")
    assert "ds-1" in superseded["text"]


def test_unsupported_items_are_grouped_by_type_with_one_replacement_note(tmp_path):
    plan = _plan(tmp_path)
    state = _state(tmp_path)
    export = {"path": "export/dashboard/x", "bytes": 5, "partial": False, "errors": []}
    _set(state, C3, "done", export=export)

    text = report_mod.render_run_markdown(report_mod.build_run_report(plan, state))

    assert text.count("Maps carry over") == 1
    assert "### Dashboard" in text and "`export/dashboard/x`" in text


def _superseded_report(tmp_path, *, layer_migrated: bool):
    plan = _plan(tmp_path)
    layer_title = next(i["title"] for i in plan["items"] if i["id"] == A1)
    for item in plan["items"]:
        if item["id"] == D3:
            item["superseded_by"] = A1
    state = _state(tmp_path)
    export = {"path": "export/csv/x", "bytes": 5, "partial": False, "errors": []}
    _set(state, D3, "done", export=export)
    if layer_migrated:
        _set(state, A1, "done", dataset_ids=["ds-1"])
    else:
        _set(state, A1, "failed", error="probe failed")
    report = report_mod.build_run_report(plan, state)
    return layer_title, report, report_mod.render_run_markdown(report)


def test_a_source_file_superseded_by_a_hosted_layer_is_not_reported_as_unhostable(
    tmp_path,
):
    layer_title, report, text = _superseded_report(tmp_path, layer_migrated=True)

    assert report["unsupported"][0]["replacement"] == (
        f"Published as {layer_title}; migrated with it."
    )
    assert "No equivalent in GeoLens." not in text
    assert "## Items GeoLens can't host" not in text
    assert "## Source files published as hosted layers" in text


def test_a_superseded_source_file_whose_layer_did_not_migrate_says_so(tmp_path):
    layer_title, report, _text = _superseded_report(tmp_path, layer_migrated=False)

    replacement = report["unsupported"][0]["replacement"]
    assert replacement == f"Source file of {layer_title}, which has not migrated."
    assert "migrated with it" not in replacement


def test_a_layer_with_a_dataset_that_then_failed_is_not_called_migrated(tmp_path):
    plan = _plan(tmp_path)
    for item in plan["items"]:
        if item["id"] == D3:
            item["superseded_by"] = A1
    state = _state(tmp_path)
    export = {"path": "export/csv/x", "bytes": 5, "partial": False, "errors": []}
    _set(state, D3, "done", export=export)
    _set(state, A1, "failed", dataset_ids=["ds-1"], error="second layer failed")

    report = report_mod.build_run_report(plan, state)

    assert "migrated with it" not in report["unsupported"][0]["replacement"]


def _run(runner, plan_file: Path, *flags: str):
    return runner.invoke(
        app, [*flags, "arcgis", "migrate", str(plan_file), "--only", A2]
    )


@pytest.fixture
def failing_plan(tmp_path, geolens):
    return _write_plan(tmp_path)


def test_a_run_writes_the_report_next_to_the_state_and_exits_1_on_a_failure(
    runner, failing_plan, geolens
):
    result = runner.invoke(
        app, ["--json", "arcgis", "migrate", str(failing_plan), "--only", A2]
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert [Path(p).name for p in payload["report"]] == [
        "arcgis-migration-report.json",
        "arcgis-migration-report.md",
    ]
    report = json.loads(
        (failing_plan.parent / "arcgis-migration-report.json").read_text()
    )
    assert len(report["items"]) == len(json.loads(failing_plan.read_text())["items"])
    assert report["counts"]["failed"] == 1


def test_a_dry_run_writes_no_report(runner, failing_plan, geolens):
    result = runner.invoke(
        app, ["--json", "arcgis", "migrate", str(failing_plan), "--dry-run"]
    )

    assert result.exit_code in (0, 1)
    assert not (failing_plan.parent / "arcgis-migration-report.md").exists()


@pytest.mark.parametrize(
    "flags", [(), ("--quiet",), ("--json",), ("--json", "--quiet")]
)
def test_a_failed_item_is_reported_in_every_output_mode(
    runner, failing_plan, geolens, flags
):
    result = _run(runner, failing_plan, *flags)

    assert result.exit_code == 1
    assert A2 in result.output and "probe failed" in result.output


def test_a_group_shared_export_gets_no_audience_follow_up(tmp_path):
    plan = _plan(tmp_path)
    for item in plan["items"]:
        if item["id"] == C3:
            item["target"]["visibility"] = "restricted"
            item["target"]["groups"] = ["g1"]
    state = _state(tmp_path)
    _set(
        state,
        C3,
        "done",
        export={"path": "p", "bytes": 1, "partial": False, "errors": []},
    )

    report = report_mod.build_run_report(plan, state, runnable={"import_layers"})

    assert (C3, "under_shared") not in {
        (f["item"], f["kind"]) for f in report["follow_ups"]
    }


def test_unavailable_actions_are_found_across_the_whole_plan(tmp_path):
    plan = _plan(tmp_path)

    report = report_mod.build_run_report(
        plan, _state(tmp_path), runnable={"import_layers"}
    )

    assert (B1, "not_available") in {
        (f["item"], f["kind"]) for f in report["follow_ups"]
    }


def test_an_interrupted_run_still_writes_the_report(
    runner, tmp_path, geolens, monkeypatch
):
    plan_file = _write_plan(tmp_path)

    def interrupted(ctx, item, entry):
        raise KeyboardInterrupt

    monkeypatch.setitem(migrate.HANDLERS, "import_layers", interrupted)
    result = runner.invoke(app, ["arcgis", "migrate", str(plan_file), "--only", A2])

    assert result.exit_code == 130
    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    assert report["stopped"] == "interrupted"
    assert report["counts"]["failed"] == 1


def test_a_failed_request_exit_still_writes_the_report(
    runner, tmp_path, geolens, monkeypatch
):
    plan_file = _write_plan(tmp_path)

    def exits(ctx, item, entry):
        raise typer.Exit(4)

    monkeypatch.setitem(migrate.HANDLERS, "import_layers", exits)
    result = runner.invoke(app, ["arcgis", "migrate", str(plan_file), "--only", A2])

    assert result.exit_code == 4
    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    assert report["stopped"] == "stopped by a failed request"


def test_group_sharing_that_was_never_read_is_a_follow_up(tmp_path):
    plan = _plan(tmp_path)
    for item in plan["items"]:
        if item["id"] == A1:
            item["target"]["visibility"] = "restricted"
            item["target"]["groups"] = None
        if item["id"] == A2:
            # Shared with the organization, so its groups add no one.
            item["target"]["visibility"] = "internal"
            item["target"]["groups"] = None
    state = _state(tmp_path)
    _set(state, A1, "done", dataset_ids=["ds-1"])
    _set(state, A2, "done", dataset_ids=["ds-2"])

    report = report_mod.build_run_report(plan, state, runnable={"import_layers"})

    under = {
        f["item"]: f["text"]
        for f in report["follow_ups"]
        if f["kind"] == "under_shared"
    }
    assert "group sharing wasn't read" in under[A1]
    assert A2 not in under


def test_a_superseding_layer_that_never_migrated_says_so(tmp_path):
    plan = _plan(tmp_path)
    for item in plan["items"]:
        if item["id"] == D3:
            item["superseded_by"] = A1
    state = _state(tmp_path)
    _set(state, A1, "failed", error="probe failed")

    report = report_mod.build_run_report(plan, state, runnable={"import_layers"})

    text = next(f["text"] for f in report["follow_ups"] if f["kind"] == "superseded")
    assert text.endswith("GeoLens dataset: not migrated")


def test_a_source_file_whose_action_was_changed_gets_no_superseded_follow_up(
    tmp_path,
):
    plan = _plan(tmp_path)
    for item in plan["items"]:
        if item["id"] == D3:
            item["superseded_by"] = A1
            item["defaults"].update(action="export_only", superseded_by=A1)
            item["action"] = "export_only"
    state = _state(tmp_path)
    _set(state, A1, "done", dataset_ids=["ds-1"])

    def kinds() -> set[str]:
        report = report_mod.build_run_report(plan, state, runnable={"import_file"})
        return {f["kind"] for f in report["follow_ups"] if f["item"] == D3}

    assert "superseded" in kinds()
    for item in plan["items"]:
        if item["id"] == D3:
            item["action"] = "import_file"
    assert "superseded" not in kinds()


def test_an_unexpected_error_still_writes_the_report(
    runner, tmp_path, geolens, monkeypatch
):
    plan_file = _write_plan(tmp_path)

    def breaks(ctx, item, entry):
        raise ValueError("malformed response")

    monkeypatch.setitem(migrate.HANDLERS, "import_layers", breaks)
    result = runner.invoke(app, ["arcgis", "migrate", str(plan_file), "--only", A2])

    assert result.exit_code == 1
    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    assert report["stopped"] == "stopped by an unexpected error"
    assert report["counts"]["running"] == 1


def test_a_changed_owner_and_a_collection_skip_are_follow_ups(tmp_path):
    plan = _plan(tmp_path)
    state = _state(tmp_path)
    _set(
        state,
        A1,
        "done",
        dataset_ids=["ds-1"],
        notes=["not filed into collections: the operator can't manage collections"],
    )

    report = report_mod.build_run_report(
        plan,
        state,
        runnable={"import_layers"},
        owner_changes=[{"item": A2, "owner": "newowner"}],
    )

    by_kind = {f["kind"]: f for f in report["follow_ups"]}
    assert by_kind["collections"]["item"] == A1
    assert by_kind["owner_changed"]["item"] == A2
    assert "newowner" in by_kind["owner_changed"]["text"]


def test_a_failed_export_is_marked_incomplete(tmp_path):
    plan = _plan(tmp_path)
    state = _state(tmp_path)
    export = {"path": "export/dashboard/x", "bytes": 5, "partial": False, "errors": []}
    _set(state, C3, "failed", error="export incomplete, rerun to retry", export=export)

    report = report_mod.build_run_report(plan, state, runnable={"import_layers"})
    text = report_mod.render_run_markdown(report)

    assert report["unsupported"][0]["incomplete"] is True
    assert (C3, "export_incomplete") in {
        (f["item"], f["kind"]) for f in report["follow_ups"]
    }
    assert "incomplete: the export failed" in text


def test_a_failed_item_left_out_of_the_run_still_gives_exit_1(
    runner, tmp_path, geolens, monkeypatch
):
    plan_file = _write_plan(tmp_path)
    state_path = tmp_path / "arcgis-migration-state.json"
    first = runner.invoke(app, ["arcgis", "migrate", str(plan_file), "--only", A2])
    assert first.exit_code == 1  # the probe has no route: A2 fails
    assert json.loads(state_path.read_text())["items"][A2]["status"] == "failed"

    result = runner.invoke(
        app, ["arcgis", "migrate", str(plan_file), "--only", A2, "--no-retry"]
    )

    assert result.exit_code == 1


def test_a_completed_run_reports_a_changed_owner(runner, tmp_path, geolens):
    plan_file = _write_plan(tmp_path)
    state_path = tmp_path / "arcgis-migration-state.json"
    plan = json.loads(plan_file.read_text())
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "portal_url": plan["portal"]["url"],
                "geolens_instance": layers.GEOLENS_INSTANCE,
                "items": {
                    A1: {
                        "status": "done",
                        "owner_id": "00000000-0000-0000-0000-0000000000b1",
                    }
                },
            }
        )
    )

    result = runner.invoke(app, ["arcgis", "migrate", str(plan_file), "--only", A2])

    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    assert (A1, "owner_changed") in {
        (f["item"], f["kind"]) for f in report["follow_ups"]
    }, result.output


def test_a_report_that_cannot_be_written_does_not_replace_the_exit_code(
    runner, tmp_path, geolens, monkeypatch
):
    plan_file = _write_plan(tmp_path)

    def interrupted(ctx, item, entry):
        raise KeyboardInterrupt

    def full_disk(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setitem(migrate.HANDLERS, "import_layers", interrupted)
    monkeypatch.setattr(migrate, "write_run_report", full_disk)

    result = runner.invoke(app, ["arcgis", "migrate", str(plan_file), "--only", A2])

    assert result.exit_code == 130


def test_the_partial_export_follow_up_names_no_single_cause(tmp_path):
    plan = _plan(tmp_path)
    state = _state(tmp_path)
    export = {"path": "p", "bytes": 1, "partial": True, "errors": []}
    _set(state, C3, "done", export=export)

    report = report_mod.build_run_report(plan, state, runnable={"import_layers"})

    text = next(
        f["text"] for f in report["follow_ups"] if f["kind"] == "export_partial"
    )
    assert "redact" in text and "size cap" in text


def test_the_group_mode_note_is_not_a_collection_permission_follow_up(tmp_path):
    plan = _plan(tmp_path)
    state = _state(tmp_path)
    _set(
        state,
        A1,
        "done",
        dataset_ids=["ds-1"],
        notes=[
            "not filed into collections: collection_from is group, and ArcGIS "
            "groups map to GeoLens groups, not collections"
        ],
    )

    report = report_mod.build_run_report(plan, state, runnable={"import_layers"})

    assert "collections" not in {f["kind"] for f in report["follow_ups"]}


def test_a_skipped_item_has_no_missing_dependency_follow_up(tmp_path):
    plan = _plan(tmp_path)
    for item in plan["items"]:
        if item["id"] == A1:
            item["action"] = "skip"
            item["depends_on"] = ["f" * 32]
    state = _state(tmp_path)

    report = report_mod.build_run_report(plan, state, runnable={"import_layers"})

    assert (A1, "unresolved_dependency") not in {
        (f["item"], f["kind"]) for f in report["follow_ups"]
    }


def test_a_report_that_cannot_be_written_at_the_end_of_a_run_exits_nonzero(
    runner, tmp_path, geolens, monkeypatch
):
    plan_file = _write_plan(tmp_path)

    def done(ctx, item, entry):
        return migrate.ItemResult()

    def full_disk(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setitem(migrate.HANDLERS, "import_layers", done)
    monkeypatch.setattr(migrate, "write_run_report", full_disk)
    monkeypatch.setattr(migrate, "transfer", lambda *a, **k: None)
    monkeypatch.setattr(migrate, "apply_item_metadata", lambda *a, **k: None)
    monkeypatch.setattr(migrate, "file_into_collections", lambda *a, **k: [])

    result = runner.invoke(app, ["arcgis", "migrate", str(plan_file), "--only", A2])

    assert result.exit_code == 1
    assert "couldn't write the report" in result.output


def test_a_failed_item_left_out_of_the_run_is_printed(runner, tmp_path, geolens):
    plan_file = _write_plan(tmp_path)
    runner.invoke(app, ["arcgis", "migrate", str(plan_file), "--only", A2])

    result = runner.invoke(
        app, ["arcgis", "migrate", str(plan_file), "--only", A2, "--no-retry"]
    )

    assert result.exit_code == 1
    assert A2 in result.output and "probe failed" in result.output


def test_an_early_exit_says_where_the_report_is(runner, tmp_path, geolens, monkeypatch):
    plan_file = _write_plan(tmp_path)

    def interrupted(ctx, item, entry):
        raise KeyboardInterrupt

    monkeypatch.setitem(migrate.HANDLERS, "import_layers", interrupted)
    result = runner.invoke(app, ["arcgis", "migrate", str(plan_file), "--only", A2])

    assert result.exit_code == 130
    assert "arcgis-migration-report.md" in result.output
