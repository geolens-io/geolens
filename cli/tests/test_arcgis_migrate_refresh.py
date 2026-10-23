"""`geolens arcgis migrate` reruns: refresh, replace, GeoLens changes and --cutover."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from geolens_cli import arcgis_migrate as migrate_mod
from geolens_cli import arcgis_migrate_cutover as cutover_mod
from geolens_cli import arcgis_migrate_refresh as refresh_mod
from geolens_cli.arcgis_portal import PortalError

from . import test_arcgis_migrate_files as files
from . import test_arcgis_migrate_layers as layers
from .arcgis_fake import A1, A2, D3, item_data_path
from .test_arcgis_migrate_layers import (
    FakeImport,
    _layer,
    _migrate,
    _state,
    _uuid,
    _write_plan,
    dataset_id,
)

geolens = layers.geolens
quick = layers.quick
portal = files.portal
private_tempdir = files.private_tempdir
plan_file = layers.plan_file

LATER = "2026-10-02T00:00:00Z"
EDITED = "2026-10-03T00:00:00Z"
ALICE = "00000000-0000-0000-0000-0000000000a1"
PARCELS = dataset_id("Parcels")
ROADS = dataset_id("Roads")
ALICE_EDIT = {"updated_at": EDITED, "updated_by": ALICE, "data_revision": 1}
# The fixture's inventory is a complete org one read by an org admin.
USER_INVENTORY = {"scope": {"mode": "user", "owner": "gis_admin", "org_id": None}}


def _run(dataset: str, run_id: str, status: str, **extra) -> dict:
    return {
        "id": run_id,
        "dataset_id": dataset,
        "origin_kind": "service",
        "trigger": "manual",
        "status": status,
        "started_at": layers.NOW,
        "finished_at": None if status == "running" else LATER,
        **extra,
    }


class FakeRefresh:
    """The refresh endpoint and run history of the datasets it is given."""

    def __init__(self, fake, service: FakeImport, outcome: str = "succeeded") -> None:
        self.fake = fake
        self.service = service
        self.outcome = outcome
        self.extra: dict = {}
        self.bodies: list[dict] = []
        self.runs: dict[str, list[dict]] = {}

    def allow(self, *datasets: str) -> FakeRefresh:
        for dataset in datasets:
            self.fake.routes[f"POST /datasets/{dataset}/refresh"] = (
                lambda seen, d=dataset: self.refresh(d, seen)
            )
            self.fake.routes[f"GET /datasets/{dataset}/refresh-runs"] = (
                lambda seen, d=dataset: self.history(d, seen)
            )
        return self

    def history(self, dataset: str, seen) -> dict:
        query = dict(parse_qsl(urlsplit(seen.url).query))
        skip, limit = int(query.get("skip", 0)), int(query.get("limit", 50))
        runs = self.runs.get(dataset, [])
        return {"runs": runs[skip : skip + limit], "total": len(runs)}

    def refresh(self, dataset: str, seen):
        self.bodies.append(seen.json())
        run_id = _uuid("5e", f"{len(self.bodies):02d}")
        self.runs.setdefault(dataset, []).insert(
            0, _run(dataset, run_id, self.outcome, **self.extra)
        )
        if self.outcome == "succeeded":
            # The swap is the operator's write.
            self.service.fields.setdefault(dataset, {}).update(
                updated_at=LATER, updated_by=layers.OPERATOR
            )
        return (
            202,
            {
                "run_id": run_id,
                "job_id": _uuid("0a", f"{len(self.bodies):02d}"),
                "dataset_id": dataset,
                "origin_kind": "service",
                "trigger": "manual",
                "message": "queued",
                "status": "pending",
            },
        )


def _preview(job: str) -> dict:
    diff = {
        "columns_added": [],
        "columns_removed": [],
        "type_changes": [],
        "row_count_old": 2,
        "row_count_new": 2,
        "row_count_delta": 0,
    }
    return {
        "job_id": job,
        "source_filename": "f.csv",
        "columns": [],
        "crs": 4326,
        "geometry_type": "Point",
        "feature_count": 2,
        "sample_rows": [],
        "layer_name": "f",
        "schema_diff": diff,
    }


def _migrated(runner, plan_file: Path, geolens, item: str = A2, *args: str):
    service = FakeImport(geolens, [_layer(0, "Parcels")], needs_auth=item == A1)
    result, _ = _migrate(runner, plan_file, "--only", item, *args)
    assert result.exit_code == 0, result.output
    return service


def _service_url(plan_file: Path, item: str) -> str:
    inventory = json.loads((plan_file.parent / "arcgis-inventory.json").read_text())
    return next(row["url"] for row in inventory["items"] if row["id"] == item)


def _set_snippet(plan_file: Path, item: str, snippet: str) -> None:
    path = plan_file.parent / "arcgis-inventory.json"
    inventory = json.loads(path.read_text())
    for row in inventory["items"]:
        if row["id"] == item:
            row["snippet"] = snippet
    path.write_text(json.dumps(inventory))


def _edit_state(plan_file: Path, item: str, **changes) -> None:
    path = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(path.read_text())
    state["items"][item].update(changes)
    path.write_text(json.dumps(state))


def _edit_plan(plan_file: Path, keep: tuple[str, ...], **inventory) -> None:
    """Leave only the *keep* items to run, and update the plan's inventory block."""
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] not in keep:
            item["action"] = "skip"
    plan["inventory"].update(inventory)
    plan_file.write_text(json.dumps(plan))


# Refresh


