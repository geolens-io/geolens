"""`geolens arcgis migrate` reruns: refresh, replace, GeoLens changes and --cutover."""

from __future__ import annotations

import json
import secrets
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from geolens_cli import arcgis_migrate as migrate_mod
from geolens_cli import arcgis_migrate_cutover as cutover_mod
from geolens_cli import arcgis_migrate_refresh as refresh_mod
from geolens_cli.arcgis_item_metadata import CARRIED, MAX_SUMMARY
from geolens_cli.arcgis_portal import PortalError
from geolens_cli.main import app

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
            # The swap is the operator's write and a new version.
            fields = self.service.fields.setdefault(dataset, {})
            fields.update(
                updated_at=LATER,
                updated_by=layers.OPERATOR,
                current_version=fields.get("current_version", 1) + 1,
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


def test_a_refresh_that_reads_no_relationships_keeps_the_recorded_ones(
    runner, plan_file, geolens
):
    classes = [{"related_layer_id": 1, "role": "Origin", "name": "Parcels_Owners"}]
    service = FakeImport(
        geolens, [_layer(0, "Parcels", has_attachments=False, relationships=classes)]
    )
    _migrate(runner, plan_file, "--only", A2)
    assert _state(plan_file)["items"][A2]["relationships"]["0"]
    # A failed optional /layers read reports no relationships at all.
    service.layers[0].pop("relationships")
    FakeRefresh(geolens, service).allow(PARCELS)

    result, _payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    recorded = _state(plan_file)["items"][A2]["relationships"]["0"]
    assert [rel["name"] for rel in recorded] == ["Parcels_Owners"]


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
    ("edit", "named"),
    [
        (
            {"updated_at": EDITED, "updated_by": ALICE},
            "its title, description, sharing or other details were edited; "
            "last changed at 2026-10-03T00:00:00+00:00",
        ),
        # A feature added by the operator's own account moves only the count.
        ({"feature_count": 5}, "its data was edited, 0 features then, 5 now"),
        # An attribute edit by the operator's own account moves only the revision.
        ({"data_revision": 1}, "its data was edited; last changed"),
        # A replacement or restore by the operator's own account moves only the
        # version.
        ({"current_version": 2}, "its data was replaced or restored; last changed"),
    ],
)
def test_a_dataset_changed_in_geolens_since_the_last_run_is_left_alone(
    runner, plan_file, geolens, edit, named
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
    assert f"changed in GeoLens since the last run ({named}" in reason
    assert "Its portal item was last modified at 2026-" in reason
    assert reason.endswith(
        "To keep the GeoLens version, set the item's action to skip in the plan, "
        "or accept it at cutover with --accept-unfinished-items"
    )
    entry = _state(plan_file)["items"][A2]
    assert entry["last_update"][PARCELS] == {
        "updated_at": "2026-10-01T00:00:00+00:00",
        "feature_count": 0,
        "data_revision": 0,
        "current_version": 1,
        "source_url": None,
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


def test_a_run_blocked_after_polling_ended_follows_its_accepted_successor(
    runner, plan_file, geolens, monkeypatch
):
    monkeypatch.setattr(refresh_mod, "JOB_TIMEOUT", 0.05)
    monkeypatch.setattr(refresh_mod, "JOB_POLL_INTERVAL", 0.01)
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service, outcome="running").allow(PARCELS)
    _migrate(runner, plan_file, "--only", A2)
    [run] = refresh.runs[PARCELS]
    run.update(status="blocked", finished_at=LATER)
    refresh.runs[PARCELS].insert(
        0,
        _run(
            PARCELS,
            _uuid("8e", "02"),
            "succeeded",
            triggered_by=ALICE,
            verification={"accepted_blocked_run_id": run["id"], "data_revision": 1},
        ),
    )
    run["verification"] = {"acceptance_consumed_by_run_id": _uuid("8e", "02")}
    service.fields.setdefault(PARCELS, {}).update(
        {"updated_at": LATER, "updated_by": ALICE, "data_revision": 1}
    )
    refresh.outcome = "succeeded"

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert payload["not_up_to_date"] == {}


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


def test_an_acceptance_blocked_again_is_followed_to_the_run_that_published(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service, outcome="blocked").allow(PARCELS)
    refresh.extra = {"verification": {"review_reasons": ["live_data_changed"]}}
    _migrate(runner, plan_file, "--only", A2)
    [first] = refresh.runs[PARCELS]
    again = _run(
        PARCELS, _uuid("8e", "01"), "blocked", triggered_by=ALICE, verification={}
    )
    first["verification"]["acceptance_consumed_by_run_id"] = again["id"]
    refresh.runs[PARCELS].insert(0, again)

    held, payload = _migrate(runner, plan_file, "--only", A2)

    assert held.exit_code == 1
    assert f"--accept-blocked-run {again['id']}" in payload["not_up_to_date"][A2][0]
    published = _run(
        PARCELS,
        _uuid("8e", "02"),
        "succeeded",
        triggered_by=ALICE,
        verification={"accepted_blocked_run_id": again["id"], "data_revision": 1},
    )
    again["verification"]["acceptance_consumed_by_run_id"] = published["id"]
    refresh.runs[PARCELS].insert(0, published)
    service.fields.setdefault(PARCELS, {}).update(
        {"updated_at": LATER, "updated_by": ALICE, "data_revision": 1}
    )
    refresh.outcome = "succeeded"

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert payload["not_up_to_date"] == {}


def test_a_blocked_run_nobody_accepted_keeps_its_marker(runner, plan_file, geolens):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service, outcome="blocked").allow(PARCELS)
    refresh.extra = {"verification": {"review_reasons": ["schema_changed"]}}
    _migrate(runner, plan_file, "--only", A2)
    [blocked] = refresh.runs[PARCELS]

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert f"--accept-blocked-run {blocked['id']}" in payload["not_up_to_date"][A2][0]
    assert len(refresh.bodies) == 1
    [marker] = _state(plan_file)["items"][A2]["refreshing"].values()
    assert marker["blocked"] == blocked["id"]


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
    blocked["verification"]["acceptance_consumed_by_run_id"] = _uuid("8e", "01")
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
def test_a_summary_cleared_in_the_portal_is_cleared_unless_also_edited_in_geolens(
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

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == int(edited), result.output
    entry = _state(plan_file)["items"][A2]
    if edited:
        assert service.summaries[PARCELS] == "Written in GeoLens"
        assert (
            'the summary is "Written in GeoLens" in GeoLens and empty in the portal'
        ) in payload["not_up_to_date"][A2][0]
    else:
        assert service.summaries[PARCELS] is None
        assert entry["metadata_baseline"][PARCELS]["summary"] == ""


def _set_title(plan_file: Path, item_id: str, title: str) -> None:
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == item_id:
            item["title"] = item["target"]["title"] = title
    plan_file.write_text(json.dumps(plan))


@pytest.mark.parametrize("edited", [False, True])
def test_a_portal_rename_retitles_the_dataset_unless_also_edited_in_geolens(
    runner, plan_file, geolens, edited
):
    service = _migrated(runner, plan_file, geolens)
    FakeRefresh(geolens, service).allow(PARCELS)
    first = service.fields[PARCELS]["title"]
    # The rerun that records the title this command left.
    assert _migrate(runner, plan_file, "--only", A2)[0].exit_code == 0
    if edited:
        service.fields[PARCELS]["title"] = "Named in GeoLens"
    _set_title(plan_file, A2, "Parcels renamed")

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == int(edited), result.output
    entry = _state(plan_file)["items"][A2]
    if edited:
        assert service.fields[PARCELS]["title"] == "Named in GeoLens"
        assert (
            'the title is "Named in GeoLens" in GeoLens and "Parcels renamed" in '
            "the portal"
        ) in payload["not_up_to_date"][A2][0]
        assert entry["metadata_baseline"][PARCELS]["title"] == first
    else:
        assert service.fields[PARCELS]["title"] == "Parcels renamed"
        assert entry["metadata_baseline"][PARCELS]["title"] == "Parcels renamed"


def test_a_decomposed_portal_title_is_recorded_as_geolens_stores_it(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    FakeRefresh(geolens, service).allow(PARCELS)
    assert _migrate(runner, plan_file, "--only", A2)[0].exit_code == 0
    _set_title(plan_file, A2, "Cafe\u0301 parcels")
    assert _migrate(runner, plan_file, "--only", A2)[0].exit_code == 0
    # GeoLens stores titles NFC-normalized.
    service.fields[PARCELS]["title"] = "Caf\u00e9 parcels"
    _set_title(plan_file, A2, "Parcels renamed")

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert service.fields[PARCELS]["title"] == "Parcels renamed"


def test_an_empty_title_baseline_an_older_cli_recorded_is_adopted(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    FakeRefresh(geolens, service).allow(PARCELS)
    assert _migrate(runner, plan_file, "--only", A2)[0].exit_code == 0
    # An older CLI empties fields the portal no longer gives; GeoLens ignores a
    # null title, so only the baseline changes.
    baseline = _state(plan_file)["items"][A2]["metadata_baseline"]
    baseline[PARCELS]["title"] = ""
    _edit_state(plan_file, A2, metadata_baseline=baseline)
    _set_title(plan_file, A2, "Parcels renamed")

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    assert service.fields[PARCELS]["title"] == "Parcels renamed"


def test_a_metadata_write_whose_keywords_fail_is_still_recorded_as_this_commands(
    runner, plan_file, geolens
):
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    assert _migrate(runner, plan_file, "--only", A2)[0].exit_code == 0
    patch = geolens.routes[f"PATCH /datasets/{PARCELS}"]

    def stamped(seen):
        # GeoLens moves updated_at on every metadata write.
        service.fields[PARCELS]["updated_at"] = EDITED
        return patch(seen)

    geolens.routes[f"PATCH /datasets/{PARCELS}"] = stamped
    keywords = f"POST /records/{PARCELS}/keywords/"
    add = geolens.routes[keywords]
    geolens.routes[keywords] = (500, layers._problem(500, "boom"))
    _set_title(plan_file, A2, "Parcels renamed")
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == A2:
            item["target"]["tags"].append("renamed")
    plan_file.write_text(json.dumps(plan))
    result, payload = _migrate(runner, plan_file, "--only", A2)
    assert result.exit_code == 1
    assert "writing the item metadata failed" in payload["not_up_to_date"][A2][0]
    assert service.fields[PARCELS]["title"] == "Parcels renamed"
    geolens.routes[keywords] = add

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, payload["not_up_to_date"]
    assert len(refresh.bodies) == 3


def _edited_on_both_sides(
    runner,
    tmp_path,
    geolens,
    portal_title: str | None,
    geolens_title: str = "Named in GeoLens",
    item: str = A2,
    *args: str,
):
    """A migrated *item* retitled in GeoLens, then given a new portal snippet
    and, with *portal_title*, a new portal title."""
    plan_file = _write_plan(tmp_path, rows={item: {"snippet": "Old summary"}})
    service = _migrated(runner, plan_file, geolens, item, *args)
    if item == A1:
        service.fields.setdefault(PARCELS, {}).update(
            {"origin_ref": {"url": _service_url(plan_file, A1)}}
        )
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    # The rerun that records the title this command left.
    assert _migrate(runner, plan_file, "--only", item, *args)[0].exit_code == 0
    service.fields[PARCELS].update(
        title=geolens_title, updated_at=EDITED, updated_by=ALICE
    )
    _set_snippet(plan_file, item, "New summary")
    if portal_title:
        _set_title(plan_file, item, portal_title)
    return plan_file, service, refresh


MERGED = (
    f"dataset {PARCELS} was edited in GeoLens; merged its metadata: the summary "
    "from the portal, the title from GeoLens"
)
BOTH_TITLES = (
    'the title is "Named in GeoLens" in GeoLens and "Parcels renamed" in the portal'
)


def _merged_as_edited(service) -> None:
    assert service.fields[PARCELS]["title"] == "Named in GeoLens"
    assert service.summaries[PARCELS].startswith("New summary")


def test_edits_to_different_fields_on_each_side_are_merged(runner, tmp_path, geolens):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, payload["not_up_to_date"]
    assert len(refresh.bodies) == 2
    _merged_as_edited(service)
    assert payload["metadata_merged"] == {A2: [MERGED]}
    assert MERGED in _state(plan_file)["items"][A2]["notes"]
    report = (plan_file.parent / "arcgis-migration-report.json").read_text()
    assert MERGED in report


def test_a_field_changed_on_both_sides_stops_with_both_values(
    runner, tmp_path, geolens
):
    plan_file, service, refresh = _edited_on_both_sides(
        runner, tmp_path, geolens, "Parcels renamed"
    )
    before = len(geolens.seen)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert len(refresh.bodies) == 1
    assert [s for s in geolens.seen[before:] if s.method not in ("GET", "POST")] == []
    assert service.fields[PARCELS]["title"] == "Named in GeoLens"
    [reason] = payload["not_up_to_date"][A2]
    assert f"both sides changed the same fields: {BOTH_TITLES}" in reason
    assert reason.endswith(refresh_mod.MAKE_EQUAL + refresh_mod.KEEP_GEOLENS)
    assert payload["metadata_merged"] == {}


def test_a_dataset_without_a_metadata_baseline_stops_as_before(
    runner, tmp_path, geolens
):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    _edit_state(plan_file, A2, metadata_baseline={})

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert len(refresh.bodies) == 1
    [reason] = payload["not_up_to_date"][A2]
    assert reason.startswith(
        f"dataset {PARCELS}: changed in GeoLens since the last run"
    )
    assert reason.endswith(refresh_mod.KEEP_GEOLENS)
    assert service.fields[PARCELS]["title"] == "Named in GeoLens"


def test_a_title_with_no_recorded_value_counts_as_changed_on_both_sides(
    runner, tmp_path, geolens
):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    baseline = _state(plan_file)["items"][A2]["metadata_baseline"]
    del baseline[PARCELS]["title"]
    _edit_state(plan_file, A2, metadata_baseline=baseline)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert len(refresh.bodies) == 1
    assert (
        'the title is "Named in GeoLens" in GeoLens'
        in (payload["not_up_to_date"][A2][0])
    )


@pytest.mark.parametrize(
    "edit",
    [
        {"data_revision": 1},
        # A replacement keeping the feature count, and a restore after it.
        {"current_version": 3},
        {"current_version": 4, "feature_count": 0},
        {"created_by": ALICE},
    ],
    ids=["feature-edit", "replacement", "restore", "owner"],
)
def test_a_data_or_owner_change_in_geolens_still_stops(runner, tmp_path, geolens, edit):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    service.fields[PARCELS].update(edit)

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert len(refresh.bodies) == 1
    assert service.fields[PARCELS]["title"] == "Named in GeoLens"
    assert payload["not_up_to_date"][A2][0].endswith(refresh_mod.KEEP_GEOLENS)
    assert payload["metadata_merged"] == {}


def test_a_snapshot_recorded_without_its_version_stops_as_before(
    runner, tmp_path, geolens
):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    entry = _state(plan_file)["items"][A2]
    del entry["last_update"][PARCELS]["current_version"]
    _edit_state(plan_file, A2, last_update=entry["last_update"])

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert len(refresh.bodies) == 1
    assert payload["not_up_to_date"][A2][0].endswith(refresh_mod.KEEP_GEOLENS)


def test_a_snapshot_recorded_without_its_version_still_refreshes_when_unchanged(
    runner, tmp_path, geolens
):
    plan_file = _write_plan(tmp_path, rows={A2: {"snippet": "Old summary"}})
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    entry = _state(plan_file)["items"][A2]
    del entry["last_update"][PARCELS]["current_version"]
    _edit_state(plan_file, A2, last_update=entry["last_update"])

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, payload["not_up_to_date"]
    assert len(refresh.bodies) == 1


def test_a_field_filled_in_geolens_with_no_recorded_value_counts_as_both(
    runner, tmp_path, geolens
):
    plan_file = _write_plan(tmp_path, rows={A2: {"snippet": None}})
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    assert _migrate(runner, plan_file, "--only", A2)[0].exit_code == 0
    assert "summary" not in _state(plan_file)["items"][A2]["metadata_baseline"][PARCELS]
    service.summaries[PARCELS] = "Filled in GeoLens"
    service.fields[PARCELS].update(
        title="Named in GeoLens", updated_at=EDITED, updated_by=ALICE
    )

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert len(refresh.bodies) == 1
    assert (
        'the summary is "Filled in GeoLens" in GeoLens and empty in the portal'
    ) in payload["not_up_to_date"][A2][0]


def test_a_field_filled_in_geolens_over_a_recorded_empty_value_is_kept(
    runner, tmp_path, geolens
):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    baseline = _state(plan_file)["items"][A2]["metadata_baseline"]
    baseline[PARCELS]["attribution"] = ""
    _edit_state(plan_file, A2, metadata_baseline=baseline)
    service.fields[PARCELS]["attribution"] = "Credit added in GeoLens"

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, payload["not_up_to_date"]
    assert service.fields[PARCELS]["attribution"] == "Credit added in GeoLens"
    assert payload["metadata_merged"] == {
        A2: [
            MERGED.replace(
                "the title from GeoLens",
                "the title from GeoLens, the attribution from GeoLens",
            )
        ]
    }


# Where each carried field's portal value comes from: an inventory row key,
# the inventory's portal record, or the plan item's title.
_PORTAL_SOURCES = {
    "summary": ("row", ("snippet", "description")),
    "attribution": ("row", ("access_information",)),
    "license": ("row", ("license_info",)),
    "source_organization": ("portal", ("name",)),
    "title": ("plan", ()),
}


def _set_portal_value(plan_file: Path, name: str, value: str | None) -> None:
    where, keys = _PORTAL_SOURCES[name]
    if where == "plan":
        _set_title(plan_file, A2, value)
        return
    path = plan_file.parent / "arcgis-inventory.json"
    inventory = json.loads(path.read_text())
    target = (
        inventory["portal"]
        if where == "portal"
        else next(row for row in inventory["items"] if row["id"] == A2)
    )
    for key in keys:
        target[key] = None
    target[keys[0]] = value
    path.write_text(json.dumps(inventory))


def _set_geolens_value(service, name: str, value: str) -> None:
    if name == "summary":
        service.summaries[PARCELS] = value
    else:
        service.fields[PARCELS][name] = value


def _geolens_value(service, name: str):
    if name == "summary":
        return service.summaries.get(PARCELS)
    return service.fields[PARCELS].get(name)


def _every_field_recorded(runner, tmp_path, geolens):
    plan_file = _write_plan(
        tmp_path,
        rows={
            A2: {
                "snippet": "Old summary",
                "access_information": "Old credit",
                "license_info": "Old license",
            }
        },
        portal={"name": "Old organization"},
    )
    service = _migrated(runner, plan_file, geolens)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    assert _migrate(runner, plan_file, "--only", A2)[0].exit_code == 0
    return plan_file, service, refresh


@pytest.mark.parametrize("portal", ["unchanged", "changed", "emptied"])
@pytest.mark.parametrize("name", CARRIED)
def test_a_value_changed_in_geolens_is_never_overwritten(
    runner, tmp_path, geolens, name, portal
):
    if name == "title" and portal == "emptied":
        pytest.skip("a title is never emptied")
    plan_file, service, refresh = _every_field_recorded(runner, tmp_path, geolens)
    _set_geolens_value(service, name, "Edited in GeoLens")
    service.fields[PARCELS].update(updated_at=EDITED, updated_by=ALICE)
    if portal != "unchanged":
        _set_portal_value(
            plan_file, name, "From the portal" if portal == "changed" else None
        )

    for args in ((), ("--dry-run",), ()):
        result, payload = _migrate(runner, plan_file, "--only", A2, *args)

        assert result.exit_code == int(portal != "unchanged"), payload
        assert _geolens_value(service, name) == "Edited in GeoLens"


def test_a_failed_metadata_write_is_merged_again_by_the_next_run(
    runner, tmp_path, geolens
):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    route = f"PATCH /datasets/{PARCELS}"
    patch = geolens.routes[route]
    geolens.routes[route] = (500, layers._problem(500, "boom"))

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert "writing the item metadata failed" in payload["not_up_to_date"][A2][0]
    assert payload["metadata_merged"] == {}
    assert service.fields[PARCELS]["title"] == "Named in GeoLens"
    geolens.routes[route] = patch

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, payload["not_up_to_date"]
    _merged_as_edited(service)
    assert payload["metadata_merged"] == {A2: [MERGED]}


def test_a_refresh_an_earlier_run_left_running_is_adopted_and_merged(
    runner, tmp_path, geolens, monkeypatch
):
    monkeypatch.setattr(refresh_mod, "JOB_TIMEOUT", 0.05)
    monkeypatch.setattr(refresh_mod, "JOB_POLL_INTERVAL", 0.01)
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    refresh.outcome = "running"

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert "still running" in payload["not_up_to_date"][A2][0]
    refresh.runs[PARCELS][0].update(status="succeeded", finished_at=LATER)
    service.fields[PARCELS].update(
        updated_at="2026-10-04T00:00:00Z", updated_by=layers.OPERATOR, current_version=3
    )
    refresh.outcome = "succeeded"

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, payload["not_up_to_date"]
    _merged_as_edited(service)
    assert payload["metadata_merged"] == {A2: [MERGED]}


def test_a_merge_whose_write_answer_was_lost_is_recorded_once_both_sides_agree(
    runner, tmp_path, geolens
):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    route = f"PATCH /datasets/{PARCELS}"
    patch = geolens.routes[route]

    def committed_then_lost(seen):
        patch(seen)
        return (502, layers._problem(502, "bad gateway"))

    geolens.routes[route] = committed_then_lost
    assert _migrate(runner, plan_file, "--only", A2)[0].exit_code == 1
    _merged_as_edited(service)
    geolens.routes[route] = patch

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, payload["not_up_to_date"]
    _merged_as_edited(service)
    baseline = _state(plan_file)["items"][A2]["metadata_baseline"][PARCELS]
    assert baseline["summary"].startswith("New summary")
    _set_snippet(plan_file, A2, "Newer summary")

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, payload["not_up_to_date"]
    assert service.summaries[PARCELS] == "Newer summary"
    assert service.fields[PARCELS]["title"] == "Named in GeoLens"


@pytest.mark.parametrize("write", ["visibility", "metadata"])
def test_a_run_stopped_right_after_a_write_is_merged_by_the_next(
    runner, tmp_path, geolens, write
):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    if write == "visibility":
        _set_visibility(plan_file, A2, "internal")
    route = f"PATCH /datasets/{PARCELS}"
    patch = geolens.routes[route]

    def landed_then_stopped(seen):
        # GeoLens moves updated_at on every metadata write.
        service.fields[PARCELS]["updated_at"] = "2026-10-05T00:00:00Z"
        answer = patch(seen)
        if (write == "visibility") is ("visibility" in seen.json()):
            raise KeyboardInterrupt
        return answer

    geolens.routes[route] = landed_then_stopped
    assert _migrate(runner, plan_file, "--only", A2)[0].exit_code == 130
    geolens.routes[route] = patch

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, payload["not_up_to_date"]
    _merged_as_edited(service)
    [line] = payload["metadata_merged"][A2]
    assert line.startswith(f"dataset {PARCELS} was edited in GeoLens; merged")


@pytest.mark.parametrize("dry_run", [False, True], ids=["run", "dry-run"])
@pytest.mark.parametrize(
    "form",
    ["--token", "ARCGIS_TOKEN", "--token-stdin", "ARCGIS_PASSWORD", "--password-stdin"],
)
def test_every_credential_form_is_kept_out_of_a_public_runs_output(
    runner, tmp_path, geolens, form, dry_run
):
    secret = secrets.token_urlsafe(40) + "\\" + secrets.token_urlsafe(8)
    plan_file, service, refresh = _edited_on_both_sides(
        runner, tmp_path, geolens, "Parcels renamed", f"Named {secret}"
    )
    args = ["arcgis", "migrate", str(plan_file), "--only", A2]
    env, stdin = {}, None
    if form == "--token":
        args += ["--token", secret]
    elif form == "ARCGIS_TOKEN":
        env["ARCGIS_TOKEN"] = secret
    elif form == "--token-stdin":
        args.append("--token-stdin")
        stdin = secret + "\n"
    elif form == "ARCGIS_PASSWORD":
        args += ["--username", "gis_admin"]
        env["ARCGIS_PASSWORD"] = secret
    else:
        args += ["--username", "gis_admin", "--password-stdin"]
        stdin = secret + "\n"
    if dry_run:
        args.append("--dry-run")

    human = runner.invoke(app, args, env=env, input=stdin)
    data = runner.invoke(app, ["--json", *args], env=env, input=stdin)

    assert human.exit_code == 1 and data.exit_code == 1, human.output
    reason = json.loads(data.stdout)["not_up_to_date"][A2][0]
    assert 'the title is "Named [REDACTED]" in GeoLens' in reason
    files = [path for path in plan_file.parent.rglob("*") if path.is_file()]
    if not dry_run:
        assert {p.name for p in files} >= {
            "arcgis-migration-state.json",
            "arcgis-migration-report.json",
            "arcgis-migration-report.md",
        }
    _assert_kept_out([human.output, data.output], files, secret)


def _secret_pieces(secret: str) -> tuple[str, ...]:
    return (secret, secret[:24], secret.split("\\")[0], json.dumps(secret)[1:-1])


def _assert_kept_out(outputs: list[str], files: list[Path], *pieces: str) -> None:
    sinks = outputs + [path.read_text(errors="replace") for path in files]
    for secret in pieces:
        for piece in _secret_pieces(secret):
            assert not any(piece in sink for sink in sinks), piece


def _run_and_dry_run(runner, plan_file: Path, *args: str, env=None):
    base = ["arcgis", "migrate", str(plan_file), "--only", A2, *args]
    runs = [
        runner.invoke(app, [*prefix, *base, *suffix], env=env)
        for prefix in ([], ["--json"])
        for suffix in ([], ["--dry-run"])
    ]
    # The plan and inventory are the inputs that hold the portal's values.
    inputs = {plan_file.name, "arcgis-inventory.json"}
    files = [
        path
        for path in plan_file.parent.rglob("*")
        if path.is_file() and path.name not in inputs
    ]
    return runs, files


def test_a_portal_value_whose_credential_is_cut_at_a_length_limit_is_not_written(
    runner, tmp_path, geolens
):
    secret = secrets.token_urlsafe(40)
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    # The summary limit falls inside the token, so only its start would be kept.
    cut = MAX_SUMMARY - 12
    _set_snippet(plan_file, A2, "x" * cut + secret)

    runs, files = _run_and_dry_run(runner, plan_file, "--token", secret)

    assert [r.exit_code for r in runs] == [1, 1, 1, 1], runs[0].output
    reason = json.loads(runs[2].stdout)["not_up_to_date"][A2][0]
    assert "the portal's summary holds a credential, so it isn't written" in reason
    assert service.summaries[PARCELS] == "Old summary"
    assert len(refresh.bodies) == 1
    _assert_kept_out([r.output for r in runs], files, secret[:12])


def test_a_decomposed_password_is_kept_out_of_a_conflict_and_never_written(
    runner, tmp_path, geolens
):
    password = unicodedata.normalize("NFD", "Pässwörd-" + secrets.token_urlsafe(16))
    composed = unicodedata.normalize("NFC", password)
    plan_file, service, refresh = _edited_on_both_sides(
        runner, tmp_path, geolens, f"Renamed {password}", f"Named {composed}"
    )
    env = {"ARCGIS_PASSWORD": password}

    runs, files = _run_and_dry_run(
        runner, plan_file, "--username", "gis_admin", env=env
    )

    assert [r.exit_code for r in runs] == [1, 1, 1, 1], runs[0].output
    reason = json.loads(runs[2].stdout)["not_up_to_date"][A2][0]
    assert (
        'the title is "Named [REDACTED]" in GeoLens and a value that holds a '
        "credential in the portal"
    ) in reason
    assert service.fields[PARCELS]["title"] == f"Named {composed}"
    _assert_kept_out([r.output for r in runs], files, password, composed)


def test_a_json_valued_portal_field_is_merged_as_any_other(runner, tmp_path, geolens):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    _set_snippet(plan_file, A2, '{"zoning":"R1","lots":[1,2]}')

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, payload["not_up_to_date"]
    assert service.summaries[PARCELS] == '{"zoning":"R1","lots":[1,2]}'
    assert payload["metadata_merged"] == {A2: [MERGED]}


@pytest.mark.parametrize("dry_run", [False, True], ids=["run", "dry-run"])
def test_an_environment_token_is_kept_out_beside_an_explicit_one(
    runner, tmp_path, geolens, dry_run
):
    explicit = secrets.token_urlsafe(30)
    from_env = secrets.token_urlsafe(30)
    plan_file, service, refresh = _edited_on_both_sides(
        runner, tmp_path, geolens, "Parcels renamed", f"Named {from_env} {explicit}"
    )
    args = ["--json", "arcgis", "migrate", str(plan_file), "--only", A2]
    args += ["--token", explicit, *(["--dry-run"] if dry_run else [])]

    result = runner.invoke(app, args, env={"ARCGIS_TOKEN": from_env})

    assert result.exit_code == 1, result.output
    reason = json.loads(result.stdout)["not_up_to_date"][A2][0]
    assert 'the title is "Named [REDACTED] [REDACTED]" in GeoLens' in reason
    files = [path for path in plan_file.parent.rglob("*") if path.is_file()]
    _assert_kept_out([result.output], files, from_env, explicit)


@pytest.mark.parametrize(
    "secret",
    [
        secrets.token_urlsafe(64),
        secrets.token_urlsafe(12) + "\\" + secrets.token_urlsafe(12),
    ],
    ids=["long", "backslash"],
)
def test_a_value_shown_for_a_conflict_never_carries_a_credential(
    runner, tmp_path, geolens, secret
):
    plan_file, service, refresh = _edited_on_both_sides(
        runner,
        tmp_path,
        geolens,
        "Parcels renamed",
        f"Named {secret}",
        A1,
        "--token",
        secret,
    )

    result, payload = _migrate(runner, plan_file, "--only", A1, "--token", secret)
    dry = runner.invoke(
        app,
        [
            *("arcgis", "migrate", str(plan_file), "--only", A1),
            *("--token", secret, "--dry-run"),
        ],
    )

    assert result.exit_code == 1 and dry.exit_code == 1, dry.output
    assert (
        'the title is "Named [REDACTED]" in GeoLens'
        in (payload["not_up_to_date"][A1][0])
    )
    files = [path for path in plan_file.parent.rglob("*") if path.is_file()]
    _assert_kept_out([result.output, dry.output], files, secret)


def test_a_visibility_edited_in_geolens_stops_a_merge(runner, tmp_path, geolens):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    service.fields[PARCELS]["visibility"] = "internal"
    _set_visibility(plan_file, A2, "private")

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert "its visibility was changed to" in payload["not_up_to_date"][A2][0]
    assert service.fields[PARCELS]["title"] == "Named in GeoLens"
    assert payload["metadata_merged"] == {}
    assert len(refresh.bodies) == 1


def test_a_later_portal_edit_to_a_field_kept_from_geolens_stops(
    runner, tmp_path, geolens
):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    assert _migrate(runner, plan_file, "--only", A2)[0].exit_code == 0
    _set_title(plan_file, A2, "Parcels renamed")

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert len(refresh.bodies) == 2
    assert service.fields[PARCELS]["title"] == "Named in GeoLens"
    assert BOTH_TITLES in payload["not_up_to_date"][A2][0]


def test_a_dry_run_shows_the_merge_and_writes_nothing(runner, tmp_path, geolens):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    state_before = (plan_file.parent / "arcgis-migration-state.json").read_text()
    before = len(geolens.seen)

    result, payload = _migrate(runner, plan_file, "--only", A2, "--dry-run")

    assert result.exit_code == 0, result.output
    assert [s for s in geolens.seen[before:] if s.method != "GET"] == []
    assert (plan_file.parent / "arcgis-migration-state.json").read_text() == (
        state_before
    )
    assert service.fields[PARCELS]["title"] == "Named in GeoLens"
    assert payload["metadata_merged"] == {
        A2: [MERGED.replace("; merged", "; would merge")]
    }


def test_a_dry_run_reports_a_field_changed_on_both_sides(runner, tmp_path, geolens):
    plan_file, service, refresh = _edited_on_both_sides(
        runner, tmp_path, geolens, "Parcels renamed"
    )
    _edit_plan(plan_file, (A2,))
    state_before = (plan_file.parent / "arcgis-migration-state.json").read_text()

    result, payload = _migrate(runner, plan_file, "--dry-run")
    cutover, checked = _migrate(runner, plan_file, "--cutover", "--dry-run")

    assert result.exit_code == 1 and cutover.exit_code == 1
    assert BOTH_TITLES in payload["not_up_to_date"][A2][0]
    assert payload["metadata_merged"] == {}
    [check] = [
        c for c in checked["cutover"]["checks"] if c["check"] == "unfinished-items"
    ]
    assert any(BOTH_TITLES in i["reason"] for i in check["items"])
    assert (plan_file.parent / "arcgis-migration-state.json").read_text() == (
        state_before
    )


def test_a_dry_run_replaces_a_recorded_conflict_once_it_is_resolved(
    runner, tmp_path, geolens
):
    plan_file, service, refresh = _edited_on_both_sides(
        runner, tmp_path, geolens, "Parcels renamed"
    )
    original = _state(plan_file)["items"][A2]["metadata_baseline"][PARCELS]["title"]
    _edit_plan(plan_file, (A2,))
    result, payload = _migrate(runner, plan_file)
    assert result.exit_code == 1
    assert BOTH_TITLES in payload["not_up_to_date"][A2][0]
    _set_title(plan_file, A2, original)

    result, payload = _migrate(runner, plan_file, "--dry-run")
    cutover, checked = _migrate(runner, plan_file, "--cutover", "--dry-run")

    assert result.exit_code == 0, payload["not_up_to_date"]
    assert A2 not in payload["not_up_to_date"]
    [line] = payload["metadata_merged"][A2]
    assert "would merge" in line
    unfinished = [
        i
        for c in checked["cutover"]["checks"]
        if c["check"] == "unfinished-items"
        for i in c["items"]
    ]
    assert not [i for i in unfinished if i["item"] == A2], unfinished


def _patch_bodies(geolens) -> str:
    return json.dumps([s.json() for s in geolens.seen if s.method == "PATCH"])


@pytest.mark.parametrize(
    "summary",
    [
        "Authorization: Bearer {secret} [REDACTED]",
        '{{"token": "[REDACTED] {secret}"}}',
    ],
    ids=["header", "json"],
)
def test_a_portal_value_already_holding_a_marker_is_still_refused(
    runner, tmp_path, geolens, summary
):
    secret = secrets.token_urlsafe(40)
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    _set_snippet(plan_file, A2, summary.format(secret=secret))

    result, payload = _migrate(runner, plan_file, "--only", A2, "--token", secret)

    assert result.exit_code == 1
    reason = payload["not_up_to_date"][A2][0]
    assert "the portal's summary holds a credential, so it isn't written" in reason
    assert service.summaries[PARCELS] == "Old summary"
    assert secret not in _patch_bodies(geolens)
    state = (plan_file.parent / "arcgis-migration-state.json").read_text()
    assert secret not in state


def test_a_source_url_edited_in_geolens_stops_a_merge_before_a_refresh(
    runner, tmp_path, geolens
):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    service.fields[PARCELS]["source_url"] = "https://example.test/edited-in-geolens"
    send = geolens.routes[f"POST /datasets/{PARCELS}/refresh"]

    def publishing_changed_data(seen):
        # A refresh that publishes writes the source URL it read from.
        service.fields[PARCELS]["source_url"] = "https://example.test/service/0"
        return send(seen)

    geolens.routes[f"POST /datasets/{PARCELS}/refresh"] = publishing_changed_data

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 1
    assert len(refresh.bodies) == 1
    reason = payload["not_up_to_date"][A2][0]
    assert reason.endswith(refresh_mod.KEEP_GEOLENS)
    assert service.fields[PARCELS]["source_url"] == (
        "https://example.test/edited-in-geolens"
    )
    assert service.fields[PARCELS]["title"] == "Named in GeoLens"


@pytest.mark.parametrize("name", CARRIED)
def test_a_conflict_ends_once_both_sides_hold_the_same_new_value(
    runner, tmp_path, geolens, name
):
    plan_file, service, refresh = _every_field_recorded(runner, tmp_path, geolens)
    _set_geolens_value(service, name, "Edited in GeoLens")
    service.fields[PARCELS].update(updated_at=EDITED, updated_by=ALICE)
    _set_portal_value(plan_file, name, "From the portal")
    assert _migrate(runner, plan_file, "--only", A2)[0].exit_code == 1
    _set_geolens_value(service, name, "Agreed value")
    _set_portal_value(plan_file, name, "Agreed value")

    dry, previewed = _migrate(runner, plan_file, "--only", A2, "--dry-run")
    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert dry.exit_code == 0, previewed["not_up_to_date"]
    assert result.exit_code == 0, payload["not_up_to_date"]
    label = name.replace("_", " ")
    [line] = payload["metadata_merged"][A2]
    assert line.endswith(f"the {label} the same on both sides")
    baseline = _state(plan_file)["items"][A2]["metadata_baseline"][PARCELS]
    assert baseline[name] == "Agreed value"
    _set_portal_value(plan_file, name, "Later from the portal")

    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, payload["not_up_to_date"]
    assert _geolens_value(service, name) == "Later from the portal"


@pytest.mark.parametrize(
    ("flags", "refusal"),
    [
        (["--token-stdin"], "--token-stdin read an empty line"),
        (["--username", "gis_admin", "--password-stdin"], "an empty password"),
    ],
    ids=["token", "password"],
)
def test_an_empty_stdin_line_is_refused_not_skipped(
    runner, plan_file, geolens, flags, refusal
):
    FakeImport(geolens, [_layer(0, "Parcels")], needs_auth=True)
    args = ["arcgis", "migrate", str(plan_file), "--only", A1, *flags]

    result = runner.invoke(app, args, input="\nsecond-line-value\n")

    assert result.exit_code == 2, result.output
    assert refusal in result.output
    assert "second-line-value" not in result.output


def test_a_dry_run_checks_visibility_with_the_sharing_the_run_gives(
    runner, tmp_path, geolens
):
    plan_file, service, refresh = _edited_on_both_sides(runner, tmp_path, geolens, None)
    # Restricted to no mapped group becomes private, which the dataset is; the
    # state can't say who set it, so only a raw plan comparison would refuse.
    _set_visibility(plan_file, A2, "restricted")
    plan = json.loads(plan_file.read_text())
    next(i for i in plan["items"] if i["id"] == A2)["target"]["groups"] = []
    plan_file.write_text(json.dumps(plan))
    service.fields[PARCELS]["visibility"] = "private"
    _edit_state(plan_file, A2, visibility={})

    dry, previewed = _migrate(runner, plan_file, "--only", A2, "--dry-run")
    result, payload = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, payload["not_up_to_date"]
    assert dry.exit_code == 0, previewed["not_up_to_date"]
    assert previewed["metadata_merged"] == {
        A2: [MERGED.replace("; merged", "; would merge")]
    }


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
    _set_title(plan_file, D3, "Inspections renamed")
    before = len(geolens.seen)

    result, payload = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert payload["refreshed"] == [D3] and payload["not_up_to_date"] == {}
    assert [
        s.json()["title"]
        for s in geolens.seen[before:]
        if s.method == "PATCH" and "title" in s.json()
    ] == ["Inspections renamed"]
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
    # A held run is named until someone accepts it.
    reason = "changed in GeoLens" if outcome == "failed" else "--accept-blocked-run"
    assert reason in payload["not_up_to_date"][A2][0]


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
        "current_version": 2,
        "source_url": None,
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
        "current_version": 2,
        "source_url": None,
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


def test_the_loss_report_lists_each_relationship_class_once(runner, plan_file, geolens):
    _edit_plan(plan_file, (A2,))
    relationship = {
        "name": "Parcels_Owners",
        "related_layer_id": 1,
        "cardinality": "OneToMany",
        "role": "Origin",
    }
    FakeImport(
        geolens,
        [
            _layer(0, "Parcels", has_attachments=False, relationships=[relationship]),
            _layer(
                1,
                "Owners",
                "Table",
                has_attachments=False,
                relationships=[
                    {**relationship, "related_layer_id": 0, "role": "Destination"}
                ],
            ),
        ],
    )

    result, _payload = _migrate(runner, plan_file)

    assert result.exit_code == 0, result.output
    report = json.loads((plan_file.parent / "arcgis-migration-report.json").read_text())
    texts = [f["text"] for f in report["follow_ups"] if f["kind"] == "relationships"]
    assert texts == [
        "relationship class Parcels_Owners from layer 0 (origin) to layer 1 "
        "(destination), OneToMany, which GeoLens doesn't import"
    ]


def test_unnamed_relationship_classes_between_the_same_layers_are_listed_apart(
    runner, plan_file, geolens
):
    _edit_plan(plan_file, (A2,))
    classes = [
        {"id": 0, "related_layer_id": 1, "cardinality": "OneToMany", "role": "Origin"},
        {"id": 1, "related_layer_id": 1, "cardinality": "ManyToMany"},
    ]
    FakeImport(
        geolens,
        [
            _layer(0, "Parcels", has_attachments=False, relationships=classes),
            _layer(1, "Owners", "Table", has_attachments=False),
        ],
    )

    result, _payload = _migrate(runner, plan_file)

    assert result.exit_code == 0, result.output
    report = json.loads((plan_file.parent / "arcgis-migration-report.json").read_text())
    texts = [f["text"] for f in report["follow_ups"] if f["kind"] == "relationships"]
    assert texts == [
        "relationship class (unnamed) from layer 0 (origin) to layer 1 "
        "(destination), OneToMany, which GeoLens doesn't import",
        "relationship class (unnamed) between layers 0 and 1, ManyToMany, "
        "which GeoLens doesn't import",
    ]


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
    assert not (plan_file.parent / "arcgis-migration-state.json").exists()

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

    accept = ("--cutover", "--accept-unfinished-items", "--no-retry")
    result, payload = _migrate(runner, plan_file, "--dry-run", *accept)
    assert result.exit_code == 0, result.output
    assert payload["cutover"]["refused"] == [] and payload["failed"] == [A2]

    result, payload = _migrate(runner, plan_file, *accept)
    assert payload["cutover"]["marked"] is True
    # Still failed and reported, but the cutover accepted it.
    assert payload["failed"] == [A2]
    assert result.exit_code == 0, result.output


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


def test_a_refused_cutover_keeps_the_earlier_one_in_the_report(
    runner, plan_file, geolens, monkeypatch
):
    _edit_plan(plan_file, (A2,))
    service = FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    result, _ = _migrate(runner, plan_file, "--cutover")
    assert result.exit_code == 0, result.output
    at = _state(plan_file)["cutover"]["at"]
    report = plan_file.parent / "arcgis-migration-report.md"
    assert f"**Cut over** at {at}; losses accepted: none" in report.read_text()
    FakeRefresh(geolens, service).allow(PARCELS)
    monkeypatch.setattr(
        migrate_mod, "inventory_changes", lambda *a: "portal items changed"
    )

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    text = report.read_text()
    assert f"**Cut over** at {at}; losses accepted: none" in text
    assert "**Cutover refused:** incomplete-inventory" in text
    saved = json.loads((plan_file.parent / "arcgis-migration-report.json").read_text())
    assert saved["cutover"]["earlier"] == {"at": at, "accepted": []}


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
        (
            _SearchPortal({"results": [{"id": "a1", "modified": 1791000000000}]}),
            "changed after the inventory was read 10 days ago (a1)",
        ),
        # Changed while the inventory ran, after its start, before its end.
        (
            _SearchPortal({"results": [{"id": "a1", "modified": 1790815000000}]}),
            "changed after",
        ),
        (_SearchPortal({"results": [{"id": "a1", "modified": 1759000000000}]}), None),
        # An organization the plan came from has items; none is no answer.
        (_SearchPortal({"results": []}), "found no items of the organization"),
        (_SearchPortal({"results": []}, token=None), "no ArcGIS credential"),
        (None, "no ArcGIS credential"),
        (_SearchPortal(PortalError("boom", kind="server")), "couldn't check"),
        (_SearchPortal({"error": "nope"}), "couldn't check"),
        (_SearchPortal({"results": [{}]}), "couldn't check"),
        (
            _SearchPortal({"results": [{"id": "a1", "modified": None}]}),
            "couldn't check",
        ),
        (
            _SearchPortal({"results": [{"id": "a1", "modified": "1791000000000"}]}),
            "couldn't check",
        ),
        (
            _SearchPortal({"results": [{"id": "a1", "modified": True}]}),
            "couldn't check",
        ),
        (_SearchPortal({"results": [{"modified": 1791000000000}]}), "couldn't check"),
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
        assert params["sortField"] == "modified" and params["sortOrder"] == "desc"
        assert params["start"] == 1


class _PagedPortal(_SearchPortal):
    """A search answering *pages* in turn, each with its nextStart."""

    def __init__(self, pages) -> None:
        super().__init__(None)
        self.pages = list(pages)

    def get_json(self, path, params=None):
        self.asked.append((path, dict(params or {})))
        if path == "portals/self":
            return self.self_info
        return self.pages.pop(0)


def test_the_freshness_check_ignores_items_the_plan_skips():
    newer, older = 1791000000000, 1759000000000
    plan = {
        **_PLAN,
        "items": [
            {"id": "skipped", "action": "skip"},
            {"id": "imported", "action": "import_layers"},
        ],
    }
    pages = [
        {"results": [{"id": "skipped", "modified": newer}], "nextStart": 2},
        {"results": [{"id": "imported", "modified": older}], "nextStart": 3},
    ]

    assert cutover_mod.inventory_changes(_PagedPortal(pages), plan, _NOW) is None

    # The next page holds a planned item and a new one, changed after the read.
    client = _PagedPortal(
        [
            pages[0],
            {
                "results": [
                    {"id": "imported", "modified": newer},
                    {"id": "brand-new", "modified": newer},
                    {"id": "skipped", "modified": older},
                ],
                "nextStart": -1,
            },
        ]
    )
    reason = cutover_mod.inventory_changes(client, plan, _NOW)
    assert reason == (
        "portal items changed after the inventory was read 10 days ago (imported); "
        "portal items the plan doesn't hold were created or changed after the "
        "inventory was read 10 days ago (brand-new); run inventory and plan again "
        "to include them"
    )
    assert [p["start"] for path, p in client.asked if path == "search"] == [1, 2]


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
    assert not (plan_file.parent / "arcgis-migration-state.json").exists()


@pytest.mark.parametrize("refusal", ["inventory", "owner"])
def test_a_cutover_refused_for_what_no_run_changes_runs_nothing(
    runner, plan_file, geolens, monkeypatch, refusal
):
    _edit_plan(plan_file, (A2,))
    service = FakeImport(geolens, [_layer(0, "Parcels", has_attachments=False)])
    _migrate(runner, plan_file)
    refresh = FakeRefresh(geolens, service).allow(PARCELS)
    if refusal == "inventory":
        monkeypatch.setattr(
            migrate_mod,
            "inventory_changes",
            lambda client, plan, now: "portal items changed after the inventory",
        )
        check = "incomplete-inventory"
    else:
        monkeypatch.setattr(migrate_mod, "inventory_changes", lambda *a: None)
        plan = json.loads(plan_file.read_text())
        plan["owner_map"] = {k: "ghost" for k in plan["owner_map"]}
        plan_file.write_text(json.dumps(plan))
        check = "unresolved-users"

    result, payload = _migrate(runner, plan_file, "--cutover")

    assert result.exit_code == 1
    assert payload["cutover"]["refused"] == [check]
    assert payload["refreshed"] == [] and refresh.bodies == []
    assert _state(plan_file)["cutover"] is None
    text = runner.invoke(app, ["arcgis", "migrate", str(plan_file), "--cutover"])
    assert text.exit_code == 1
    assert "cutover refused" in text.output and "Report: " in text.output
    assert "up to date" not in text.output and "Ran 0" not in text.output
    # Nothing ran, so no state was saved and no earlier failure is counted.
    assert "State: " not in text.output and "item(s) failed" not in text.output


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