def test_a_rerun_refreshes_a_migrated_service_and_records_its_last_update(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert payload["refreshed"] == [A2] and payload["not_up_to_date"] == {}
    [body] = refresh.bodies
    assert "auth" not in body and "accept_blocked_run_id" not in body
    assert body["expected_data_revision"] == 0
    entry = _state(plan_file)["items"][A2]
    assert entry["last_update"][PARCELS]["updated_at"].startswith("2026-10-02")
    assert entry["refreshing"] == {} and entry["stale"] == []


def test_a_private_service_is_refreshed_with_the_token(runner, plan_file, geolens):
    token = secrets.token_urlsafe(16)
    service = _migrated(runner, plan_file, geolens, A1, "--token", token)
    service.fields.setdefault(PARCELS, {}).update(
        {"origin_ref": {"url": _service_url(plan_file, A1)}}
    )
    refresh = FakeRefresh(geolens, service).allow(PARCELS)

    result, _ = _migrate(runner, plan_file, "--only", A1, "--token", token)

    assert result.exit_code == 0, result.output
    [body] = refresh.bodies
    assert body["auth"] == {"method": "bearer", "token": token}
    raw = (plan_file.parent / "arcgis-migration-state.json").read_text()
    assert token not in raw and token not in result.output


def test_the_token_is_not_sent_to_a_stored_source_on_another_host(
    runner, plan_file, geolens
):
    token = secrets.token_urlsafe(16)
    service = _migrated(runner, plan_file, geolens, A1, "--token", token)
    service.fields.setdefault(PARCELS, {}).update(
        {"origin_ref": {"url": "https://elsewhere.example.org/arcgis/rest/services/P"}}
    )
    refresh = FakeRefresh(geolens, service).allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--only", A1, "--token", token)

    assert result.exit_code == 1
    assert refresh.bodies == []
    [reason] = payload["not_up_to_date"][A1]
    assert "token was not sent" in reason
    assert reason.rsplit("--trust-service-host ", 1)[1] == "elsewhere.example.org"
    assert token not in result.output


@pytest.mark.parametrize(
    "edit",
    [
        {"updated_at": EDITED, "updated_by": ALICE},
        # A feature added by the operator's own account moves only the count.
        {"feature_count": 5},
        # An attribute edit by the operator's own account moves only the revision.
        {"data_revision": 1},
    ],
)
def test_a_dataset_changed_in_geolens_since_the_last_run_is_left_alone(
    runner, plan_file, geolens, edit
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    service.fields.setdefault(PARCELS, {}).update(edit)
    before = len(geolens.seen)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert refresh.bodies == []
    assert [s for s in geolens.seen[before:] if s.method not in ("GET", "POST")] == []
    [reason] = payload["not_up_to_date"][A2]
    assert "changed in GeoLens since the last run" in reason
    entry = _state(plan_file)["items"][A2]
    assert entry["last_update"][PARCELS] == {
        "updated_at": "2026-10-01T00:00:00+00:00",
        "feature_count": 0,
        "data_revision": 0,
    }


@pytest.mark.parametrize(
    ("updated_by", "updated_at", "refreshed"),
    [
        (layers.OPERATOR, LATER, True),
        # A user deleted since their edit leaves no updated_by.
        (None, LATER, False),
        (ALICE, LATER, False),
        # Someone else's edit after the item finished, then the operator's.
        (layers.OPERATOR, EDITED, False),
    ],
)
def test_a_state_without_last_updates_trusts_only_the_operators_last_write(
    runner, plan_file, geolens, updated_by, updated_at, refreshed
):
    service = _migrated(runner, plan_file, geolens)
    _edit_state(plan_file, A2, last_update={}, finished_at="2026-10-02T12:00:00Z")
    service.fields.setdefault(PARCELS, {}).update(
        {"updated_at": updated_at, "updated_by": updated_by}
    )
    refresh = FakeRefresh(geolens, service).allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert bool(refresh.bodies) is refreshed
    assert result.exit_code == (0 if refreshed else 1)
    if not refreshed:
        assert (
            "changed in GeoLens since it was migrated"
            in (payload["not_up_to_date"][A2][0])
        )


def test_a_refresh_that_stops_for_review_is_reported_not_accepted(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service, outcome="blocked").allow(PARCELS)
    refresh.extra = {"verification": {"review_reasons": ["live_data_changed"]}}

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    [body] = refresh.bodies
    assert "accept_blocked_run_id" not in body
    [reason] = payload["not_up_to_date"][A2]
    run_id = refresh.runs[PARCELS][0]["id"]
    assert "stopped for review and published nothing" in reason
    assert "Features were edited while the replacement ran" in reason
    assert f"geolens refresh {PARCELS} --accept-blocked-run {run_id}" in reason


@pytest.mark.parametrize(
    ("after", "adopted"),
    [
        ({"updated_by": layers.OPERATOR}, True),
        # Edited by someone else while the refresh ran.
        ({"updated_by": ALICE}, False),
        # The operator's own feature edit after the refresh published.
        ({"updated_by": layers.OPERATOR, "data_revision": 1}, False),
    ],
)
def test_a_refresh_still_running_at_the_deadline_is_picked_up_by_the_next_run(
    runner, plan_file, geolens, monkeypatch, after, adopted
):
    monkeypatch.setattr(refresh_mod, "JOB_TIMEOUT", 0.05)
    monkeypatch.setattr(refresh_mod, "JOB_POLL_INTERVAL", 0.01)
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service, outcome="running").allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert "still running" in payload["not_up_to_date"][A2][0]
    entry = _state(plan_file)["items"][A2]
    [run] = refresh.runs[PARCELS]
    assert entry["refreshing"] == {
        PARCELS: {
            "run": run["id"],
            "revision": 0,
            "by": layers.OPERATOR,
            "owner": layers.OPERATOR,
        }
    }
    assert entry["last_update"][PARCELS]["updated_at"].startswith("2026-10-01")

    run.update(status="succeeded", finished_at=LATER)
    service.fields.setdefault(PARCELS, {}).update({"updated_at": LATER, **after})
    refresh.outcome = "succeeded"
    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert (len(refresh.bodies) == 2) is adopted
    assert result.exit_code == (0 if adopted else 1), result.output
    if adopted:
        assert _state(plan_file)["items"][A2]["refreshing"] == {}


def test_a_refresh_an_earlier_run_left_is_found_behind_newer_runs(
    runner, plan_file, geolens, monkeypatch
):
    monkeypatch.setattr(refresh_mod, "JOB_TIMEOUT", 0.05)
    monkeypatch.setattr(refresh_mod, "JOB_POLL_INTERVAL", 0.01)
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service, outcome="running").allow(PARCELS)
    _migrate(runner, plan_file, "--only", A2)
    [run] = refresh.runs[PARCELS]
    run.update(status="succeeded", finished_at=LATER)
    service.fields.setdefault(PARCELS, {}).update({"updated_at": LATER})
    newer = [
        _run(PARCELS, _uuid("6e", f"{n:02d}"), "failed", trigger="scheduled")
        for n in range(60)
    ]
    refresh.runs[PARCELS] = [*newer, run]
    refresh.outcome = "succeeded"

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert len(refresh.bodies) == 2
    assert _state(plan_file)["items"][A2]["refreshing"] == {}


def test_a_recovered_refresh_is_recorded_before_the_next_one_starts(
    runner, plan_file, geolens, monkeypatch
):
    monkeypatch.setattr(refresh_mod, "JOB_TIMEOUT", 0.05)
    monkeypatch.setattr(refresh_mod, "JOB_POLL_INTERVAL", 0.01)
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service, outcome="running").allow(PARCELS)
    _migrate(runner, plan_file, "--only", A2)
    [run] = refresh.runs[PARCELS]
    run.update(status="succeeded", finished_at=LATER)
    service.fields.setdefault(PARCELS, {}).update({"updated_at": LATER})

    refresh.outcome = "failed"
    result, _ = _migrate(runner, plan_file, "--only", A2)
    assert result.exit_code == 1 and len(refresh.bodies) == 2
    recorded = _state(plan_file)["items"][A2]["last_update"][PARCELS]
    assert recorded["updated_at"].startswith("2026-10-02")

    refresh.outcome = "succeeded"
    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert len(refresh.bodies) == 3


@pytest.mark.parametrize(("by", "adopted"), [(ALICE, True), (None, False)])
def test_a_refresh_another_admin_started_is_taken_as_this_commands_own(
    runner, plan_file, geolens, by, adopted
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    run_id = _uuid("5e", "77")
    refresh.runs[PARCELS] = [_run(PARCELS, run_id, "succeeded")]
    marker = {"run": run_id, "revision": 0, **({"by": by} if by else {})}
    _edit_state(plan_file, A2, refreshing={PARCELS: marker})
    service.fields.setdefault(PARCELS, {}).update(
        {"updated_at": LATER, "updated_by": ALICE}
    )

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert bool(refresh.bodies) is adopted
    assert result.exit_code == (0 if adopted else 1), result.output


def _lose_the_answer(geolens, refresh: FakeRefresh) -> None:
    """GeoLens accepts the refresh and the response never arrives."""

    def lost(seen):
        refresh.refresh(PARCELS, seen)
        raise httpx.ReadTimeout("timed out")

    geolens.routes[f"POST /datasets/{PARCELS}/refresh"] = lost


def test_a_refresh_whose_answer_was_lost_is_adopted_on_the_next_run(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    refresh.extra = {"triggered_by": layers.OPERATOR}
    _lose_the_answer(geolens, refresh)

    first, _ = _migrate(runner, plan_file, "--only", A2)

    assert first.exit_code != 0 and len(refresh.bodies) == 1
    [marker] = _state(plan_file)["items"][A2]["refreshing"].values()
    assert marker["pending"] == 0
    refresh.allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert payload["not_up_to_date"] == {}
    assert _state(plan_file)["items"][A2]["refreshing"] == {}


def test_a_refresh_answered_by_a_gateway_error_is_adopted_on_the_next_run(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    refresh.extra = {"triggered_by": layers.OPERATOR}

    def queued_then_bad_gateway(seen):
        refresh.refresh(PARCELS, seen)
        return (502, {"detail": "Bad Gateway"})

    geolens.routes[f"POST /datasets/{PARCELS}/refresh"] = queued_then_bad_gateway
    first, _ = _migrate(runner, plan_file, "--only", A2)
    assert first.exit_code != 0 and len(refresh.bodies) == 1
    refresh.allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert payload["not_up_to_date"] == {}
    assert _state(plan_file)["items"][A2]["refreshing"] == {}


def test_a_lost_request_that_never_landed_starts_again(runner, plan_file, geolens):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    refresh.extra = {"triggered_by": layers.OPERATOR}

    def down(seen):
        raise httpx.ConnectError("down")

    geolens.routes[f"POST /datasets/{PARCELS}/refresh"] = down
    first, _ = _migrate(runner, plan_file, "--only", A2)
    assert first.exit_code != 0 and refresh.bodies == []
    refresh.allow(PARCELS)

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert len(refresh.bodies) == 1


def test_two_runs_started_after_a_lost_request_are_reported(runner, plan_file, geolens):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    refresh.extra = {"triggered_by": layers.OPERATOR}
    _lose_the_answer(geolens, refresh)
    _migrate(runner, plan_file, "--only", A2)
    refresh.runs[PARCELS].insert(
        0, _run(PARCELS, _uuid("7e", "01"), "succeeded", triggered_by=layers.OPERATOR)
    )
    refresh.allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert "more than one refresh was started" in payload["not_up_to_date"][A2][0]
    assert len(refresh.bodies) == 1


def test_a_lost_request_with_a_page_of_runs_since_is_reported(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    refresh.extra = {"triggered_by": layers.OPERATOR}
    _lose_the_answer(geolens, refresh)
    _migrate(runner, plan_file, "--only", A2)
    # The lost run is 51st; the newest page holds one other run by the operator.
    for n in range(49):
        refresh.runs[PARCELS].insert(
            0, _run(PARCELS, _uuid("7e", f"{n:02d}"), "succeeded", triggered_by=ALICE)
        )
    refresh.runs[PARCELS].insert(
        0, _run(PARCELS, _uuid("7f", "01"), "succeeded", triggered_by=layers.OPERATOR)
    )
    refresh.allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert "more refreshes were started" in payload["not_up_to_date"][A2][0]
    assert len(refresh.bodies) == 1


@pytest.mark.parametrize("edited_after", [False, True])
def test_a_blocked_run_the_operator_accepts_is_recorded_as_the_migrations(
    runner, plan_file, geolens, edited_after
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service, outcome="blocked").allow(PARCELS)
    refresh.extra = {"verification": {"review_reasons": ["live_data_changed"]}}
    _migrate(runner, plan_file, "--only", A2)
    [blocked] = refresh.runs[PARCELS]
    # `geolens refresh --accept-blocked-run` starts a successor that publishes.
    refresh.runs[PARCELS].insert(
        0,
        _run(
            PARCELS,
            _uuid("8e", "01"),
            "succeeded",
            triggered_by=ALICE,
            # It publishes over the live edit that blocked the first run.
            verification={"accepted_blocked_run_id": blocked["id"], "data_revision": 1},
        ),
    )
    service.fields.setdefault(PARCELS, {}).update(
        {
            "updated_at": LATER,
            "updated_by": ALICE,
            "data_revision": 2 if edited_after else 1,
        }
    )
    refresh.outcome = "succeeded"

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == (1 if edited_after else 0), result.output
    assert bool(payload["not_up_to_date"]) is edited_after


def test_a_rerun_writes_the_portals_new_item_metadata(runner, tmp_path, geolens):
    plan_file = _write_plan(tmp_path, rows={A2: {"snippet": "Old summary"}})
    service = _migrated(runner, plan_file, geolens)
    FakeRefresh(geolens, service).allow(PARCELS)
    _set_snippet(plan_file, A2, "New summary")

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert service.summaries[PARCELS].startswith("New summary")


@pytest.mark.parametrize("edited", [False, True])
def test_a_summary_cleared_in_the_portal_is_cleared_unless_edited_in_geolens(
    runner, tmp_path, geolens, edited
):
    plan_file = _write_plan(tmp_path, rows={A2: {"snippet": "Old summary"}})
    service = _migrated(runner, plan_file, geolens)
    FakeRefresh(geolens, service).allow(PARCELS)
    assert service.summaries[PARCELS].startswith("Old summary")
    _set_snippet(plan_file, A2, None)
    path = plan_file.parent / "arcgis-inventory.json"
    inventory = json.loads(path.read_text())
    for row in inventory["items"]:
        if row["id"] == A2:
            row["description"] = None
    path.write_text(json.dumps(inventory))
    if edited:
        service.summaries[PARCELS] = "Written in GeoLens"

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][A2]
    if edited:
        assert service.summaries[PARCELS] == "Written in GeoLens"
        assert (
            f"kept the summary edited in GeoLens on dataset {PARCELS}"
            in (entry["notes"])
        )
    else:
        assert service.summaries[PARCELS] is None
        assert entry["metadata_baseline"][PARCELS]["summary"] == ""


def _set_visibility(plan_file: Path, item_id: str, visibility: str) -> None:
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == item_id:
            item["target"]["visibility"] = visibility
    plan_file.write_text(json.dumps(plan))


def test_a_visibility_narrowed_in_the_portal_is_applied_on_a_rerun(
    runner, plan_file, geolens
):
    _edit_plan(plan_file, (A2,))
    service = FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    _migrate(runner, plan_file)
    assert service.fields[PARCELS]["visibility"] == "public"
    FakeRefresh(geolens, service).allow(PARCELS)
    _set_visibility(plan_file, A2, "private")
    before = len(geolens.seen)

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 0, result.output
    sent = [
        s.json()
        for s in geolens.seen[before:]
        if s.method == "PATCH" and "visibility" in s.json()
    ]
    assert sent == [
        {"visibility": "private", "expected_updated_at": "2026-10-01T00:00:00+00:00"}
    ]
    assert service.fields[PARCELS]["visibility"] == "private"
    assert _state(plan_file)["items"][A2]["visibility"] == {PARCELS: "private"}
    assert payload["cutover"]["marked"] is True


def _stale(seen):
    detail = {"code": "stale_write", "message": "changed"}
    return (409, layers._problem(409, detail))


def test_a_visibility_write_geolens_refuses_as_stale_is_reported_not_recorded(
    runner, plan_file, geolens
):
    _edit_plan(plan_file, (A2,))
    service = FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    _migrate(runner, plan_file)
    FakeRefresh(geolens, service).allow(PARCELS)
    _set_visibility(plan_file, A2, "private")
    recorded = _state(plan_file)["items"][A2]["last_update"]
    geolens.routes[f"PATCH /datasets/{PARCELS}"] = _stale

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    [reason] = payload["not_up_to_date"][A2]
    assert reason.endswith(
        "changed in GeoLens while its visibility was written; it was left as it is"
    )
    entry = _state(plan_file)["items"][A2]
    assert entry["visibility"] == {PARCELS: "public"}
    assert entry["last_update"] == recorded


@pytest.mark.parametrize(
    ("recorded", "says"),
    [("public", "was changed to internal in GeoLens"), (None, "doesn't say")],
)
def test_a_visibility_the_rerun_cant_attribute_is_reported_not_applied(
    runner, plan_file, geolens, recorded, says
):
    _edit_plan(plan_file, (A2,))
    service = FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    _migrate(runner, plan_file)
    FakeRefresh(geolens, service).allow(PARCELS)
    service.fields[PARCELS]["visibility"] = "internal"
    _edit_state(plan_file, A2, visibility={PARCELS: recorded} if recorded else {})
    _set_visibility(plan_file, A2, "private")
    before = len(geolens.seen)

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    assert says in payload["not_up_to_date"][A2][0]
    assert not [s for s in geolens.seen[before:] if s.method == "PATCH"]
    assert payload["cutover"]["refused"] == ["unfinished-items"]


def test_a_data_file_is_downloaded_again_and_replaced(
    runner, tmp_path, geolens, portal
):
    files.FakeFiles(geolens)
    plan_file = files._plan(tmp_path)
    result, _ = _migrate(runner, plan_file, "--only", D3)
    assert result.exit_code == 0, result.output
    [dataset] = _state(plan_file)["items"][D3]["dataset_ids"]
    job = _uuid("0c", "01")
    sent: dict[str, list] = {"upload": [], "commit": []}

    def upload(seen):
        sent["upload"].append(seen.body)
        return (201, {"job_id": job, "message": "ok", "status": "pending"})

    def commit(seen):
        sent["commit"].append(seen.json())
        return (202, {"job_id": job, "status": "pending", "message": "queued"})

    geolens.routes.update(
        {
            f"POST /datasets/{dataset}/reupload": upload,
            f"POST /datasets/{dataset}/reupload/{job}/preview": _preview(job),
            f"POST /datasets/{dataset}/reupload/{job}/commit": commit,
            f"GET /datasets/{dataset}/refresh-runs": {
                "runs": [
                    _run(dataset, _uuid("5e", "01"), "succeeded", ingest_job_id=job)
                ],
                "total": 1,
            },
        }
    )

    result, payload = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert payload["refreshed"] == [D3] and payload["not_up_to_date"] == {}
    assert len(portal.requests_to(item_data_path(D3))) == 2
    [body] = sent["upload"]
    assert files.CSV in body
    [committed] = sent["commit"]
    assert "review_fingerprint" not in committed
    assert committed["expected_data_revision"] == 0
    assert _state(plan_file)["items"][D3]["refreshing"] == {}


def test_a_data_file_whose_visibility_this_run_changed_is_still_replaced(
    runner, tmp_path, geolens, portal
):
    imported = files.FakeFiles(geolens)
    plan_file = files._plan(tmp_path)
    _migrate(runner, plan_file, "--only", D3)
    [dataset] = _state(plan_file)["items"][D3]["dataset_ids"]
    _set_visibility(plan_file, D3, "private")
    job = _uuid("0c", "01")
    commits = []
    patch = geolens.routes[f"PATCH /datasets/{dataset}"]

    def patch_moving_updated_at(seen):
        imported.helper.fields.setdefault(dataset, {}).update(
            {"updated_at": "2026-10-02T00:00:00Z", "updated_by": layers.OPERATOR}
        )
        return patch(seen)

    geolens.routes.update(
        {
            f"PATCH /datasets/{dataset}": patch_moving_updated_at,
            f"POST /datasets/{dataset}/reupload": (
                201,
                {"job_id": job, "message": "ok", "status": "pending"},
            ),
            f"POST /datasets/{dataset}/reupload/{job}/preview": _preview(job),
            f"POST /datasets/{dataset}/reupload/{job}/commit": lambda seen: (
                commits.append(seen.json())
                or (202, {"job_id": job, "status": "pending", "message": "queued"})
            ),
            f"GET /datasets/{dataset}/refresh-runs": {
                "runs": [
                    _run(dataset, _uuid("5e", "01"), "succeeded", ingest_job_id=job)
                ],
                "total": 1,
            },
        }
    )

    result, payload = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert payload["not_up_to_date"] == {}
    assert len(commits) == 1
    assert _state(plan_file)["items"][D3]["visibility"] == {dataset: "private"}


class EditDuring(FakeRefresh):
    """Alice edits *victim* when the refresh of *trigger* is requested."""

    def __init__(self, fake, service, trigger, victim, **kwargs) -> None:
        super().__init__(fake, service, **kwargs)
        self.trigger = trigger
        self.victim = victim

    def refresh(self, dataset, seen):
        out = super().refresh(dataset, seen)
        if dataset == self.trigger:
            self.service.fields.setdefault(self.victim, {}).update(ALICE_EDIT)
            self.trigger = None
        return out


def _patches_since(geolens, before: int) -> list:
    return [s for s in geolens.seen[before:] if s.method == "PATCH"]


@pytest.mark.parametrize("outcome", ["failed", "blocked"])
def test_an_edit_made_while_a_refresh_is_refused_stays_protected(
    runner, plan_file, geolens, outcome
):
    service = _migrated(runner, plan_file, geolens)
    refresh = EditDuring(geolens, service, PARCELS, PARCELS, outcome=outcome)
    refresh.allow(PARCELS)
    _set_snippet(plan_file, A2, "New summary")
    before = len(geolens.seen)

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    # Nothing was published, so the item's metadata isn't written either.
    assert _patches_since(geolens, before) == []
    entry = _state(plan_file)["items"][A2]
    assert entry["last_update"][PARCELS]["data_revision"] == 0
    # A run held for review stays tied to the migration, for its acceptance.
    held = [marker["blocked"] for marker in entry["refreshing"].values()]
    assert held == ([] if outcome == "failed" else [refresh.runs[PARCELS][0]["id"]])

    refresh.outcome = "succeeded"
    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert len(refresh.bodies) == 1
    assert "changed in GeoLens since the last run" in payload["not_up_to_date"][A2][0]


def test_a_dataset_edited_right_after_its_refresh_published_is_not_recorded(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    refresh = EditDuring(geolens, service, PARCELS, PARCELS).allow(PARCELS)
    before = len(geolens.seen)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    [reason] = payload["not_up_to_date"][A2]
    assert "changed in GeoLens while its refresh ran" in reason
    assert _patches_since(geolens, before) == []
    assert _state(plan_file)["items"][A2]["last_update"][PARCELS]["data_revision"] == 0

    _migrate(runner, plan_file, "--only", A2)
    assert len(refresh.bodies) == 1


def test_a_dataset_transferred_while_its_refresh_ran_is_not_recorded(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)

    class TransferDuring(FakeRefresh):
        def refresh(self, dataset, seen):
            out = super().refresh(dataset, seen)
            # The swap stamps the operator again; the revision doesn't move.
            self.service.fields[dataset]["created_by"] = ALICE
            return out

    refresh = TransferDuring(geolens, service).allow(PARCELS)
    before = len(geolens.seen)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    [reason] = payload["not_up_to_date"][A2]
    assert "changed in GeoLens while its refresh ran" in reason
    assert _patches_since(geolens, before) == []
    entry = _state(plan_file)["items"][A2]
    assert entry["last_update"][PARCELS]["updated_at"].startswith("2026-10-01")
    assert entry["refreshing"] == {} and len(refresh.bodies) == 1


def test_a_layer_edited_while_another_layer_refreshes_stays_protected(
    runner, plan_file, geolens
):
    service = FakeImport(geolens, [_layer(0, "Parcels"), _layer(1, "Roads")])
    result, _ = _migrate(runner, plan_file, "--only", A2)
    assert result.exit_code == 0, result.output
    refresh = EditDuring(geolens, service, ROADS, PARCELS).allow(PARCELS, ROADS)

    result, _ = _migrate(runner, plan_file, "--only", A2)
    assert result.exit_code == 0, result.output
    assert len(refresh.bodies) == 2

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert len(refresh.bodies) == 3
    [reason] = payload["not_up_to_date"][A2]
    assert reason.startswith(f"dataset {PARCELS}: changed in GeoLens")


def test_a_later_layer_edited_during_an_earlier_refresh_is_left_alone(
    runner, plan_file, geolens
):
    service = FakeImport(geolens, [_layer(0, "Parcels"), _layer(1, "Roads")])
    result, _ = _migrate(runner, plan_file, "--only", A2)
    assert result.exit_code == 0, result.output
    refresh = EditDuring(geolens, service, PARCELS, ROADS).allow(PARCELS, ROADS)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert list(refresh.runs) == [PARCELS]
    [reason] = payload["not_up_to_date"][A2]
    assert reason.startswith(f"dataset {ROADS}: changed in GeoLens")


def test_a_layer_added_to_a_migrated_service_is_reported_and_blocks_cutover(
    runner, plan_file, geolens
):
    _edit_plan(plan_file, (A2,))
    service = FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    _migrate(runner, plan_file)
    service.layers.append(_layer(1, "Roads", has_attachments=False))
    FakeRefresh(geolens, service).allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    assert payload["not_up_to_date"][A2] == [
        "layer Roads was added to the service in the portal and isn't migrated"
    ]
    assert payload["cutover"]["refused"] == ["unfinished-items"]


def test_a_layer_added_to_a_service_that_had_none_to_import_blocks_cutover(
    runner, plan_file, geolens
):
    _edit_plan(plan_file, (A2,))
    service = FakeImport(geolens, [_layer(0, "Imagery", "Raster Layer")])
    _migrate(runner, plan_file)
    service.layers.append(_layer(1, "Roads", has_attachments=False))

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    assert payload["not_up_to_date"][A2] == [
        "layer Roads was added to the service in the portal and isn't migrated"
    ]
    assert payload["cutover"]["refused"] == ["unfinished-items"]


def test_no_token_goes_out_when_the_stored_source_cant_be_read(
    runner, plan_file, geolens
):
    token = secrets.token_urlsafe(16)
    service = _migrated(runner, plan_file, geolens, A1, "--token", token)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--only", A1, "--token", token)

    assert result.exit_code == 1
    assert refresh.bodies == []
    assert "stored source can't be read" in payload["not_up_to_date"][A1][0]


def test_a_service_url_changed_in_the_portal_is_not_refreshed(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    path = plan_file.parent / "arcgis-inventory.json"
    inventory = json.loads(path.read_text())
    for row in inventory["items"]:
        if row["id"] == A2:
            row["url"] = "https://services1.arcgis.com/ExAmPlEoRg0123/x/FeatureServer"
    path.write_text(json.dumps(inventory))
    before = len(geolens.seen)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert refresh.bodies == []
    assert not any(s.url.endswith("/services/probe/") for s in geolens.seen[before:])
    assert "service URL changed" in payload["not_up_to_date"][A2][0]


def test_a_legacy_entry_adopts_its_service_url_and_refuses_a_later_change(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    url = _service_url(plan_file, A2)
    _edit_state(plan_file, A2, service_url=None)

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert _state(plan_file)["items"][A2]["service_url"] == url
    path = plan_file.parent / "arcgis-inventory.json"
    inventory = json.loads(path.read_text())
    for row in inventory["items"]:
        if row["id"] == A2:
            row["url"] = "https://services1.arcgis.com/ExAmPlEoRg0123/x/FeatureServer"
    path.write_text(json.dumps(inventory))

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert len(refresh.bodies) == 1
    assert "service URL changed" in payload["not_up_to_date"][A2][0]


def test_a_refresh_an_earlier_run_left_running_is_not_started_again(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    run_id = _uuid("5e", "99")
    refresh.runs[PARCELS] = [_run(PARCELS, run_id, "running")]
    _edit_state(plan_file, A2, refreshing={PARCELS: {"run": run_id, "revision": 0}})

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert refresh.bodies == []
    assert "still running" in payload["not_up_to_date"][A2][0]


@pytest.mark.parametrize("flag", ["removed", "unlisted"])
def test_items_gone_or_unlisted_are_not_refreshed(runner, plan_file, geolens, flag):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    _edit_plan(plan_file, (A2,))
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == A2:
            item[flag] = True
    plan_file.write_text(json.dumps(plan))

    _, payload = _migrate(runner, plan_file)

    assert refresh.bodies == [] and A2 not in payload["refreshed"]


def test_a_stopped_refresh_ends_the_pass_and_marks_no_cutover(
    runner, plan_file, geolens
):
    token = secrets.token_urlsafe(16)
    _edit_plan(plan_file, (A1, A2))
    # Both items share the Parcels dataset; give them one visibility.
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        item["target"]["visibility"] = "internal"
    plan_file.write_text(json.dumps(plan))
    service = FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    result, _ = _migrate(runner, plan_file, "--token", token)
    assert result.exit_code == 0, result.output
    service.fields.setdefault(PARCELS, {}).update(
        {"origin_ref": {"url": _service_url(plan_file, A1)}}
    )
    FakeRefresh(geolens, service).allow(PARCELS)
    geolens.routes[f"POST /datasets/{PARCELS}/refresh"] = (
        503,
        {
            "title": "Unavailable",
            "status": 503,
            "detail": {"code": "credential_store_unavailable", "message": "no store"},
        },
    )

    result, payload = _migrate(
        runner,
        plan_file,
        "--token",
        token,
        "--cutover",
        *(f"--accept-{c}" for c in cutover_mod.CHECKS),
    )

    assert result.exit_code == 1
    assert payload["refreshed"] == [A1]
    assert payload["stopped"] and payload["cutover"]["marked"] is False
    assert _state(plan_file)["cutover"] is None


def test_a_layer_added_to_a_migrated_multi_layer_file_is_reported_and_blocks_cutover(
    runner, tmp_path, geolens, portal
):
    files.FakeFiles(geolens, layer_names=["Roads", "Parcels"])
    plan_file = files._plan(tmp_path)
    _edit_plan(plan_file, (D3,))
    result, _ = _migrate(runner, plan_file)
    assert result.exit_code == 0, result.output
    datasets = _state(plan_file)["items"][D3]["dataset_ids"]
    assert datasets == [dataset_id("Roads"), dataset_id("Parcels")]
    committed = []
    for n, dataset in enumerate(datasets):
        job = _uuid("0c", f"{n:02d}")
        preview = _preview(job)
        preview["all_layers"] = [
            {"name": name} for name in ("Roads", "Parcels", "Hydrants")
        ]
        geolens.routes.update(
            {
                f"POST /datasets/{dataset}/reupload": (
                    201,
                    {"job_id": job, "message": "ok", "status": "pending"},
                ),
                f"POST /datasets/{dataset}/reupload/{job}/preview": preview,
                f"POST /datasets/{dataset}/reupload/{job}/commit": (
                    lambda seen, d=dataset, j=job: (
                        committed.append(d)
                        or (
                            202,
                            {"job_id": j, "status": "pending", "message": "queued"},
                        )
                    )
                ),
                f"GET /datasets/{dataset}/refresh-runs": {
                    "runs": [
                        _run(
                            dataset,
                            _uuid("5e", f"{n:02d}"),
                            "succeeded",
                            ingest_job_id=job,
                        )
                    ],
                    "total": 1,
                },
            }
        )

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    assert committed == datasets
    assert payload["not_up_to_date"][D3] == [
        "layer Hydrants is in the file but isn't migrated"
    ]
    assert payload["cutover"]["refused"] == ["unfinished-items"]


def test_a_replacement_of_a_file_that_now_holds_several_layers_is_not_committed(
    runner, tmp_path, geolens, portal
):
    files.FakeFiles(geolens)
    plan_file = files._plan(tmp_path)
    _migrate(runner, plan_file, "--only", D3)
    [dataset] = _state(plan_file)["items"][D3]["dataset_ids"]
    job = _uuid("0c", "01")
    preview = _preview(job)
    preview["all_layers"] = [{"name": "a"}, {"name": "b"}]
    geolens.routes.update(
        {
            f"POST /datasets/{dataset}/reupload": (
                201,
                {"job_id": job, "message": "ok"},
            ),
            f"POST /datasets/{dataset}/reupload/{job}/preview": preview,
        }
    )

    result, payload = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert not any(s.url.endswith("/commit") for s in geolens.seen)
    assert "now holds several layers" in payload["not_up_to_date"][D3][0]
    assert _state(plan_file)["items"][D3]["refreshing"] == {}


def test_a_file_dataset_rebound_to_a_service_is_not_replaced(
    runner, tmp_path, geolens, portal
):
    files.FakeFiles(geolens)
    plan_file = files._plan(tmp_path)
    _migrate(runner, plan_file, "--only", D3)
    [dataset] = _state(plan_file)["items"][D3]["dataset_ids"]
    served = geolens.routes[f"GET /datasets/{dataset}"]
    geolens.routes[f"GET /datasets/{dataset}"] = lambda s: {
        **served(s),
        "origin": "service",
    }

    result, payload = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert not any(s.url.endswith("/reupload") for s in geolens.seen)
    assert payload["not_up_to_date"][D3]


def test_a_geolens_without_data_revisions_gets_no_refresh(runner, plan_file, geolens):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    service.fields.setdefault(PARCELS, {}).update({"data_revision": None})

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert refresh.bodies == []
    [reason] = payload["not_up_to_date"][A2]
    assert "upgrade GeoLens to bring migrated datasets up to date safely" in reason


def test_the_record_stays_the_published_one_when_the_metadata_write_races_an_edit(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    FakeRefresh(geolens, service).allow(PARCELS)
    _set_snippet(plan_file, A2, "New summary")
    patch = geolens.routes[f"PATCH /datasets/{PARCELS}"]

    def patch_while_alice_edits(seen):
        reply = patch(seen)
        service.fields[PARCELS].update(ALICE_EDIT)
        return reply

    geolens.routes[f"PATCH /datasets/{PARCELS}"] = patch_while_alice_edits

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    [reason] = payload["not_up_to_date"][A2]
    assert "changed in GeoLens while its metadata was written" in reason
    assert service.summaries[PARCELS].startswith("New summary")
    assert _state(plan_file)["items"][A2]["last_update"][PARCELS] == {
        "updated_at": "2026-10-02T00:00:00+00:00",
        "feature_count": 0,
        "data_revision": 0,
    }


def test_a_metadata_write_geolens_refuses_as_stale_keeps_the_published_record(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    FakeRefresh(geolens, service).allow(PARCELS)
    _set_snippet(plan_file, A2, "New summary")
    sent = []

    def stale(seen):
        sent.append(seen.json())
        return _stale(seen)

    geolens.routes[f"PATCH /datasets/{PARCELS}"] = stale

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert [body["expected_updated_at"] for body in sent] == [
        "2026-10-02T00:00:00+00:00"
    ]
    [reason] = payload["not_up_to_date"][A2]
    assert reason.endswith(
        "changed in GeoLens while its metadata was written; it was left as it is"
    )
    assert _state(plan_file)["items"][A2]["last_update"][PARCELS] == {
        "updated_at": "2026-10-02T00:00:00+00:00",
        "feature_count": 0,
        "data_revision": 0,
    }


def test_a_replacement_made_in_geolens_during_the_upload_is_not_overwritten(
    runner, tmp_path, geolens, portal
):
    imported = files.FakeFiles(geolens)
    plan_file = files._plan(tmp_path)
    _migrate(runner, plan_file, "--only", D3)
    [dataset] = _state(plan_file)["items"][D3]["dataset_ids"]
    job = _uuid("0c", "01")

    def upload(seen):
        # A swap moves updated_at and updated_by, not the data revision.
        imported.helper.fields.setdefault(dataset, {}).update(
            {"updated_at": EDITED, "updated_by": ALICE}
        )
        return (201, {"job_id": job, "message": "ok", "status": "pending"})

    geolens.routes.update(
        {
            f"POST /datasets/{dataset}/reupload": upload,
            f"POST /datasets/{dataset}/reupload/{job}/preview": _preview(job),
        }
    )

    result, payload = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert not any(s.url.endswith("/commit") for s in geolens.seen)
    [reason] = payload["not_up_to_date"][D3]
    assert "changed in GeoLens during the upload" in reason
    assert _state(plan_file)["items"][D3]["refreshing"] == {}


def test_a_finished_file_item_without_a_recorded_dataset_is_reported(
    runner, tmp_path, geolens, portal
):
    files.FakeFiles(geolens)
    plan_file = files._plan(tmp_path)
    _migrate(runner, plan_file, "--only", D3)
    _edit_state(plan_file, D3, layer_datasets={}, dataset_ids=[])

    result, payload = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert "nothing to replace" in payload["not_up_to_date"][D3][0]


# Cutover


def test_cutover_refuses_a_migrated_layer_with_attachments_until_accepted(
    runner, plan_file, geolens
):
    _edit_plan(plan_file, (A2,))
    service = FakeImport(geolens, [_layer(0, "Parcels", has_attachments=True)])

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    assert payload["cutover"]["refused"] == ["attachment-loss"]
    [check] = payload["cutover"]["checks"]
    assert check["items"] == [
        {"item": A2, "reason": f"layer 0 ({PARCELS}) has attachments"}
    ]
    assert _state(plan_file)["cutover"] is None
    report = json.loads((plan_file.parent / "arcgis-migration-report.json").read_text())
    assert {
        "item": A2,
        "kind": "attachments",
        "text": ("layer 0 has attachments, which GeoLens doesn't import yet"),
    } in report["follow_ups"]
    assert report["cutover"]["refused"] == ["attachment-loss"]

    FakeRefresh(geolens, service).allow(PARCELS)
    result, payload = _migrate(
        runner, plan_file, "--cutover", "--accept-attachment-loss"
    )

    assert result.exit_code == 0, result.output
    assert payload["cutover"]["marked"] is True
    recorded = _state(plan_file)["cutover"]
    assert recorded["accepted"] == ["attachment-loss"] and recorded["at"]


@pytest.mark.parametrize("with_parcels", [True, False])
def test_cutover_counts_a_service_layer_geolens_does_not_import(
    runner, plan_file, geolens, with_parcels
):
    _edit_plan(plan_file, (A2,))
    imagery = _layer(1, "Imagery", "Raster Layer", has_attachments=False)
    group = _layer(2, "Districts", "Group Layer", has_attachments=False)
    parcels = [_layer(0, "Parcels", has_attachments=False)] if with_parcels else []
    service = FakeImport(geolens, [*parcels, imagery, group])
    result, _ = _migrate(runner, plan_file)
    assert result.exit_code == 0, result.output
    FakeRefresh(geolens, service).allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    assert payload["cutover"]["refused"] == ["unfinished-items"]
    [check] = payload["cutover"]["checks"]
    assert check["items"] == [
        {"item": A2, "reason": "Imagery: Raster Layer layer, not imported"}
    ]


def test_cutover_treats_a_layer_the_probe_says_nothing_about_as_a_loss(
    runner, plan_file, geolens
):
    _edit_plan(plan_file, (A2,))
    FakeImport(geolens, [_layer(0, "Parcels")])

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    [check] = payload["cutover"]["checks"]
    assert check["items"][0]["reason"].endswith("may have attachments")


def test_cutover_refuses_a_plan_not_merged_from_a_complete_org_inventory(
    runner, plan_file, geolens
):
    _edit_plan(plan_file, (A2,), **USER_INVENTORY)
    service = FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    assert payload["cutover"]["refused"] == ["incomplete-inventory"]
    assert _state(plan_file)["cutover"] is None

    FakeRefresh(geolens, service).allow(PARCELS)
    result, payload = _migrate(
        runner, plan_file, "--cutover", "--accept-incomplete-inventory"
    )
    assert result.exit_code == 0, result.output
    assert _state(plan_file)["cutover"]["accepted"] == ["incomplete-inventory"]


def test_cutover_refuses_unfinished_items_until_accepted(runner, plan_file, geolens):
    _edit_plan(plan_file, (A2,))
    service = FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    service.job_errors["Parcels"] = "boom"

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    assert payload["cutover"]["refused"] == ["unfinished-items"]
    assert payload["cutover"]["checks"][0]["items"] == [
        {"item": A2, "reason": "failed"}
    ]

    result, payload = _migrate(
        runner, plan_file, "--cutover", "--accept-unfinished-items", "--no-retry"
    )
    assert payload["cutover"]["marked"] is True
    # The item is still failed, so the run says so even though it is marked.
    assert result.exit_code == 1


def test_cutover_counts_a_finished_item_a_partial_merge_left_unlisted(
    runner, plan_file, geolens
):
    _edit_plan(plan_file, (A2,))
    FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    result, _ = _migrate(runner, plan_file)
    assert result.exit_code == 0, result.output
    plan = json.loads(plan_file.read_text())
    plan["inventory"]["complete"] = False
    for item in plan["items"]:
        if item["id"] == A2:
            item["unlisted"] = True
    plan_file.write_text(json.dumps(plan))

    result, payload = _migrate(
        runner, plan_file, "--cutover", "--accept-incomplete-inventory"
    )

    assert result.exit_code == 1
    assert payload["cutover"]["refused"] == ["unfinished-items"]
    [check] = [
        c for c in payload["cutover"]["checks"] if c["check"] == "unfinished-items"
    ]
    assert check["items"] == [{"item": A2, "reason": "unlisted"}]
    assert _state(plan_file)["cutover"] is None


def test_cutover_counts_an_item_left_out_of_date_as_unfinished(
    runner, plan_file, geolens
):
    _edit_plan(plan_file, (A2,))
    service = FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    _migrate(runner, plan_file)
    FakeRefresh(geolens, service, outcome="failed").allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    [check] = payload["cutover"]["checks"]
    assert check["check"] == "unfinished-items"
    assert "its refresh ended failed" in check["items"][0]["reason"]


def test_a_dry_run_shows_the_cutover_checks_and_writes_nothing(
    runner, plan_file, geolens
):
    _edit_plan(plan_file, (A2,), **USER_INVENTORY)
    FakeImport(geolens, [_layer(0, "Parcels")])

    result, payload = _migrate(runner, plan_file, "--cutover", "--dry-run")

    assert result.exit_code == 1
    assert payload["cutover"]["marked"] is False
    assert payload["cutover"]["refused"] == ["unfinished-items", "incomplete-inventory"]
    assert not (plan_file.parent / "arcgis-migration-state.json").exists()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("--accept-attachment-loss",), "go with --cutover"),
        (("--cutover", "--only", A2), "drop --only"),
    ],
)
def test_cutover_option_misuse_is_a_usage_error(
    runner, plan_file, geolens, args, message
):
    result, _ = _migrate(runner, plan_file, *args)
    assert result.exit_code == 2
    assert message in result.output
    assert geolens.seen == []


def test_a_later_run_reports_the_cutover_in_the_report(runner, plan_file, geolens):
    _edit_plan(plan_file, (A2,))
    service = FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    result, _ = _migrate(runner, plan_file, "--cutover")
    assert result.exit_code == 0, result.output
    FakeRefresh(geolens, service).allow(PARCELS)

    _migrate(runner, plan_file)

    report = (plan_file.parent / "arcgis-migration-report.md").read_text()
    assert "**Cut over** at" in report


_ORG = "ExAmPlEoRg0123"
_ADMIN = {"id": _ORG, "user": {"username": "gis_admin", "role": "org_admin"}}


class _SearchPortal:
    def __init__(self, answer, token: str | None = "t", self_info=_ADMIN) -> None:
        self.answer = answer
        self.token = token
        self.self_info = self_info
        self.asked: list[tuple[str, dict]] = []

    def get_json(self, path, params=None):
        self.asked.append((path, dict(params or {})))
        if path == "portals/self":
            return self.self_info
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


_READ_AT = "2026-10-01T00:00:00Z"
_NOW = datetime(2026, 10, 11, tzinfo=UTC)
_PLAN = {
    "inventory": {
        "started_at": _READ_AT,
        # Read for an hour: an item changed meanwhile is after the start.
        "generated_at": "2026-10-01T01:00:00Z",
        "scope": {"mode": "org", "owner": None, "org_id": _ORG},
    }
}


@pytest.mark.parametrize(
    ("client", "says"),
    [
        (_SearchPortal({"results": [{"modified": 1791000000000}]}), "changed after"),
        # Changed while the inventory ran, after its start, before its end.
        (_SearchPortal({"results": [{"modified": 1790815000000}]}), "changed after"),
        (_SearchPortal({"results": [{"modified": 1759000000000}]}), None),
        # An organization the plan came from has items; none is no answer.
        (_SearchPortal({"results": []}), "found no items of the organization"),
        (_SearchPortal({"results": []}, token=None), "no ArcGIS credential"),
        (None, "no ArcGIS credential"),
        (_SearchPortal(PortalError("boom", kind="server")), "couldn't check"),
        (_SearchPortal({"error": "nope"}), "couldn't check"),
        (_SearchPortal({"results": [{}]}), "couldn't check"),
        (_SearchPortal({"results": [{"modified": None}]}), "couldn't check"),
        (_SearchPortal({"results": [{"modified": "1791000000000"}]}), "couldn't check"),
        (_SearchPortal({"results": [{"modified": True}]}), "couldn't check"),
        (_SearchPortal({"results": ["item"]}), "couldn't check"),
    ],
)
def test_cutover_asks_the_portal_for_items_changed_since_the_inventory(client, says):
    reason = cutover_mod.inventory_changes(client, _PLAN, _NOW)

    if says is None:
        assert reason is None
    else:
        assert says in reason and "10 days ago" in reason
    if isinstance(client, _SearchPortal) and client.token:
        [(_self, _), (path, params)] = client.asked
        assert path == "search" and params["q"] == "orgid:ExAmPlEoRg0123"
        assert params["sortField"] == "modified" and params["num"] == 1


def test_a_portal_changed_since_the_inventory_refuses_cutover(
    runner, plan_file, geolens, monkeypatch
):
    _edit_plan(plan_file, (A2,))
    FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    seen = []

    def changed(client, plan, now):
        seen.append(client)
        return "portal items changed after the inventory was read 3 days ago"

    monkeypatch.setattr(migrate_mod, "inventory_changes", changed)
    token = secrets.token_urlsafe(16)

    result, payload = _migrate(runner, plan_file, "--cutover", "--token", token)

    assert result.exit_code == 1
    assert payload["cutover"]["refused"] == ["incomplete-inventory"]
    [check] = payload["cutover"]["checks"]
    assert "3 days ago" in check["items"][0]["reason"]
    # The search goes out with the run's credential, though no item needs it.
    [client] = seen
    assert client.token == token
    assert _state(plan_file)["cutover"] is None


def _set_row(plan_file: Path, item_id: str, **row) -> None:
    path = plan_file.parent / "arcgis-inventory.json"
    inventory = json.loads(path.read_text())
    for found in inventory["items"]:
        if found["id"] == item_id:
            found.update(row)
    path.write_text(json.dumps(inventory))


def _refused_for(payload, item_id: str, says: str) -> None:
    assert payload["cutover"]["refused"] == ["unfinished-items"]
    [check] = payload["cutover"]["checks"]
    assert any(
        found["item"] == item_id and says in found["reason"] for found in check["items"]
    ), check


@pytest.mark.parametrize(
    ("damage", "says"),
    [("deleted", "deleted in GeoLens"), ("no_url", "no service URL")],
)
def test_a_service_item_cutover_cant_bring_up_to_date_is_refused(
    runner, plan_file, geolens, damage, says
):
    _edit_plan(plan_file, (A2,))
    service = FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    _migrate(runner, plan_file)
    FakeRefresh(geolens, service).allow(PARCELS)
    if damage == "deleted":
        geolens.routes.pop(f"GET /datasets/{PARCELS}")
    else:
        _set_row(plan_file, A2, url=None)

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    assert says in payload["not_up_to_date"][A2][0]
    _refused_for(payload, A2, says)


@pytest.mark.parametrize(
    ("damage", "says"),
    [("gone", "not in the inventory"), ("too_big", "over the instance's upload limit")],
)
def test_a_file_item_cutover_cant_bring_up_to_date_is_refused(
    runner, tmp_path, geolens, portal, damage, says
):
    files.FakeFiles(geolens)
    plan_file = files._plan(tmp_path)
    _edit_plan(plan_file, (D3,))
    result, _ = _migrate(runner, plan_file)
    assert result.exit_code == 0, result.output
    if damage == "gone":
        _set_row(plan_file, D3, type="Shapefile Package")
        plan = json.loads(plan_file.read_text())
        for item in plan["items"]:
            if item["id"] == D3:
                item["type"] = "Shapefile Package"
        plan_file.write_text(json.dumps(plan))
    else:
        _set_row(plan_file, D3, size_bytes=10**12)

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    assert says in payload["not_up_to_date"][D3][0]
    _refused_for(payload, D3, says)


def test_an_inventory_without_a_start_time_refuses_the_freshness_check():
    plan = {"inventory": {**_PLAN["inventory"]}}
    del plan["inventory"]["started_at"]
    client = _SearchPortal({"results": []})

    reason = cutover_mod.inventory_changes(client, plan, _NOW)

    assert (
        "records no start time" in reason and "run inventory and plan again" in reason
    )
    assert client.asked == []


def test_a_plan_carries_the_start_time_of_the_inventory_it_was_merged_from(
    runner, tmp_path
):
    from geolens_cli import arcgis_plan as plan_mod

    from .arcgis_fake import inventory_report

    report = inventory_report()
    assert report["started_at"] == "2026-09-30T23:00:00Z"
    plan = plan_mod.build_plan(report, inventory_path="i.json", owner_map={})
    assert plan["inventory"]["started_at"] == "2026-09-30T23:00:00Z"
    newer = {**report, "started_at": "2026-10-05T00:00:00Z"}
    merged, _ = plan_mod.merge_plan(
        plan,
        plan_mod.build_plan(newer, inventory_path="i.json", owner_map={}),
        newer,
    )
    assert merged["inventory"]["started_at"] == "2026-10-05T00:00:00Z"


@pytest.mark.parametrize(
    ("user", "searched"),
    [
        ({"username": "u", "role": "org_publisher"}, False),
        (
            {
                "username": "u",
                "role": "org_user",
                "privileges": ["portal:user:joinGroup"],
            },
            False,
        ),
        (None, False),
        (
            {
                "username": "u",
                "role": "org_user",
                "privileges": ["portal:admin:viewItems"],
            },
            True,
        ),
    ],
)
def test_the_freshness_search_needs_an_org_admin_account(user, searched):
    client = _SearchPortal(
        {"results": [{"modified": 1759000000000}]},
        self_info={"id": _ORG, "user": user} if user else {"id": _ORG},
    )

    reason = cutover_mod.inventory_changes(client, _PLAN, _NOW)

    assert [path for path, _ in client.asked][1:] == (["search"] if searched else [])
    if searched:
        assert reason is None
    else:
        assert "isn't an organization administrator (org_admin)" in reason


@pytest.mark.parametrize("own", ["OtherOrg9876", None])
def test_the_freshness_search_needs_an_account_of_the_plans_org(own):
    client = _SearchPortal(
        {"results": [{"modified": 1759000000000}]},
        self_info={**_ADMIN, "id": own},
    )

    reason = cutover_mod.inventory_changes(client, _PLAN, _NOW)

    assert [path for path, _ in client.asked] == ["portals/self"]
    assert reason.endswith(
        f"belongs to organization {own or 'unknown'}, not the plan's organization "
        f"{_ORG}"
    )


@pytest.mark.parametrize("date", [None, "not a date"])
def test_an_inventory_without_a_portal_time_records_no_start(monkeypatch, date):
    from geolens_cli import arcgis_plan as plan_mod

    from . import arcgis_fake

    monkeypatch.setattr(arcgis_fake, "PORTAL_DATE", date)
    report = arcgis_fake.inventory_report()

    assert "started_at" not in report and report["started_at_local"]
    plan = plan_mod.build_plan(report, inventory_path="i.json", owner_map={})
    reason = cutover_mod.inventory_changes(_SearchPortal({"results": []}), plan, _NOW)
    assert "no start time by the portal's clock" in reason


def test_the_inventory_start_is_the_portals_clock_not_the_hosts():
    from .arcgis_fake import inventory_report

    report = inventory_report()

    assert report["started_at"] == "2026-09-30T23:00:00Z"
    assert report["started_at_local"] == "2026-09-30T23:00:05Z"


# Fail closed: a check that can't read what it compares refuses.


@pytest.mark.parametrize("started_at", ["yesterday", "2026-10-01T00:00:00", 17])
def test_an_unusable_inventory_start_refuses_the_freshness_check(started_at):
    plan = {"inventory": {**_PLAN["inventory"], "started_at": started_at}}
    client = _SearchPortal({"results": [{"modified": 1759000000000}]})

    reason = cutover_mod.inventory_changes(client, plan, _NOW)

    assert "records no start time" in reason and client.asked == []


def test_a_probe_that_lists_no_layers_is_not_taken_as_unchanged(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    service.layers.clear()

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert payload["not_up_to_date"][A2] == [
        "couldn't check the service's layers: its probe listed none"
    ]
    assert refresh.bodies == []


@pytest.mark.parametrize("finished_at", [None, "not a time", "2026-10-02T12:00:00"])
def test_an_unusable_finish_time_in_an_old_state_is_not_trusted(
    runner, plan_file, geolens, finished_at
):
    service = _migrated(runner, plan_file, geolens)
    _edit_state(plan_file, A2, last_update={}, finished_at=finished_at)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert refresh.bodies == []
    assert (
        "changed in GeoLens since it was migrated" in (payload["not_up_to_date"][A2][0])
    )


@pytest.mark.parametrize(
    ("marker", "fields"),
    [
        # A bool is not a revision, though True == 1.
        ({"revision": True}, {"data_revision": 1}),
        # An owner recorded as none must still be none.
        ({"revision": 0, "owner": None}, {}),
    ],
)
def test_a_recovered_run_is_adopted_only_on_a_matching_record(
    runner, plan_file, geolens, marker, fields
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    run_id = _uuid("5e", "88")
    refresh.runs[PARCELS] = [_run(PARCELS, run_id, "succeeded")]
    _edit_state(
        plan_file,
        A2,
        refreshing={PARCELS: {"run": run_id, "by": layers.OPERATOR, **marker}},
    )
    service.fields.setdefault(PARCELS, {}).update({"updated_at": LATER, **fields})

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert refresh.bodies == []
    assert "changed in GeoLens" in payload["not_up_to_date"][A2][0]


def test_a_multi_layer_file_whose_previews_list_no_layers_is_reported(
    runner, tmp_path, geolens, portal
):
    files.FakeFiles(geolens, layer_names=["Roads", "Parcels"])
    plan_file = files._plan(tmp_path)
    result, _ = _migrate(runner, plan_file, "--only", D3)
    assert result.exit_code == 0, result.output
    datasets = _state(plan_file)["items"][D3]["dataset_ids"]
    for n, dataset in enumerate(datasets):
        job = _uuid("0c", f"{n:02d}")
        geolens.routes.update(
            {
                f"POST /datasets/{dataset}/reupload": (
                    201,
                    {"job_id": job, "message": "ok", "status": "pending"},
                ),
                f"POST /datasets/{dataset}/reupload/{job}/preview": _preview(job),
                f"POST /datasets/{dataset}/reupload/{job}/commit": (
                    202,
                    {"job_id": job, "status": "pending", "message": "queued"},
                ),
                f"GET /datasets/{dataset}/refresh-runs": {
                    "runs": [
                        _run(
                            dataset,
                            _uuid("5e", f"{n:02d}"),
                            "succeeded",
                            ingest_job_id=job,
                        )
                    ],
                    "total": 1,
                },
            }
        )

    result, payload = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert payload["not_up_to_date"][D3] == [
        "couldn't check the file's layers: its previews listed none"
    ]
