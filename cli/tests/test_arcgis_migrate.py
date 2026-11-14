"""`geolens arcgis migrate`: plan order, state file, resume and owner mapping."""

from __future__ import annotations

import json
import os
import secrets
import stat
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

import typer

from geolens_cli import arcgis_migrate as migrate
from geolens_cli.arcgis_migrate_state import release_locks
from geolens_cli.main import app

from .conftest import GEOLENS_INSTANCE

PORTAL = "https://examplecounty.maps.arcgis.com"
OPERATOR = "00000000-0000-0000-0000-0000000000a0"
ALICE = "00000000-0000-0000-0000-0000000000a1"
VIC = "00000000-0000-0000-0000-0000000000a2"
GONE = "00000000-0000-0000-0000-0000000000a3"
L1, L2, M1, S1 = "11" * 16, "22" * 16, "33" * 16, "44" * 16
NOW = "2026-10-01T00:00:00Z"
# NOW as a write echoes it back in expected_updated_at.
READ_AT = "2026-10-01T00:00:00+00:00"


def _item(item_id: str, action: str = "import_layers", **extra: Any) -> dict[str, Any]:
    return {
        "id": item_id,
        "type": "Web Map" if action == "import_map" else "Feature Service",
        "title": f"Item {item_id[:2]}",
        "owner": extra.pop("owner", "agol_alice"),
        "action": action,
        "reason": "test",
        "target": {
            "owner": extra.pop("target_owner", None),
            "visibility": "private",
            "collections": [],
            "groups": [],
            "title": f"Item {item_id[:2]}",
            "tags": [],
        },
        "depends_on": list(extra.pop("depends_on", [])),
        **extra,
    }


def _plan(items: list[dict], owner_map: dict[str, str] | None = None) -> dict:
    return {
        "schema_version": "1",
        "inventory": {"path": "inv.json", "generated_at": NOW, "complete": True},
        "portal": {"url": PORTAL},
        "defaults": {"visibility": "private", "collection_from": "folder"},
        "owner_map": {"agol_alice": "alice"} if owner_map is None else owner_map,
        "group_map": {},
        "basemap_map": {},
        "items": items,
    }


def _user(user_id: str, username: str, roles: list[str], active: bool = True) -> dict:
    return {
        "id": user_id,
        "username": username,
        "email": f"{username}@example.org",
        "is_active": active,
        "status": "active" if active else "deactivated",
        "last_login_at": None,
        "created_at": NOW,
        "roles": roles,
        "can_reset_password": False,
    }


def _dataset(dataset_id: str, owner: str) -> dict:
    return {
        "id": dataset_id,
        "record_id": dataset_id,
        "table_name": "t",
        "title": "t",
        "summary": None,
        "feature_count": 0,
        "source_filename": None,
        "visibility": "private",
        "created_by": owner,
        "created_by_display": None,
        "created_at": NOW,
        "updated_at": NOW,
        "updated_by": OPERATOR,
    }


def _map(map_id: str, owner: str) -> dict:
    return {
        "id": map_id,
        "name": "m",
        "description": None,
        "center_lng": 0.0,
        "center_lat": 0.0,
        "zoom": 1.0,
        "bearing": 0.0,
        "pitch": 0.0,
        "basemap_style": "light",
        "show_basemap_labels": True,
        "visibility": "private",
        "created_by": owner,
        "created_at": NOW,
        "updated_at": NOW,
        "layers": [],
        "layer_count": 0,
    }


DEFAULT_ROLES = {
    "viewer": {"upload": False, "edit_metadata": False},
    "editor": {"upload": True, "edit_metadata": True},
    "admin": {"upload": True, "edit_metadata": True},
}


def _settings(role_permissions: dict) -> dict:
    return {
        "env_only": False,
        "tabs": {
            "auth": [
                {
                    "key": "role_permissions",
                    "value": role_permissions,
                    "source": "default",
                    "label": "Role permissions",
                }
            ]
        },
    }


def _install(monkeypatch, handler) -> None:
    for action in migrate.TRANSFER_PERMISSION:
        monkeypatch.setitem(migrate.HANDLERS, action, handler)


@pytest.fixture(autouse=True)
def no_inventory(monkeypatch):
    """These tests stub the handlers, which are what read the inventory."""
    monkeypatch.setattr(migrate, "_inventory_rows", lambda *args: ({}, None, {}))


@pytest.fixture(autouse=True)
def refreshed(monkeypatch):
    """Refreshers that record the finished items a rerun brings up to date."""
    calls: list[str] = []

    def refresher(ctx, item, entry):
        calls.append(item["id"])
        return []

    for action in migrate.REFRESHERS:
        monkeypatch.setitem(migrate.REFRESHERS, action, refresher)
    return calls


@pytest.fixture
def geolens(fake_geolens):
    """The fake instance with an admin operator, alice (editor) and vic (viewer)."""
    users = [
        _user(OPERATOR, "operator", ["admin"]),
        _user(ALICE, "alice", ["editor"]),
        _user(VIC, "vic", ["viewer"]),
        _user(GONE, "gone", ["editor"], active=False),
    ]
    fake_geolens.routes.update(
        {
            "GET /auth/me/": users[0],
            "GET /admin/users/": {"users": users, "total": len(users)},
            "GET /settings/all/": _settings(DEFAULT_ROLES),
            "GET /settings/feature-flags/": {"restrict_public_visibility": False},
            "GET /datasets/": {"datasets": [], "total": 0},
            "GET /catalog/collections/": {"collections": [], "total": 0},
        }
    )
    return fake_geolens


def _allow_transfers(fake, *ids: str, map_ids: tuple[str, ...] = ()) -> None:
    for dataset_id in ids:
        fake.routes[f"PATCH /datasets/{dataset_id}"] = lambda seen, d=dataset_id: (
            _dataset(d, seen.json()["owner_id"])
        )
        fake.routes[f"GET /datasets/{dataset_id}"] = _dataset(dataset_id, OPERATOR)
    for map_id in map_ids:
        fake.routes[f"PATCH /maps/{map_id}"] = lambda seen, m=map_id: _map(
            m, seen.json()["owner_id"]
        )
        fake.routes[f"GET /maps/{map_id}"] = _map(map_id, OPERATOR)


def _created_id(item_id: str) -> str:
    return f"00000000-0000-0000-0001-{item_id[:12]}"


@pytest.fixture
def handled(monkeypatch):
    """Handlers for every import action that record the order they ran in."""
    calls: list[str] = []

    def handler(ctx, item, entry):
        calls.append(item["id"])
        if item["action"] == "import_map":
            if not entry.map_id:
                # As the import records the map it made.
                entry.map_id = _created_id(item["id"])
                entry.map_snapshot = {"owner": ctx.operator_id, "updated_at": READ_AT}
        else:
            entry.dataset_ids = [_created_id(item["id"])]
        return migrate.ItemResult()

    _install(monkeypatch, handler)
    return calls


def _run(runner, tmp_path: Path, plan: dict, *args: str):
    path = tmp_path / "arcgis-migration-plan.json"
    path.write_text(json.dumps(plan))
    result = runner.invoke(app, ["--json", "arcgis", "migrate", str(path), *args])
    payload = json.loads(result.stdout) if result.stdout.strip() else None
    return result, payload


def _state(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "arcgis-migration-state.json").read_text())


def _write_state(
    tmp_path: Path,
    items: dict[str, dict],
    portal: str = PORTAL,
    instance: str = GEOLENS_INSTANCE,
) -> None:
    (tmp_path / "arcgis-migration-state.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "portal_url": portal,
                "geolens_instance": instance,
                "items": items,
            }
        )
    )


# Ordering


def test_items_run_after_the_items_they_depend_on(runner, tmp_path, geolens, handled):
    _allow_transfers(
        geolens, _created_id(L1), _created_id(L2), map_ids=(_created_id(M1),)
    )
    plan = _plan([_item(M1, "import_map", depends_on=[L2, L1]), _item(L2), _item(L1)])

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert handled == [L2, L1, M1]
    assert {r["id"]: r["status"] for r in payload["items"]} == dict.fromkeys(
        (L2, L1, M1), "done"
    )


def test_a_dependency_cycle_is_a_usage_error_before_any_request(
    runner, tmp_path, geolens, handled
):
    plan = _plan([_item(L1, depends_on=[L2]), _item(L2, depends_on=[L1])])

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 2
    assert "cycle" in result.output and L1 in result.output
    assert geolens.seen == [] and handled == []


def test_a_dependency_outside_the_plan_does_not_hold_an_item_back(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    result, _ = _run(runner, tmp_path, _plan([_item(L1, depends_on=["ff" * 16])]))
    assert result.exit_code == 0, result.output
    assert handled == [L1]


# State file and resume


def test_resume_after_a_crash_runs_only_unfinished_items(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1), _created_id(L2), _created_id(S1))
    _write_state(
        tmp_path,
        {
            L1: {"status": "done", "dataset_ids": [_created_id(L1)], "owner_id": ALICE},
            L2: {"status": "running"},
        },
    )
    plan = _plan([_item(L1), _item(L2), _item(S1)])

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert handled == [L2, S1]
    saved = _state(tmp_path)["items"]
    assert {k: v["status"] for k, v in saved.items()} == dict.fromkeys(
        (L1, L2, S1), "done"
    )
    assert saved[L2]["dataset_ids"] == [_created_id(L2)]


def test_state_file_is_private(runner, tmp_path, geolens, handled):
    _allow_transfers(geolens, _created_id(L1))
    _run(runner, tmp_path, _plan([_item(L1)]))
    mode = (tmp_path / "arcgis-migration-state.json").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_failed_items_are_retried_unless_no_retry(runner, tmp_path, geolens, handled):
    _allow_transfers(geolens, _created_id(L1))
    _write_state(tmp_path, {L1: {"status": "failed", "error": "boom"}})

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]), "--no-retry")
    # The failure is still in the state, so the run is not a success.
    assert result.exit_code == 1 and handled == []

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))
    assert result.exit_code == 0 and handled == [L1]
    assert _state(tmp_path)["items"][L1]["error"] is None


def test_only_pulls_in_unfinished_dependencies(runner, tmp_path, geolens, handled):
    _allow_transfers(geolens, _created_id(L2), map_ids=(_created_id(M1),))
    _write_state(tmp_path, {L1: {"status": "done", "owner_id": ALICE}})
    plan = _plan(
        [
            _item(L1),
            _item(L2),
            _item(S1),
            _item(M1, "import_map", depends_on=[L1, L2]),
        ]
    )

    result, _ = _run(runner, tmp_path, plan, "--only", M1)

    assert result.exit_code == 0, result.output
    assert handled == [L2, M1]


def test_only_with_an_unknown_id_is_a_usage_error(runner, tmp_path, geolens, handled):
    result, _ = _run(runner, tmp_path, _plan([_item(L1)]), "--only", "ff" * 16)
    assert result.exit_code == 2 and "not in the plan" in result.output


def test_a_state_file_from_another_portal_is_refused(
    runner, tmp_path, geolens, handled
):
    _write_state(tmp_path, {}, portal="https://other.example")
    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))
    assert result.exit_code == 2
    assert "records a migration from" in result.output
    assert handled == []


def test_a_state_file_from_another_geolens_is_refused(
    runner, tmp_path, geolens, handled
):
    _write_state(
        tmp_path,
        {L1: {"status": "done", "dataset_ids": [_created_id(L1)]}},
        instance="https://old.example.org/api",
    )
    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))
    assert result.exit_code == 2
    assert "records a migration into" in result.output
    assert handled == [] and geolens.seen == []


def test_dry_run_writes_no_state_and_changes_nothing(
    runner, tmp_path, geolens, handled
):
    result, payload = _run(runner, tmp_path, _plan([_item(L1)]), "--dry-run")

    assert result.exit_code == 0, result.output
    assert payload["items"] == [
        {
            "id": L1,
            "title": "Item 11",
            "action": "import_layers",
            "status": "pending",
            "owner": "alice",
            "notes": [],
            "error": None,
        }
    ]
    assert not (tmp_path / "arcgis-migration-state.json").exists()
    assert handled == []
    assert all(s.method == "GET" for s in geolens.seen)


@pytest.mark.parametrize("dry_run", [True, False])
def test_a_failed_item_set_to_skip_shows_skipped_in_a_dry_run_too(
    runner, tmp_path, geolens, handled, dry_run
):
    _write_state(tmp_path, {L1: {"status": "failed", "error": "HTTP 422"}})
    flags = ("--dry-run",) if dry_run else ()

    result, payload = _run(runner, tmp_path, _plan([_item(L1, "skip")]), *flags)

    assert result.exit_code == 0, result.output
    [row] = payload["items"]
    assert (row["status"], row["error"]) == ("skipped", None)
    assert payload["failed"] == []
    assert _state(tmp_path)["items"][L1]["status"] == (
        "failed" if dry_run else "skipped"
    )


def test_brought_up_to_date_counts_only_the_items_that_are(
    runner, tmp_path, geolens, monkeypatch
):
    reasons = {L1: [], L2: ["changed in GeoLens since the last run"]}
    for action in migrate.REFRESHERS:
        monkeypatch.setitem(
            migrate.REFRESHERS, action, lambda ctx, item, entry: reasons[item["id"]]
        )
    _write_state(
        tmp_path,
        {
            item: {"status": "done", "dataset_ids": [_created_id(item)]}
            for item in reasons
        },
    )
    path = tmp_path / "arcgis-migration-plan.json"
    path.write_text(json.dumps(_plan([_item(L1), _item(L2)])))

    result = runner.invoke(app, ["arcgis", "migrate", str(path)])

    assert result.exit_code == 1
    assert "Brought 1 migrated item(s) up to date." in result.output
    assert f"{L2} is not up to date" in result.output


def _migrated(dataset_id: str, item_id: str, kind: str = "service") -> dict:
    return {
        **_dataset(dataset_id, ALICE),
        "title": f"Copy of {item_id[:2]}",
        "origin_ref": {"kind": kind, "item_id": item_id, "portal_url": PORTAL},
    }


def _catalog(fake, monkeypatch, *datasets: dict) -> None:
    """GeoLens holds *datasets*, listed one per page."""
    monkeypatch.setattr(migrate, "DATASET_PAGE", 1)
    fake.routes["GET /datasets/"] = lambda seen: {
        "datasets": list(
            datasets[int(parse_qs(urlsplit(seen.url).query)["skip"][0]) :][:1]
        ),
        "total": len(datasets),
    }


@pytest.mark.parametrize("dry_run", [False, True])
def test_a_run_without_its_state_file_refuses_to_import_migrated_items_again(
    runner, tmp_path, geolens, handled, monkeypatch, dry_run
):
    copy = "00000000-0000-0000-0002-000000000001"
    _catalog(
        geolens,
        monkeypatch,
        _migrated("00000000-0000-0000-0002-000000000002", "ff" * 16),
        # Another catalog's item id, which names no portal item.
        _migrated("00000000-0000-0000-0002-000000000003", L1, kind="stac"),
        _migrated(copy, L1),
    )
    state_file = tmp_path / "lost" / "arcgis-migration-state.json"

    result, _ = _run(
        runner,
        tmp_path,
        _plan([_item(L1), _item(L2)]),
        "--state",
        str(state_file),
        *(["--dry-run"] if dry_run else []),
    )

    assert result.exit_code == 2
    assert f"no state file at {state_file}" in result.output
    assert (
        f"1 dataset(s) migrated from 1 of the plan's items (Copy of 11 ({copy}))"
        in result.output
    )
    assert "--start-fresh" in result.output
    assert handled == [] and not state_file.exists()
    assert all(s.method == "GET" for s in geolens.seen)


def test_start_fresh_runs_without_the_state_file_anyway(
    runner, tmp_path, geolens, handled, monkeypatch
):
    _allow_transfers(geolens, _created_id(L1))
    _catalog(
        geolens, monkeypatch, _migrated("00000000-0000-0000-0002-000000000001", L1)
    )

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]), "--start-fresh")

    assert result.exit_code == 0, result.output
    assert handled == [L1]


def test_a_rerun_with_its_state_file_doesnt_look_for_earlier_copies(
    runner, tmp_path, geolens, handled, monkeypatch
):
    _allow_transfers(geolens, _created_id(L2))
    _catalog(geolens, monkeypatch, _migrated(_created_id(L1), L1))
    _write_state(tmp_path, {})

    result, _ = _run(runner, tmp_path, _plan([_item(L2)]))

    assert result.exit_code == 0, result.output
    assert handled == [L2]
    assert not any(urlsplit(s.url).path.endswith("/datasets/") for s in geolens.seen)


def test_an_action_without_a_handler_is_left_pending(
    runner, tmp_path, geolens, monkeypatch
):
    monkeypatch.delitem(migrate.HANDLERS, "import_map")
    plan = _plan([_item(L1, "import_map"), _item(M1, "import_map", depends_on=[L1])])

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 1
    assert payload["not_available"] == [L1, M1]
    assert _state(tmp_path)["items"] == {}


def test_a_map_waits_while_its_layer_failed(runner, tmp_path, geolens, monkeypatch):
    def handler(ctx, item, entry):
        if item["id"] == L1:
            raise migrate.ItemFailed("the service answered 500")
        raise AssertionError("the map must not run")

    _install(monkeypatch, handler)
    plan = _plan([_item(L1), _item(M1, "import_map", depends_on=[L1])])

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 1
    assert payload["waiting"] == [{"item": M1, "waiting_on": [L1]}]
    assert _state(tmp_path)["items"][L1]["error"] == "the service answered 500"


def test_skip_items_are_recorded_as_skipped(runner, tmp_path, geolens, handled):
    result, _ = _run(runner, tmp_path, _plan([_item(L1, "skip")]))
    assert result.exit_code == 0
    assert _state(tmp_path)["items"][L1]["status"] == "skipped"
    assert handled == []


def test_interrupt_marks_the_item_and_stops(runner, tmp_path, geolens, monkeypatch):
    seen: list[str] = []

    def handler(ctx, item, entry):
        seen.append(item["id"])
        raise KeyboardInterrupt

    monkeypatch.setitem(migrate.HANDLERS, "import_layers", handler)

    result, _ = _run(runner, tmp_path, _plan([_item(L1), _item(L2)]))

    assert result.exit_code == 130
    assert seen == [L1]
    items = _state(tmp_path)["items"]
    assert items[L1]["status"] == "failed" and items[L1]["error"] == "interrupted"
    assert L2 not in items


def test_errors_in_the_state_file_are_redacted(runner, tmp_path, geolens, monkeypatch):
    portal_token = secrets.token_urlsafe(16)

    def handler(ctx, item, entry):
        raise migrate.ItemFailed(
            f"GET https://svc.example/q?token={portal_token} as Bearer {geolens.token}"
        )

    monkeypatch.setitem(migrate.HANDLERS, "import_layers", handler)

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))

    assert result.exit_code == 1
    raw = (tmp_path / "arcgis-migration-state.json").read_text()
    assert "[REDACTED]" in raw
    assert portal_token not in raw and geolens.token not in raw


# Owner mapping and transfer


def test_items_are_transferred_to_the_mapped_owner(runner, tmp_path, geolens, handled):
    _allow_transfers(geolens, _created_id(L1), map_ids=(_created_id(M1),))
    plan = _plan([_item(L1), _item(M1, "import_map", depends_on=[L1])])

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    patches = [s for s in geolens.seen if s.method == "PATCH"]
    assert [(s.url.rsplit("/", 2)[-2], s.json()) for s in patches] == [
        ("datasets", {"owner_id": ALICE, "expected_updated_at": READ_AT}),
        ("maps", {"owner_id": ALICE, "expected_updated_at": READ_AT}),
    ]
    assert _state(tmp_path)["items"][L1]["owner_id"] == ALICE


@pytest.mark.parametrize(
    "edit",
    [{"updated_by": ALICE}, {"data_revision": 1}, {"current_version": 2}],
    ids=["alice", "data", "replacement"],
)
def test_a_dataset_changed_before_its_first_transfer_is_not_handed_over(
    runner, tmp_path, geolens, handled, edit
):
    dataset_id = _created_id(L1)
    _allow_transfers(geolens, dataset_id)
    imported = {**_dataset(dataset_id, OPERATOR), "data_revision": 0}
    reads = []

    def read(seen):
        reads.append(seen)
        return imported if len(reads) == 1 else {**imported, **edit}

    geolens.routes[f"GET /datasets/{dataset_id}"] = read

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))

    assert result.exit_code == 1
    entry = _state(tmp_path)["items"][L1]
    assert entry["error"] == (
        f"dataset {dataset_id} changed in GeoLens before its owner was handed "
        "over; it was left as it is"
    )
    assert [s for s in geolens.seen if s.method == "PATCH"] == []
    assert entry["last_update"] == {} and entry["owner_id"] is None


def test_a_dataset_edited_before_the_post_import_read_is_not_handed_over(
    runner, tmp_path, geolens, handled
):
    dataset_id = _created_id(L1)
    _allow_transfers(geolens, dataset_id)
    imported = _dataset(dataset_id, OPERATOR)
    reads = []

    def read(seen):
        # Alice's feature edit lands before the first read; the metadata write
        # then makes the operator the last writer.
        reads.append(seen)
        writer = ALICE if len(reads) == 1 else OPERATOR
        return {**imported, "updated_by": writer, "data_revision": 1}

    geolens.routes[f"GET /datasets/{dataset_id}"] = read

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))

    assert result.exit_code == 1
    entry = _state(tmp_path)["items"][L1]
    assert entry["error"] == (
        f"dataset {dataset_id} changed in GeoLens before its owner was handed "
        "over; it was left as it is"
    )
    assert [s for s in geolens.seen if s.method == "PATCH"] == []
    assert entry["last_update"] == {}


def test_a_fresh_import_nobody_has_written_is_handed_over(
    runner, tmp_path, geolens, handled
):
    dataset_id = _created_id(L1)
    _allow_transfers(geolens, dataset_id)
    geolens.routes[f"GET /datasets/{dataset_id}"] = {
        **_dataset(dataset_id, OPERATOR),
        "updated_by": None,
        "data_revision": 0,
    }

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))

    assert result.exit_code == 0, result.output
    assert [s.json()["owner_id"] for s in geolens.seen if s.method == "PATCH"] == [
        ALICE
    ]


def test_the_baseline_is_the_transfers_answer_not_a_later_read(
    runner, tmp_path, geolens, handled
):
    dataset_id = _created_id(L1)
    _allow_transfers(geolens, dataset_id)
    read = geolens.routes[f"GET /datasets/{dataset_id}"]

    def alice_edits_after_the_transfer(seen):
        if any(s.method == "PATCH" for s in geolens.seen):
            return {**read, "updated_at": "2026-10-02T00:00:00Z", "updated_by": ALICE}
        return read

    geolens.routes[f"GET /datasets/{dataset_id}"] = alice_edits_after_the_transfer

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))

    assert result.exit_code == 0, result.output
    assert _state(tmp_path)["items"][L1]["last_update"][dataset_id]["updated_at"] == (
        READ_AT
    )


def test_a_retry_mapped_to_the_operator_reclaims_partly_transferred_items(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    _write_state(tmp_path, {L1: {"status": "failed", "owner_id": ALICE}})
    plan = _plan([_item(L1)], owner_map={"agol_alice": "operator@example.org"})

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    patches = [s.json() for s in geolens.seen if s.method == "PATCH"]
    assert patches == [{"owner_id": OPERATOR, "expected_updated_at": READ_AT}]
    assert _state(tmp_path)["items"][L1]["owner_id"] == OPERATOR


def test_target_owner_overrides_owner_map(runner, tmp_path, geolens, handled):
    _allow_transfers(geolens, _created_id(L1))
    plan = _plan([_item(L1, target_owner="operator")])
    result, payload = _run(runner, tmp_path, plan)
    assert result.exit_code == 0
    assert payload["items"][0]["owner"] == "operator"


@pytest.mark.parametrize(
    ("owner_map", "expected"),
    [
        ({"agol_alice": "gone"}, "gone is not an active GeoLens user"),
        ({"agol_alice": ""}, "has no GeoLens owner in owner_map"),
        ({}, "has no GeoLens owner in owner_map"),
        ({"agol_alice": "nobody"}, "nobody (owner of"),
    ],
)
def test_an_unusable_owner_stops_the_run_before_any_import(
    runner, tmp_path, geolens, handled, owner_map, expected
):
    result, _ = _run(runner, tmp_path, _plan([_item(L1)], owner_map=owner_map))

    assert result.exit_code == 2
    assert expected in result.output
    assert handled == []
    assert all(s.method == "GET" for s in geolens.seen)
    assert not (tmp_path / "arcgis-migration-state.json").exists()


@pytest.mark.parametrize(
    ("inventory_email", "named"),
    [("agol_alice@example.org", True), ("someone@else.org", False), (None, False)],
    ids=["same-email", "other-email", "no-email"],
)
def test_an_empty_owner_map_entry_names_the_account_with_the_same_username_and_email(
    runner, tmp_path, geolens, handled, monkeypatch, inventory_email, named
):
    _users(
        geolens, _user("00000000-0000-0000-0000-0000000000b1", "agol_alice", ["editor"])
    )
    row = {"owner": "agol_alice", "owner_email": inventory_email}
    monkeypatch.setattr(migrate, "_inventory_rows", lambda *args: ({L1: row}, None, {}))

    result, _ = _run(
        runner,
        tmp_path,
        _plan([_item(L1)], owner_map={"agol_alice": ""}),
        "--dry-run",
    )

    assert result.exit_code == 2
    assert "has no GeoLens owner in owner_map" in result.output
    assert ('\\"agol_alice\\": \\"agol_alice\\"' in result.output) is named
    assert handled == []


def test_unmapped_owner_takes_items_whose_owner_cannot_hold_them(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1), _created_id(L2))
    plan = _plan(
        [_item(L1), _item(L2, owner="agol_bob")],
        owner_map={"agol_alice": "gone", "agol_bob": ""},
    )

    result, payload = _run(runner, tmp_path, plan, "--unmapped-owner", "alice")

    assert result.exit_code == 0, result.output
    assert [r["owner"] for r in payload["items"]] == ["alice", "alice"]
    assert len(payload["owner_reassigned"]) == 2


def test_an_unknown_name_is_refused_without_an_unmapped_owner(
    runner, tmp_path, geolens, handled
):
    plan = _plan([_item(L1)], owner_map={"agol_alice": "nobody"})
    result, _ = _run(runner, tmp_path, plan)
    assert result.exit_code == 2 and handled == []
    assert "nobody (owner of" in result.output


def _users(fake, *extra: dict) -> None:
    users = [*fake.routes["GET /admin/users/"]["users"], *extra]
    fake.routes["GET /admin/users/"] = {"users": users, "total": len(users)}


def _owner_patches(fake) -> list[str]:
    return [s.json()["owner_id"] for s in fake.seen if s.method == "PATCH"]


NEW = "00000000-0000-0000-0000-0000000000a4"


def test_an_owner_not_in_geolens_yet_waits_and_is_handed_over_later(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    plan = _plan([_item(L1)], owner_map={"agol_alice": "newbie"})

    result, payload = _run(runner, tmp_path, plan, "--unmapped-owner", "operator")

    assert result.exit_code == 0, result.output
    reason = "newbie is not a GeoLens user yet"
    assert payload["owner_pending"] == {L1: reason}
    entry = _state(tmp_path)["items"][L1]
    assert entry["owner_id"] == OPERATOR and entry["owner_pending"] == reason
    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    assert [f["kind"] for f in report["follow_ups"]] == ["owner_pending"]

    _users(geolens, _user(NEW, "newbie", ["editor"]))
    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert handled == [L1]
    assert _owner_patches(geolens) == [OPERATOR, NEW]
    assert payload["handed_over"] == [{"item": L1, "owner": "newbie"}]
    entry = _state(tmp_path)["items"][L1]
    assert entry["owner_id"] == NEW and entry["owner_pending"] is None


@pytest.mark.parametrize("raced", ["datasets", "maps"])
def test_a_transfer_to_a_role_that_cant_own_it_asks_for_a_promotion(
    runner, tmp_path, geolens, handled, raced
):
    _allow_transfers(geolens, _created_id(L1), map_ids=(_created_id(M1),))
    refused_id = _created_id(L1 if raced == "datasets" else M1)
    geolens.routes[f"PATCH /{raced}/{refused_id}"] = (
        422,
        {
            "title": "Unprocessable Content",
            "status": 422,
            "detail": "The new owner's role does not grant the upload permission.",
        },
    )
    # The role matrix can't be read, so only GeoLens can tell vic can't own it.
    geolens.routes["GET /settings/all/"] = (
        500,
        {"title": "Error", "status": 500, "detail": "boom"},
    )
    item = _item(L1) if raced == "datasets" else _item(M1, "import_map")
    plan = _plan([item], owner_map={"agol_alice": "vic"})

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 1, result.output
    error = _state(tmp_path)["items"][item["id"]]["error"]
    assert error == (
        f"{raced[:-1]} {refused_id} wasn't handed to vic, whose role can't own "
        "it; promote vic to editor in GeoLens and run again, or pass "
        "--unmapped-owner to hold it meanwhile"
    )


@pytest.mark.parametrize(
    ("owner", "updated_at"),
    [
        (OPERATOR, "2026-10-01T00:00:00Z"),
        (OPERATOR, "2026-10-05T00:00:00Z"),
        (ALICE, "2026-10-01T00:00:00Z"),
    ],
    ids=["untouched", "edited-after-the-run", "given-away"],
)
def test_a_waiting_map_without_a_snapshot_is_reported_not_handed_over(
    runner, tmp_path, geolens, handled, owner, updated_at
):
    map_id = _created_id(M1)
    _allow_transfers(geolens, map_ids=(map_id,))
    geolens.routes[f"GET /maps/{map_id}"] = {
        **_map(map_id, owner),
        "updated_at": updated_at,
    }
    _write_state(
        tmp_path,
        {
            M1: {
                "status": "done",
                "map_id": map_id,
                "owner_id": OPERATOR,
                "owner_pending": "newbie is not a GeoLens user yet",
                "finished_at": "2026-10-02T00:00:00Z",
            }
        },
    )
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    plan = _plan([_item(M1, "import_map")], owner_map={"agol_alice": "newbie"})

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 1
    assert _owner_patches(geolens) == []
    [failed] = payload["handover_failed"]
    assert f"map {map_id} has no recorded baseline" in failed
    entry = _state(tmp_path)["items"][M1]
    assert entry["owner_pending"] and entry["map_snapshot"] is None


STALE = (
    409,
    {
        "title": "Conflict",
        "status": 409,
        "detail": {"code": "stale_write", "message": "changed"},
    },
)


@pytest.mark.parametrize("raced", ["datasets", "maps"])
def test_a_transfer_geolens_refuses_as_stale_fails_the_item(
    runner, tmp_path, geolens, handled, raced
):
    _allow_transfers(geolens, _created_id(L1), map_ids=(_created_id(M1),))
    raced_id = _created_id(L1 if raced == "datasets" else M1)
    geolens.routes[f"PATCH /{raced}/{raced_id}"] = STALE
    item = _item(L1) if raced == "datasets" else _item(M1, "import_map")

    result, _ = _run(runner, tmp_path, _plan([item]))

    assert result.exit_code == 1
    entry = _state(tmp_path)["items"][item["id"]]
    assert entry["status"] == "failed"
    assert entry["error"] == (
        f"changed in GeoLens while {raced[:-1]} "
        f"{raced_id} was handed over; it was left as it is"
    )
    assert entry["owner_id"] is None


def test_a_handover_geolens_refuses_as_stale_is_reported_not_recorded(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    plan = _plan([_item(L1)], owner_map={"agol_alice": "newbie"})
    _run(runner, tmp_path, plan, "--unmapped-owner", "operator")
    recorded = _state(tmp_path)["items"][L1]["last_update"]
    geolens.routes[f"PATCH /datasets/{_created_id(L1)}"] = STALE
    _users(geolens, _user(NEW, "newbie", ["editor"]))

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 1
    [failed] = payload["handover_failed"]
    assert failed.endswith(
        f"changed in GeoLens while dataset {_created_id(L1)} was handed over; "
        "it was left as it is"
    )
    entry = _state(tmp_path)["items"][L1]
    assert entry["owner_id"] == OPERATOR and entry["owner_pending"]
    assert entry["last_update"] == recorded


def test_a_viewer_owner_is_asked_to_be_promoted_instead_of_a_refused_transfer(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    plan = _plan([_item(L1)], owner_map={"agol_alice": "vic"})

    result, payload = _run(runner, tmp_path, plan, "--unmapped-owner", "operator")

    assert result.exit_code == 0, result.output
    assert _owner_patches(geolens) == [OPERATOR]
    assert "promote vic to editor" in payload["owner_pending"][L1]

    _users(geolens)
    geolens.routes["GET /settings/all/"] = _settings(
        {**DEFAULT_ROLES, "viewer": {"upload": True, "edit_metadata": True}}
    )
    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert _owner_patches(geolens) == [OPERATOR, VIC]
    assert _state(tmp_path)["items"][L1]["owner_pending"] is None


def test_a_viewer_who_stays_a_viewer_is_not_handed_the_item(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    plan = _plan([_item(L1)], owner_map={"agol_alice": "vic"})
    _run(runner, tmp_path, plan, "--unmapped-owner", "operator")

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert _owner_patches(geolens) == [OPERATOR]
    assert "promote vic to editor" in payload["owner_pending"][L1]


def test_a_waiting_item_is_not_handed_to_an_inactive_unmapped_owner(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    plan = _plan([_item(L1)], owner_map={"agol_alice": "newbie"})
    _run(runner, tmp_path, plan, "--unmapped-owner", "operator")

    result, _ = _run(runner, tmp_path, plan, "--unmapped-owner", "gone")

    assert result.exit_code == 0, result.output
    assert _owner_patches(geolens) == [OPERATOR]
    assert _state(tmp_path)["items"][L1]["owner_id"] == OPERATOR


def test_a_handover_that_failed_part_way_resumes_on_the_next_run(
    runner, tmp_path, geolens, handled
):
    first, second = _created_id(L1), _created_id(L2)
    owners = {first: OPERATOR, second: OPERATOR}
    edited = {first: NOW, second: NOW}
    refuse = {second}

    def get(seen, d):
        return {**_dataset(d, owners[d]), "updated_at": edited[d]}

    def patch(seen, d):
        if d in refuse:
            return (500, {"title": "Error", "status": 500, "detail": "boom"})
        owners[d] = seen.json()["owner_id"]
        edited[d] = "2026-10-02T00:00:00Z"
        return get(seen, d)

    for d in (first, second):
        geolens.routes[f"GET /datasets/{d}"] = lambda seen, d=d: get(seen, d)
        geolens.routes[f"PATCH /datasets/{d}"] = lambda seen, d=d: patch(seen, d)
    snapshot = {"updated_at": "2026-10-01T00:00:00+00:00", "feature_count": 0}
    _write_state(
        tmp_path,
        {
            L1: {
                "status": "done",
                "dataset_ids": [first, second],
                "owner_id": OPERATOR,
                "owner_pending": "newbie is not a GeoLens user yet",
                "last_update": {
                    first: {**snapshot, "data_revision": None},
                    second: {**snapshot, "data_revision": None},
                },
            }
        },
    )
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    plan = _plan([_item(L1)], owner_map={"agol_alice": "newbie"})

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 1 and payload["handover_failed"]
    assert owners == {first: NEW, second: OPERATOR}
    recorded = _state(tmp_path)["items"][L1]["last_update"]
    assert recorded[first]["updated_at"].startswith("2026-10-02")

    refuse.clear()
    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert payload["handed_over"] == [{"item": L1, "owner": "newbie"}]
    assert owners == {first: NEW, second: NEW}
    entry = _state(tmp_path)["items"][L1]
    assert entry["owner_id"] == NEW and entry["owner_pending"] is None


def test_a_changed_unmapped_owner_takes_an_item_still_waiting(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    plan = _plan([_item(L1)], owner_map={"agol_alice": "newbie"})
    _run(runner, tmp_path, plan, "--unmapped-owner", "operator")

    result, payload = _run(runner, tmp_path, plan, "--unmapped-owner", "alice")

    assert result.exit_code == 0, result.output
    assert _owner_patches(geolens) == [OPERATOR, ALICE]
    entry = _state(tmp_path)["items"][L1]
    assert entry["owner_id"] == ALICE
    assert entry["owner_pending"] == "newbie is not a GeoLens user yet"


def test_a_waiting_item_changed_in_geolens_is_not_handed_over(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    plan = _plan([_item(L1)], owner_map={"agol_alice": "newbie"})
    _run(runner, tmp_path, plan, "--unmapped-owner", "operator")
    edited = {"updated_at": "2026-10-05T00:00:00Z", "updated_by": ALICE}
    geolens.routes[f"GET /datasets/{_created_id(L1)}"] = {
        **_dataset(_created_id(L1), OPERATOR),
        **edited,
    }
    _users(geolens, _user(NEW, "newbie", ["editor"]))

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 1
    assert _owner_patches(geolens) == [OPERATOR]
    [failed] = payload["handover_failed"]
    assert "changed in GeoLens since the last run" in failed
    entry = _state(tmp_path)["items"][L1]
    assert entry["owner_id"] == OPERATOR and entry["owner_pending"]

    # Handed to the owner in GeoLens meanwhile: nothing to transfer.
    geolens.routes[f"GET /datasets/{_created_id(L1)}"] = {
        **_dataset(_created_id(L1), NEW),
        **edited,
    }
    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert _owner_patches(geolens) == [OPERATOR]
    entry = _state(tmp_path)["items"][L1]
    assert entry["owner_id"] == NEW and entry["owner_pending"] is None


def test_a_waiting_map_given_to_someone_else_in_geolens_is_not_handed_over(
    runner, tmp_path, geolens, handled
):
    map_id = _created_id(M1)
    _allow_transfers(geolens, map_ids=(map_id,))
    plan = _plan([_item(M1, "import_map")], owner_map={"agol_alice": "newbie"})
    _run(runner, tmp_path, plan, "--unmapped-owner", "operator")
    # An administrator gives the map to alice, which moves its timestamp.
    geolens.routes[f"GET /maps/{map_id}"] = {
        **_map(map_id, ALICE),
        "updated_at": "2026-10-05T00:00:00Z",
    }
    _users(geolens, _user(NEW, "newbie", ["editor"]))

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 1
    assert _owner_patches(geolens) == [OPERATOR]
    [failed] = payload["handover_failed"]
    assert f"map {map_id} was changed in GeoLens since the last run" in failed
    entry = _state(tmp_path)["items"][M1]
    assert entry["owner_id"] == OPERATOR and entry["owner_pending"]


def test_a_waiting_map_nobody_touched_is_handed_over(
    runner, tmp_path, geolens, handled
):
    map_id = _created_id(M1)
    _allow_transfers(geolens, map_ids=(map_id,))
    plan = _plan([_item(M1, "import_map")], owner_map={"agol_alice": "newbie"})
    _run(runner, tmp_path, plan, "--unmapped-owner", "operator")
    assert _state(tmp_path)["items"][M1]["map_snapshot"]["owner"] == OPERATOR
    _users(geolens, _user(NEW, "newbie", ["editor"]))

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert _owner_patches(geolens) == [OPERATOR, NEW]
    assert _state(tmp_path)["items"][M1]["map_snapshot"]["owner"] == NEW


@pytest.mark.parametrize(
    ("owner", "reason"),
    [
        ("", "its plan owner is empty"),
        ("nobody", "its plan owner nobody is not a GeoLens user"),
        ("alice@example.org", "matches more than one GeoLens user"),
    ],
)
def test_a_migrated_item_whose_plan_owner_no_longer_resolves_is_reported(
    runner, tmp_path, geolens, handled, owner, reason
):
    _allow_transfers(geolens, _created_id(L1))
    _users(geolens, _user(NEW, "alice@example.org", ["editor"]))
    _write_state(
        tmp_path,
        {L1: {"status": "done", "dataset_ids": [_created_id(L1)], "owner_id": ALICE}},
    )

    result, payload = _run(
        runner, tmp_path, _plan([_item(L1, target_owner=owner)]), "--cutover"
    )

    [unresolved] = payload["owner_unresolved"]
    assert unresolved["item"] == L1 and reason in unresolved["reason"]
    assert "unresolved-users" in payload["cutover"]["refused"]
    assert _owner_patches(geolens) == []


def test_each_accept_flag_lifts_only_its_own_check(runner, tmp_path, geolens, handled):
    _allow_transfers(geolens, _created_id(L1))
    plan = _plan([_item(L1)], owner_map={"agol_alice": "newbie"})

    result, payload = _run(
        runner,
        tmp_path,
        plan,
        "--unmapped-owner",
        "operator",
        "--cutover",
        "--accept-unresolved-users",
    )

    assert result.exit_code == 1
    assert payload["cutover"]["accepted"] == ["unresolved-users"]
    # A v1 plan records no inventory scope.
    assert payload["cutover"]["refused"] == ["incomplete-inventory"]

    result, payload = _run(
        runner,
        tmp_path,
        plan,
        "--unmapped-owner",
        "operator",
        "--cutover",
        "--accept-incomplete-inventory",
        "--accept-unfinished-items",
        "--accept-attachment-loss",
    )
    assert payload["cutover"]["refused"] == ["unresolved-users"]


def test_a_state_file_is_written_at_the_current_version_and_v1_still_loads(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1), _created_id(L2))
    _write_state(
        tmp_path,
        {L1: {"status": "done", "dataset_ids": [_created_id(L1)], "owner_id": ALICE}},
    )

    result, _ = _run(runner, tmp_path, _plan([_item(L1), _item(L2)]))

    assert result.exit_code == 0, result.output
    assert _state(tmp_path)["schema_version"] == "6"


def test_cutover_counts_an_item_whose_plan_owner_moved_and_could_not_be_handed_over(
    runner, tmp_path, geolens, handled
):
    _write_state(
        tmp_path,
        {L1: {"status": "done", "dataset_ids": [_created_id(L1)], "owner_id": ALICE}},
    )

    result, payload = _run(
        runner,
        tmp_path,
        _plan([_item(L1, target_owner="operator")]),
        "--cutover",
        "--accept-incomplete-inventory",
    )

    assert result.exit_code == 1
    assert payload["cutover"]["refused"] == ["unresolved-users"]
    [check] = [
        c for c in payload["cutover"]["checks"] if c["check"] == "unresolved-users"
    ]
    assert check["items"] == [
        {
            "item": L1,
            "reason": "its plan owner is now operator, who hasn't been given it",
        }
    ]


def test_cutover_refuses_an_item_still_waiting_for_its_owner(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    plan = _plan([_item(L1)], owner_map={"agol_alice": "newbie"})

    result, payload = _run(
        runner,
        tmp_path,
        plan,
        "--unmapped-owner",
        "operator",
        "--cutover",
        "--accept-incomplete-inventory",
    )

    assert result.exit_code == 1
    assert "unresolved-users" in payload["cutover"]["refused"]
    [check] = [
        c for c in payload["cutover"]["checks"] if c["check"] == "unresolved-users"
    ]
    assert check["items"] == [
        {"item": L1, "reason": "newbie is not a GeoLens user yet"}
    ]
    # No run makes newbie a GeoLens user, so the cutover refuses before it.
    assert handled == []


def test_a_cutover_refuses_a_hold_left_on_a_skipped_item_before_the_run(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L2))
    _write_state(
        tmp_path,
        {
            L1: {
                "status": "done",
                "dataset_ids": [_created_id(L1)],
                "owner_id": OPERATOR,
                "owner_pending": "newbie is not a GeoLens user yet",
            }
        },
    )
    plan = _plan([_item(L1, "skip"), _item(L2)])

    result, payload = _run(
        runner, tmp_path, plan, "--cutover", "--accept-incomplete-inventory"
    )

    assert result.exit_code == 1
    assert "unresolved-users" in payload["cutover"]["refused"]
    [users] = [
        c for c in payload["cutover"]["checks"] if c["check"] == "unresolved-users"
    ]
    assert users["items"] == [
        {"item": L1, "reason": "newbie is not a GeoLens user yet"}
    ]
    # No run settles that hold, so the cutover refuses before importing L2.
    assert handled == []


def test_an_unusable_unmapped_owner_is_refused(runner, tmp_path, geolens, handled):
    plan = _plan([_item(L1)], owner_map={"agol_alice": ""})
    result, _ = _run(runner, tmp_path, plan, "--unmapped-owner", "gone")
    assert result.exit_code == 2
    assert "--unmapped-owner: gone is not an active" in result.output
    assert handled == []


def test_role_permissions_come_from_the_instance_settings(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    geolens.routes["GET /settings/all/"] = _settings(
        {**DEFAULT_ROLES, "viewer": {"upload": True, "edit_metadata": False}}
    )
    plan = _plan([_item(L1)], owner_map={"agol_alice": "vic"})

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert payload["owner_roles_checked"] is True


def test_a_map_owner_is_checked_for_edit_metadata_only(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, map_ids=(_created_id(M1),))
    geolens.routes["GET /settings/all/"] = _settings(
        {**DEFAULT_ROLES, "viewer": {"upload": False, "edit_metadata": True}}
    )
    owner_map = {"agol_alice": "vic"}

    result, payload = _run(
        runner, tmp_path, _plan([_item(M1, "import_map")], owner_map), "--dry-run"
    )
    assert payload["owner_warnings"] == []

    result, payload = _run(runner, tmp_path, _plan([_item(L1)], owner_map), "--dry-run")
    assert payload["owner_warnings"] == [
        f"{L1}: vic's roles (viewer) don't grant upload"
    ]


def test_unreadable_role_permissions_check_the_account_only(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    geolens.routes["GET /settings/all/"] = (
        403,
        {"detail": "no", "status": 403, "title": "Forbidden"},
    )
    plan = _plan([_item(L1)], owner_map={"agol_alice": "vic"})

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert payload["owner_roles_checked"] is False

    result, _ = _run(runner, tmp_path, _plan([_item(L2)], {"agol_alice": "gone"}))
    assert result.exit_code == 2 and "not an active" in result.output


def test_a_viewer_operator_is_refused(runner, tmp_path, geolens, handled):
    geolens.routes["GET /auth/me/"] = _user(VIC, "vic", ["viewer"])
    geolens.routes["GET /auth/me/permissions/"] = {"permissions": {"upload": False}}
    result, _ = _run(runner, tmp_path, _plan([_item(L1)], {"agol_alice": "vic"}))
    assert result.exit_code == 2 and "editor or admin" in result.output
    assert handled == []


def test_users_are_read_page_by_page(runner, tmp_path, geolens, handled, monkeypatch):
    monkeypatch.setattr(migrate, "USER_PAGE_SIZE", 2)
    users = geolens.routes["GET /admin/users/"]["users"]

    def page(seen):
        params = dict(p.split("=") for p in seen.url.split("?")[1].split("&"))
        start = int(params["skip"])
        return {"users": users[start : start + 2], "total": len(users)}

    geolens.routes["GET /admin/users/"] = page
    _allow_transfers(geolens, _created_id(L1))
    plan = _plan([_item(L1)], owner_map={"agol_alice": "gone"})

    result, _ = _run(runner, tmp_path, plan, "--unmapped-owner", "alice")

    assert result.exit_code == 0, result.output
    assert len([s for s in geolens.seen if "/admin/users/" in s.url]) == 2


def test_a_failed_transfer_fails_the_item_and_keeps_its_datasets(
    runner, tmp_path, geolens, handled
):
    geolens.routes[f"PATCH /datasets/{_created_id(L1)}"] = (
        422,
        {
            "detail": "The new owner's account is not active.",
            "status": 422,
            "title": "Unprocessable",
        },
    )
    geolens.routes[f"GET /datasets/{_created_id(L1)}"] = _dataset(
        _created_id(L1), OPERATOR
    )

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))

    assert result.exit_code == 1
    entry = _state(tmp_path)["items"][L1]
    assert entry["status"] == "failed"
    assert "not active" in entry["error"]
    assert entry["dataset_ids"] == [_created_id(L1)]


def test_an_owner_map_edit_after_import_hands_over_without_reimporting(
    runner, tmp_path, geolens, handled
):
    _owned(geolens, datasets=(_created_id(L1),))
    _write_state(
        tmp_path,
        {L1: {"status": "done", "dataset_ids": [_created_id(L1)], "owner_id": ALICE}},
    )
    plan = _plan([_item(L1)], owner_map={"agol_alice": "operator"})

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert handled == []
    assert payload["owner_changed"] == []
    assert payload["handed_over"] == [{"item": L1, "owner": "operator"}]
    assert _state(tmp_path)["items"][L1]["owner_id"] == OPERATOR


# Following an ArcGIS owner change on a rerun

BOB_OWNERS = {"agol_alice": "alice", "agol_bob": "newbie"}


def _owned(fake, *, datasets: tuple[str, ...] = (), maps: tuple[str, ...] = ()):
    """GeoLens objects (id -> created_by and updated_at) that each transfer
    gives a new owner and a later timestamp."""
    kinds = dict.fromkeys(datasets, "datasets") | dict.fromkeys(maps, "maps")
    objects = {o: {"created_by": OPERATOR, "updated_at": NOW} for o in kinds}
    transfers = 0

    def read(seen, object_id):
        make = _dataset if kinds[object_id] == "datasets" else _map
        return {**make(object_id, OPERATOR), **objects[object_id]}

    def transfer(seen, object_id):
        nonlocal transfers
        transfers += 1
        objects[object_id] = {
            "created_by": seen.json()["owner_id"],
            "updated_at": f"2026-10-0{transfers + 1}T00:00:00Z",
        }
        return read(seen, object_id)

    for object_id, kind in kinds.items():
        fake.routes[f"GET /{kind}/{object_id}"] = partial(read, object_id=object_id)
        fake.routes[f"PATCH /{kind}/{object_id}"] = partial(
            transfer, object_id=object_id
        )
    return objects


def _moved_to_bob(item: dict) -> dict:
    return {**item, "owner": "agol_bob"}


def test_an_arcgis_owner_change_hands_the_migrated_item_to_the_new_owner(
    runner, tmp_path, geolens, handled
):
    dataset_id, map_id = _created_id(L1), _created_id(M1)
    objects = _owned(geolens, datasets=(dataset_id,), maps=(map_id,))
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    items = [_item(L1), _item(M1, "import_map", depends_on=[L1])]
    assert _run(runner, tmp_path, _plan(items, BOB_OWNERS))[0].exit_code == 0
    assert _state(tmp_path)["items"][L1]["portal_owner"] == "agol_alice"

    plan = _plan([_moved_to_bob(item) for item in items], BOB_OWNERS)
    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert handled == [L1, M1]
    assert _owner_patches(geolens) == [ALICE, ALICE, NEW, NEW]
    assert {o["created_by"] for o in objects.values()} == {NEW}
    assert payload["handed_over"] == [
        {"item": L1, "owner": "newbie"},
        {"item": M1, "owner": "newbie"},
    ]
    assert payload["owner_changed"] == []
    for item_id in (L1, M1):
        entry = _state(tmp_path)["items"][item_id]
        assert (entry["owner_id"], entry["portal_owner"]) == (NEW, "agol_bob")

    _run(runner, tmp_path, plan)
    assert len(_owner_patches(geolens)) == 4


def test_only_hands_over_just_the_items_it_names_after_an_arcgis_owner_change(
    runner, tmp_path, geolens, handled
):
    dataset_id, map_id = _created_id(L1), _created_id(M1)
    objects = _owned(geolens, datasets=(dataset_id,), maps=(map_id,))
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    items = [_item(L1), _item(M1, "import_map")]
    assert _run(runner, tmp_path, _plan(items, BOB_OWNERS))[0].exit_code == 0
    plan = _plan([_moved_to_bob(item) for item in items], BOB_OWNERS)

    result, payload = _run(runner, tmp_path, plan, "--only", L1)

    assert result.exit_code == 0, result.output
    assert payload["handed_over"] == [{"item": L1, "owner": "newbie"}]
    assert objects[dataset_id]["created_by"] == NEW
    assert objects[map_id]["created_by"] == ALICE
    assert _state(tmp_path)["items"][M1]["owner_id"] == ALICE


def test_an_item_a_handover_left_split_is_finished_after_the_arcgis_owner_reverts(
    runner, tmp_path, geolens, handled
):
    first, second = _created_id(L1), _created_id(L2)
    objects = _owned(geolens, datasets=(first, second))
    for dataset_id in (first, second):
        objects[dataset_id]["created_by"] = ALICE
    snapshot = {"updated_at": READ_AT, "feature_count": 0, "data_revision": None}
    _write_state(
        tmp_path,
        {
            L1: {
                "status": "done",
                "dataset_ids": [first, second],
                "owner_id": ALICE,
                "portal_owner": "agol_alice",
                "last_update": {first: snapshot, second: snapshot},
            }
        },
    )
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    transfer = geolens.routes[f"PATCH /datasets/{second}"]
    geolens.routes[f"PATCH /datasets/{second}"] = (
        500,
        {"title": "Error", "status": 500, "detail": "boom"},
    )
    result, payload = _run(
        runner, tmp_path, _plan([_moved_to_bob(_item(L1))], BOB_OWNERS)
    )
    assert result.exit_code == 1 and payload["handover_failed"]
    assert (objects[first]["created_by"], objects[second]["created_by"]) == (
        NEW,
        ALICE,
    )
    geolens.routes[f"PATCH /datasets/{second}"] = transfer
    plan = _plan([_item(L1)], BOB_OWNERS)

    _dry, preview = _run(runner, tmp_path, plan, "--dry-run", "--cutover")
    result, payload = _run(runner, tmp_path, plan)

    assert "unresolved-users" in preview["cutover"]["refused"]
    assert result.exit_code == 0, result.output
    assert payload["handed_over"] == [{"item": L1, "owner": "alice"}]
    assert {o["created_by"] for o in objects.values()} == {ALICE}
    entry = _state(tmp_path)["items"][L1]
    assert (entry["owner_id"], entry["handover_incomplete"]) == (ALICE, False)


def test_a_waiting_item_a_handover_left_split_goes_back_when_its_owner_is_gone(
    runner, tmp_path, geolens, handled
):
    first, second = _created_id(L1), _created_id(L2)
    objects = _owned(geolens, datasets=(first, second))
    snapshot = {"updated_at": READ_AT, "feature_count": 0, "data_revision": None}
    _write_state(
        tmp_path,
        {
            L1: {
                "status": "done",
                "dataset_ids": [first, second],
                "owner_id": OPERATOR,
                "owner_pending": "newbie is not a GeoLens user yet",
                "last_update": {first: snapshot, second: snapshot},
            }
        },
    )
    plan = _plan([_item(L1)], owner_map={"agol_alice": "newbie"})
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    transfer = geolens.routes[f"PATCH /datasets/{second}"]
    geolens.routes[f"PATCH /datasets/{second}"] = (
        500,
        {"title": "Error", "status": 500, "detail": "boom"},
    )
    assert _run(runner, tmp_path, plan)[0].exit_code == 1
    assert objects[first]["created_by"] == NEW
    geolens.routes[f"PATCH /datasets/{second}"] = transfer
    # newbie's account is gone again, so the item stays with --unmapped-owner.
    geolens.routes["GET /admin/users/"]["users"].pop()
    geolens.routes["GET /admin/users/"]["total"] -= 1

    result, _ = _run(runner, tmp_path, plan, "--unmapped-owner", "operator")

    assert result.exit_code == 0, result.output
    assert {o["created_by"] for o in objects.values()} == {OPERATOR}
    assert _state(tmp_path)["items"][L1]["handover_incomplete"] is False


BOOM = (500, {"title": "Error", "status": 500, "detail": "boom"})


def test_an_incomplete_handover_goes_to_whoever_the_plan_names_now(
    runner, tmp_path, geolens, handled
):
    ids = [_created_id(i) for i in (L1, L2, S1)]
    objects = _owned(geolens, datasets=tuple(ids))
    transfers = {d: geolens.routes[f"PATCH /datasets/{d}"] for d in ids}
    for dataset_id in ids:
        objects[dataset_id]["created_by"] = ALICE
    snapshot = {"updated_at": READ_AT, "feature_count": 0, "data_revision": None}
    _write_state(
        tmp_path,
        {
            L1: {
                "status": "done",
                "dataset_ids": ids,
                "owner_id": ALICE,
                "portal_owner": "agol_alice",
                "last_update": dict.fromkeys(ids, snapshot),
            }
        },
    )
    _users(geolens, _user(NEW, "newbie", ["editor"]))

    def run(portal_owner: str, failing: str):
        for dataset_id in ids:
            geolens.routes[f"PATCH /datasets/{dataset_id}"] = (
                BOOM if dataset_id == failing else transfers[dataset_id]
            )
        item = {**_item(L1), "owner": portal_owner}
        return _run(runner, tmp_path, _plan([item], BOB_OWNERS))[0]

    def owners() -> list[str]:
        return [objects[d]["created_by"] for d in ids]

    assert run("agol_bob", failing=ids[2]).exit_code == 1
    assert owners() == [NEW, NEW, ALICE]
    # The ArcGIS owner goes back, and the way back stops part way too.
    assert run("agol_alice", failing=ids[1]).exit_code == 1
    assert owners() == [ALICE, NEW, ALICE]
    assert _state(tmp_path)["items"][L1]["handover_incomplete"] is True

    result = run("agol_bob", failing="")

    assert result.exit_code == 0, result.output
    assert owners() == [NEW, NEW, NEW]
    entry = _state(tmp_path)["items"][L1]
    assert (entry["owner_id"], entry["handover_incomplete"]) == (NEW, False)


def test_handovers_run_in_dependency_order(runner, tmp_path, geolens, handled):
    dataset_id, map_id = _created_id(L1), _created_id(M1)
    objects = _owned(geolens, datasets=(dataset_id,), maps=(map_id,))
    transfer_map = geolens.routes[f"PATCH /maps/{map_id}"]

    def refuse_while_hidden(seen):
        # GeoLens refuses a map whose new owner can't read one of its datasets.
        if objects[dataset_id]["created_by"] != seen.json()["owner_id"]:
            return (409, {"title": "Conflict", "status": 409, "detail": "hidden"})
        return transfer_map(seen)

    geolens.routes[f"PATCH /maps/{map_id}"] = refuse_while_hidden
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    items = [_item(M1, "import_map", depends_on=[L1]), _item(L1)]
    assert _run(runner, tmp_path, _plan(items, BOB_OWNERS))[0].exit_code == 0

    result, payload = _run(
        runner, tmp_path, _plan([_moved_to_bob(item) for item in items], BOB_OWNERS)
    )

    assert result.exit_code == 0, result.output
    assert [h["item"] for h in payload["handed_over"]] == [L1, M1]
    assert {o["created_by"] for o in objects.values()} == {NEW}


def test_an_entry_without_a_recorded_arcgis_owner_adopts_it_then_follows_changes(
    runner, tmp_path, geolens, handled
):
    _owned(geolens, datasets=(_created_id(L1),))
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    plan = _plan([_item(L1)], BOB_OWNERS)
    assert _run(runner, tmp_path, plan)[0].exit_code == 0
    state = _state(tmp_path)
    del state["items"][L1]["portal_owner"]
    (tmp_path / "arcgis-migration-state.json").write_text(json.dumps(state))
    assert _run(runner, tmp_path, plan)[0].exit_code == 0
    assert _state(tmp_path)["items"][L1]["portal_owner"] == "agol_alice"

    result, payload = _run(
        runner, tmp_path, _plan([_moved_to_bob(_item(L1))], BOB_OWNERS)
    )

    assert result.exit_code == 0, result.output
    assert _owner_patches(geolens) == [ALICE, NEW]
    assert payload["handed_over"] == [{"item": L1, "owner": "newbie"}]


@pytest.mark.parametrize("kind", ["datasets", "maps"])
def test_an_object_transferred_in_geolens_keeps_its_owner_after_an_arcgis_change(
    runner, tmp_path, geolens, handled, kind
):
    item = _item(L1) if kind == "datasets" else _item(M1, "import_map")
    object_id = _created_id(item["id"])
    objects = _owned(geolens, **{kind: (object_id,)})
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    assert _run(runner, tmp_path, _plan([item], BOB_OWNERS))[0].exit_code == 0
    # An admin gives it to vic in GeoLens.
    objects[object_id] = {"created_by": VIC, "updated_at": "2026-10-08T00:00:00Z"}

    result, payload = _run(
        runner,
        tmp_path,
        _plan([_moved_to_bob(item)], BOB_OWNERS),
        "--cutover",
        "--accept-incomplete-inventory",
    )

    assert result.exit_code == 1
    assert _owner_patches(geolens) == [ALICE]
    assert objects[object_id]["created_by"] == VIC
    [failed] = payload["handover_failed"]
    assert "changed in GeoLens since the last run" in failed
    assert payload["owner_changed"] == [{"item": item["id"], "owner": "newbie"}]
    assert "unresolved-users" in payload["cutover"]["refused"]
    entry = _state(tmp_path)["items"][item["id"]]
    assert (entry["owner_id"], entry["portal_owner"]) == (ALICE, "agol_alice")


def test_an_arcgis_owner_change_keeps_the_target_owner_the_operator_set(
    runner, tmp_path, geolens, handled
):
    _owned(geolens, datasets=(_created_id(L1),))
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    item = _item(L1, target_owner="alice")
    assert _run(runner, tmp_path, _plan([item], BOB_OWNERS))[0].exit_code == 0

    result, payload = _run(runner, tmp_path, _plan([_moved_to_bob(item)], BOB_OWNERS))

    assert result.exit_code == 0, result.output
    assert _owner_patches(geolens) == [ALICE]
    assert payload["owner_conflicts"] == [
        {"item": L1, "portal_owner": "agol_bob", "owner": "alice"}
    ]
    assert payload["owner_changed"] == []
    assert _state(tmp_path)["items"][L1]["portal_owner"] == "agol_alice"
    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    assert {
        "item": L1,
        "kind": "owner_conflict",
        "text": "its ArcGIS owner is now agol_bob, but the plan's target.owner "
        "keeps it with alice",
    } in report["follow_ups"]


def test_a_map_given_away_in_geolens_keeps_its_baseline_after_a_matching_arcgis_change(
    runner, tmp_path, geolens, handled
):
    map_id = _created_id(M1)
    objects = _owned(geolens, maps=(map_id,))
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    owner_map = {**BOB_OWNERS, "agol_carol": "operator"}
    item = _item(M1, "import_map")
    assert _run(runner, tmp_path, _plan([item], owner_map))[0].exit_code == 0
    # An admin gives the map to newbie in GeoLens.
    objects[map_id] = {"created_by": NEW, "updated_at": "2026-10-08T00:00:00Z"}

    result, _ = _run(runner, tmp_path, _plan([_moved_to_bob(item)], owner_map))
    assert result.exit_code == 0, result.output
    assert _state(tmp_path)["items"][M1]["owner_id"] == NEW

    result, payload = _run(
        runner, tmp_path, _plan([{**item, "owner": "agol_carol"}], owner_map)
    )

    assert result.exit_code == 1
    assert _owner_patches(geolens) == [ALICE]
    assert objects[map_id]["created_by"] == NEW
    [failed] = payload["handover_failed"]
    assert "changed in GeoLens since the last run" in failed


@pytest.mark.parametrize("name", ["operator", "OPERATOR", "operator@example.org"])
def test_a_waiting_item_whose_owner_it_already_has_follows_the_arcgis_owner(
    runner, tmp_path, geolens, handled, name
):
    _owned(geolens, datasets=(_created_id(L1),))
    _write_state(
        tmp_path,
        {
            L1: {
                "status": "done",
                "dataset_ids": [_created_id(L1)],
                "owner_id": OPERATOR,
                "owner_pending": "newbie is not a GeoLens user yet",
                "portal_owner": "agol_alice",
            }
        },
    )
    moved = _moved_to_bob(_item(L1))
    assert _run(runner, tmp_path, _plan([moved], {"agol_bob": name}))[0].exit_code == 0
    entry = _state(tmp_path)["items"][L1]
    assert (entry["portal_owner"], entry["owner_pending"]) == ("agol_bob", None)

    result, payload = _run(
        runner, tmp_path, _plan([moved], {"agol_bob": "alice"}), "--dry-run"
    )

    assert result.exit_code == 0, result.output
    assert _owner_patches(geolens) == []
    assert payload["handovers"] == [{"item": L1, "owner": "alice"}]
    assert payload["owner_changed"] == []


def test_an_unlisted_item_doesnt_follow_an_arcgis_owner_change(
    runner, tmp_path, geolens, handled
):
    _owned(geolens, datasets=(_created_id(L1),))
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    assert _run(runner, tmp_path, _plan([_item(L1)], BOB_OWNERS))[0].exit_code == 0
    unlisted = {**_moved_to_bob(_item(L1)), "unlisted": True}

    plan = {**_plan([unlisted], BOB_OWNERS), "schema_version": "2"}

    result, payload = _run(runner, tmp_path, plan)

    assert payload is not None, result.output
    assert _owner_patches(geolens) == [ALICE]
    assert payload["handovers"] == []
    assert _state(tmp_path)["items"][L1]["portal_owner"] == "agol_alice"


def test_an_incomplete_handover_of_a_removed_item_doesnt_hold_cutover(
    runner, tmp_path, geolens, handled
):
    _write_state(
        tmp_path,
        {
            L1: {
                "status": "done",
                "dataset_ids": [_created_id(L1)],
                "owner_id": ALICE,
                "handover_incomplete": True,
            }
        },
    )

    plan = {**_plan([_item(L1, removed=True)]), "schema_version": "2"}

    _result, payload = _run(runner, tmp_path, plan, "--cutover")

    assert "unresolved-users" not in payload["cutover"]["refused"]
    assert _state(tmp_path)["items"][L1]["handover_incomplete"] is True


def test_a_dry_run_lists_the_handovers_the_run_would_make(
    runner, tmp_path, geolens, handled
):
    _owned(geolens, datasets=(_created_id(L1),), maps=(_created_id(M1),))
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    items = [_item(L1), _item(M1, "import_map")]
    assert _run(runner, tmp_path, _plan(items, BOB_OWNERS))[0].exit_code == 0
    plan = _plan([_moved_to_bob(item) for item in items], BOB_OWNERS)

    _result, payload = _run(runner, tmp_path, plan, "--dry-run")
    _result, only = _run(runner, tmp_path, plan, "--dry-run", "--only", M1)
    path = tmp_path / "arcgis-migration-plan.json"
    text = runner.invoke(app, ["arcgis", "migrate", str(path), "--dry-run"])

    assert payload["handovers"] == [
        {"item": L1, "owner": "newbie"},
        {"item": M1, "owner": "newbie"},
    ]
    assert only["handovers"] == [{"item": M1, "owner": "newbie"}]
    assert f"{L1} would be handed to newbie" in text.output
    assert _owner_patches(geolens) == [ALICE, ALICE]


def test_a_target_owner_set_after_migration_is_applied_after_an_arcgis_change(
    runner, tmp_path, geolens, handled
):
    _owned(geolens, datasets=(_created_id(L1),))
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    assert _run(runner, tmp_path, _plan([_item(L1)], BOB_OWNERS))[0].exit_code == 0
    item = _moved_to_bob(_item(L1, target_owner="newbie"))

    result, payload = _run(runner, tmp_path, _plan([item], BOB_OWNERS))

    assert result.exit_code == 0, result.output
    assert _owner_patches(geolens) == [ALICE, NEW]
    assert payload["owner_changed"] == []


def test_an_owner_map_edit_after_migration_hands_the_item_over(
    runner, tmp_path, geolens, handled
):
    _owned(geolens, datasets=(_created_id(L1),))
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    assert _run(runner, tmp_path, _plan([_item(L1)]))[0].exit_code == 0

    result, payload = _run(
        runner, tmp_path, _plan([_item(L1)], owner_map={"agol_alice": "newbie"})
    )

    assert result.exit_code == 0, result.output
    assert _owner_patches(geolens) == [ALICE, NEW]
    assert payload["owner_changed"] == []
    assert _state(tmp_path)["items"][L1]["owner_id"] == NEW

    # A rerun with no further edit queues nothing.
    result, payload = _run(
        runner, tmp_path, _plan([_item(L1)], owner_map={"agol_alice": "newbie"})
    )
    assert result.exit_code == 0, result.output
    assert _owner_patches(geolens) == [ALICE, NEW]
    assert payload["handed_over"] == []


def test_a_cutover_hands_over_an_owner_map_edit_before_checking_owners(
    runner, tmp_path, geolens, handled, refreshed
):
    _owned(geolens, datasets=(_created_id(L1),))
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    assert _run(runner, tmp_path, _plan([_item(L1)]))[0].exit_code == 0

    result, payload = _run(
        runner,
        tmp_path,
        _plan([_item(L1)], owner_map={"agol_alice": "newbie"}),
        "--cutover",
        "--accept-incomplete-inventory",
    )

    assert "unresolved-users" not in payload["cutover"]["refused"]
    assert _owner_patches(geolens) == [ALICE, NEW]


def test_an_arcgis_owner_change_to_an_inactive_user_is_reported(
    runner, tmp_path, geolens, handled
):
    _owned(geolens, datasets=(_created_id(L1),))
    owners = {**BOB_OWNERS, "agol_bob": "gone"}
    assert _run(runner, tmp_path, _plan([_item(L1)], owners))[0].exit_code == 0

    result, payload = _run(runner, tmp_path, _plan([_moved_to_bob(_item(L1))], owners))

    assert _owner_patches(geolens) == [ALICE]
    assert payload["owner_unresolved"] == [
        {"item": L1, "reason": "gone is not an active GeoLens user"}
    ]
    assert _state(tmp_path)["items"][L1]["owner_id"] == ALICE


def test_an_owner_map_edit_to_an_inactive_user_is_reported_and_moves_nothing(
    runner, tmp_path, geolens, handled
):
    _owned(geolens, datasets=(_created_id(L1),))
    assert _run(runner, tmp_path, _plan([_item(L1)]))[0].exit_code == 0

    result, payload = _run(
        runner, tmp_path, _plan([_item(L1)], owner_map={"agol_alice": "gone"})
    )

    assert _owner_patches(geolens) == [ALICE]
    assert payload["owner_unresolved"] == [
        {"item": L1, "reason": "gone is not an active GeoLens user"}
    ]
    assert payload["handovers"] == []
    assert _state(tmp_path)["items"][L1]["owner_id"] == ALICE


def _owner_changed_in_reports(tmp_path, item_id: str) -> None:
    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    assert (item_id, "owner_changed") in {
        (f["item"], f["kind"]) for f in report["follow_ups"]
    }
    assert item_id in (tmp_path / "arcgis-migration-report.md").read_text()


@pytest.mark.parametrize("error", [KeyboardInterrupt, RuntimeError])
def test_an_interrupted_handover_still_reports_the_unapplied_owner_change(
    runner, tmp_path, geolens, handled, monkeypatch, error
):
    _owned(geolens, datasets=(_created_id(L1),))
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    assert _run(runner, tmp_path, _plan([_item(L1)]))[0].exit_code == 0

    def interrupted(*args, **kwargs):
        raise error

    monkeypatch.setattr(migrate, "transfer_dataset", interrupted)
    _run(runner, tmp_path, _plan([_item(L1)], owner_map={"agol_alice": "newbie"}))

    _owner_changed_in_reports(tmp_path, L1)


def test_an_only_run_interrupted_on_another_item_reports_the_unapplied_owner_change(
    runner, tmp_path, geolens, handled, monkeypatch
):
    _owned(geolens, datasets=(_created_id(L1),))
    _users(geolens, _user(NEW, "newbie", ["editor"]))
    assert _run(runner, tmp_path, _plan([_item(L1)]))[0].exit_code == 0

    def interrupted(ctx, item, entry):
        raise KeyboardInterrupt

    monkeypatch.setitem(migrate.HANDLERS, "import_layers", interrupted)
    plan = _plan([_item(L1), _item(L2)], owner_map={"agol_alice": "newbie"})
    result, _ = _run(runner, tmp_path, plan, "--only", L2)

    assert result.exit_code == 130
    _owner_changed_in_reports(tmp_path, L1)


@pytest.mark.parametrize("version", ["1", "2"])
def test_v1_and_v2_plans_run_alike(runner, tmp_path, geolens, handled, version):
    _allow_transfers(geolens, _created_id(L1))
    plan = {**_plan([_item(L1)]), "schema_version": version}

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert handled == [L1]
    assert payload["counts"] == {"done": 1}


def test_a_rerun_leaves_what_a_removed_or_finished_item_migrated_alone(
    runner, tmp_path, geolens, handled
):
    # L2 failed part way and is gone from the portal: rerunning it would
    # reapply the plan's metadata and owner to datasets edited in GeoLens.
    _write_state(
        tmp_path,
        {
            L1: {"status": "done", "owner_id": ALICE, "dataset_ids": [_created_id(L1)]},
            L2: {"status": "failed", "error": "boom", "dataset_ids": [_created_id(L2)]},
        },
    )
    renamed = _item(L1)
    renamed["target"]["title"] = "Renamed in the portal"
    plan = {
        **_plan([renamed, _item(L2, removed=True), _item(M1, removed=True)]),
        "schema_version": "2",
    }

    result, payload = _run(runner, tmp_path, plan)

    assert handled == []
    assert payload["items"] == []
    assert [s for s in geolens.seen if s.method != "GET"] == []
    state = _state(tmp_path)["items"]
    assert state[L2]["dataset_ids"] == [_created_id(L2)]
    assert M1 not in state
    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    removed = {
        f["item"]: f["text"] for f in report["follow_ups"] if f["kind"] == "removed"
    }
    assert removed == {
        L2: "gone from the portal; what it migrated stays in GeoLens",
        M1: "gone from the portal before it was migrated",
    }
    assert result.exit_code == 1  # L2 is still failed


def _v2(items: list[dict], **kwargs: Any) -> dict:
    return {**_plan(items, **kwargs), "schema_version": "2"}


def _follow_ups(tmp_path: Path, kind: str) -> dict[str, str]:
    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    return {f["item"]: f["text"] for f in report["follow_ups"] if f["kind"] == kind}


def test_a_removed_dependency_that_never_migrated_holds_nothing_back(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L2))
    plan = _v2([_item(L1, removed=True), _item(L2, depends_on=[L1])])

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert handled == [L2]
    assert payload["waiting"] == []
    assert _follow_ups(tmp_path, "unresolved_dependency") == {
        L2: f"depends on {L1}, gone from the portal before it was migrated"
    }


def test_an_unlisted_item_is_left_pending_not_failed(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L2))
    plan = _v2([_item(L1, unlisted=True), _item(L2)])

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 1
    assert handled == [L2]
    assert payload["unlisted"] == [L1]
    assert payload["failed"] == []
    assert _state(tmp_path)["items"].get(L1, {}).get("status", "pending") == "pending"
    assert L1 in _follow_ups(tmp_path, "unlisted")


def test_only_naming_a_removed_item_says_why(runner, tmp_path, geolens, handled):
    result, _ = _run(runner, tmp_path, _v2([_item(L1, removed=True)]), "--only", L1)
    assert result.exit_code == 2
    assert "marked removed" in result.output + result.stderr
    assert handled == []


def test_a_removed_item_gets_no_run_or_owner_follow_ups(
    runner, tmp_path, geolens, handled, monkeypatch
):
    monkeypatch.delitem(migrate.HANDLERS, "import_map")
    _write_state(tmp_path, {M1: {"status": "done", "owner_id": ALICE}})
    plan = _v2(
        [
            _item(L1, "import_map", removed=True, depends_on=[L2]),
            _item(L2, unlisted=True),
            _item(M1, removed=True),
        ],
        owner_map={"agol_alice": "operator"},
    )

    result, payload = _run(runner, tmp_path, plan)

    assert payload["owner_changed"] == []
    assert payload["not_available"] == []
    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    kinds = {(f["item"], f["kind"]) for f in report["follow_ups"]}
    assert kinds == {(L1, "removed"), (L2, "unlisted"), (M1, "removed")}
    assert result.exit_code == 1  # L2 is left pending


def test_an_unlisted_items_owner_is_not_checked(runner, tmp_path, geolens, handled):
    _allow_transfers(geolens, _created_id(L2))
    plan = _v2([_item(L1, unlisted=True, owner="agol_nobody"), _item(L2)])

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 1, result.output
    assert handled == [L2]
    assert payload["unlisted"] == [L1]


def test_only_does_not_reach_through_a_removed_dependency(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    plan = _v2(
        [
            _item(L1, depends_on=[L2]),
            _item(L2, removed=True, depends_on=[M1]),
            _item(M1),
        ]
    )

    result, _ = _run(runner, tmp_path, plan, "--only", L1)

    assert result.exit_code == 0, result.output
    assert handled == [L1]


def test_a_cycle_through_a_removed_item_does_not_block_the_run(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    plan = _v2([_item(L1, depends_on=[L2]), _item(L2, removed=True, depends_on=[L1])])

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert handled == [L1]


def test_an_unlisted_items_stale_dependencies_form_no_cycle(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(M1))
    plan = _v2(
        [
            _item(L1, depends_on=[L2]),
            _item(L2, unlisted=True, depends_on=[L1]),
            _item(M1),
        ]
    )

    result, payload = _run(runner, tmp_path, plan)

    assert handled == [M1]
    assert payload["unlisted"] == [L2]
    assert payload["waiting"] == [{"item": L1, "waiting_on": [L2]}]
    assert result.exit_code == 1


def test_only_does_not_reach_through_an_unlisted_dependency(
    runner, tmp_path, geolens, handled
):
    plan = _v2(
        [
            _item(L1, depends_on=[L2]),
            _item(L2, unlisted=True, depends_on=[M1]),
            _item(M1),
        ]
    )

    result, payload = _run(runner, tmp_path, plan, "--only", L1)

    assert handled == []
    assert payload["unlisted"] == [L2]
    assert payload["waiting"] == [{"item": L1, "waiting_on": [L2]}]
    assert result.exit_code == 1


def test_an_unlisted_item_gets_only_its_unlisted_follow_up(
    runner, tmp_path, geolens, handled, monkeypatch
):
    monkeypatch.delitem(migrate.HANDLERS, "import_map")
    missing = "ff" * 16
    plan = _v2(
        [
            _item(L1, "import_map", unlisted=True, depends_on=[L2, missing]),
            _item(L2, unlisted=True),
        ]
    )

    _run(runner, tmp_path, plan)

    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    assert {(f["item"], f["kind"]) for f in report["follow_ups"]} == {
        (L1, "unlisted"),
        (L2, "unlisted"),
    }


def test_a_dry_run_classifies_items_as_the_run_does(
    runner, tmp_path, geolens, handled, monkeypatch
):
    monkeypatch.delitem(migrate.HANDLERS, "import_map")
    plan = _v2(
        [
            _item(L1, "import_map", unlisted=True),
            _item(L2, "import_map"),
            _item(M1, "skip", unlisted=True),
            _item(S1, removed=True),
        ]
    )

    _, dry = _run(runner, tmp_path, plan, "--dry-run")
    _, run = _run(runner, tmp_path, plan)

    for payload in (dry, run):
        assert payload["unlisted"] == [L1]
        assert payload["not_available"] == [L2]


def test_a_dry_run_lists_unlisted_items(runner, tmp_path, geolens, handled):
    result, payload = _run(
        runner, tmp_path, _v2([_item(L1, unlisted=True)]), "--dry-run"
    )
    assert payload["unlisted"] == [L1]
    assert result.exit_code == 1


def test_a_removed_dependency_gets_one_note_and_none_on_removed_items(
    runner, tmp_path, geolens, handled, monkeypatch
):
    monkeypatch.delitem(migrate.HANDLERS, "import_map")
    plan = _v2(
        [
            _item(L1, removed=True),
            _item(M1, "import_map", depends_on=[L1]),
            _item(L2, removed=True, depends_on=[L1]),
        ]
    )

    _run(runner, tmp_path, plan)

    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    notes = [
        (f["item"], f["kind"], f["text"])
        for f in report["follow_ups"]
        if f["kind"] != "removed"
    ]
    assert notes == [
        (M1, "not_available", "the import_map action can't run yet"),
        (
            M1,
            "unresolved_dependency",
            f"depends on {L1}, gone from the portal before it was migrated",
        ),
    ]


def test_ids_a_handler_recorded_survive_its_failure(
    runner, tmp_path, geolens, monkeypatch
):
    def handler(ctx, item, entry):
        entry.dataset_ids.append(_created_id(L1))
        ctx.save()
        raise migrate.ItemFailed("the second layer failed")

    _install(monkeypatch, handler)

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))

    assert result.exit_code == 1
    entry = _state(tmp_path)["items"][L1]
    assert entry["status"] == "failed"
    assert entry["dataset_ids"] == [_created_id(L1)]


def test_ids_a_handler_saved_survive_a_crash(runner, tmp_path, geolens, monkeypatch):
    def handler(ctx, item, entry):
        entry.dataset_ids.append(_created_id(L1))
        ctx.save()
        raise SystemExit(9)

    _install(monkeypatch, handler)

    _run(runner, tmp_path, _plan([_item(L1)]))

    assert _state(tmp_path)["items"][L1]["dataset_ids"] == [_created_id(L1)]


def test_an_item_that_depends_on_itself_still_runs(runner, tmp_path, geolens, handled):
    _allow_transfers(geolens, _created_id(L1))
    result, _ = _run(runner, tmp_path, _plan([_item(L1, depends_on=[L1])]))
    assert result.exit_code == 0, result.output
    assert handled == [L1]


def test_a_refreshed_access_token_is_redacted_too(fake_geolens, monkeypatch):
    from geolens.api.auth import me_auth_me_get

    from geolens_cli._sdk_helpers import make_client
    from geolens_cli.arcgis_migrate_session import GeoLens
    from geolens_cli.arcgis_portal import Redactor

    renewed = secrets.token_urlsafe(24)
    monkeypatch.setattr("geolens_cli.auth.try_refresh", lambda instance: renewed)
    replies = [
        (401, {"title": "Unauthorized", "status": 401, "detail": "expired"}),
        _user(OPERATOR, "operator", ["admin"]),
    ]
    fake_geolens.routes["GET /auth/me/"] = lambda seen: replies.pop(0)
    sdk = make_client(
        "https://geolens.example.org/api",
        bearer_token=fake_geolens.token,
        provenance="stored-bearer",
    )
    redact = Redactor()
    session = GeoLens(sdk, "https://geolens.example.org/api", redact)

    session.call(me_auth_me_get.sync_detailed)

    assert fake_geolens.seen[-1].headers["authorization"] == f"Bearer {renewed}"
    assert redact(f"echo {renewed} and {fake_geolens.token}") == (
        "echo [REDACTED] and [REDACTED]"
    )


def test_a_name_that_is_one_users_email_and_anothers_username_is_refused(
    runner, tmp_path, geolens, handled
):
    users = geolens.routes["GET /admin/users/"]["users"]
    impostor = _user("00000000-0000-0000-0000-0000000000a9", "x", ["editor"])
    impostor["email"] = "Alice"
    geolens.routes["GET /admin/users/"] = {"users": [*users, impostor], "total": 5}

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))

    assert result.exit_code == 2
    assert "matches more than one GeoLens user" in result.output
    assert handled == []


def test_stored_role_overrides_apply_over_the_built_in_grants(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    geolens.routes["GET /settings/all/"] = _settings(
        {"admin": {"manage_users": True, "manage_settings": True}}
    )

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))

    assert result.exit_code == 0, result.output
    assert _state(tmp_path)["items"][L1]["owner_id"] == ALICE


@pytest.mark.parametrize(("status", "code"), [(401, 3), (403, 3), (500, 5), (404, 1)])
def test_a_preflight_failure_keeps_the_cli_exit_codes_and_redacts(
    runner, tmp_path, geolens, handled, status, code
):
    geolens.routes["GET /admin/users/"] = (
        status,
        {"title": "Error", "status": status, "detail": f"echo {geolens.token}"},
    )

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))

    assert result.exit_code == code
    assert geolens.token not in result.output
    # A 401 on GEOLENS_TOKEN ends in the shared reauth refusal instead.
    assert status == 401 or "echo [REDACTED]" in result.output


def test_an_empty_target_owner_does_not_fall_back_to_owner_map(
    runner, tmp_path, geolens, handled
):
    result, _ = _run(runner, tmp_path, _plan([_item(L1, target_owner="")]))
    assert result.exit_code == 2
    assert "has no GeoLens owner" in result.output
    assert handled == []


def test_a_dry_run_names_actions_this_version_cannot_run(
    runner, tmp_path, geolens, monkeypatch
):
    monkeypatch.delitem(migrate.HANDLERS, "import_map")
    plan = _plan([_item(L1, "import_map"), _item(S1, "skip")])

    result, payload = _run(runner, tmp_path, plan, "--dry-run")

    assert result.exit_code == 1
    assert payload["not_available"] == [L1]


def test_an_owner_without_the_grant_is_kept_with_a_warning(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
    plan = _plan([_item(L1)], owner_map={"agol_alice": "vic"})

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert payload["items"][0]["owner"] == "vic"
    assert payload["owner_warnings"] == [
        f"{L1}: vic's roles (viewer) don't grant upload"
    ]
    assert [s.json() for s in geolens.seen if s.method == "PATCH"] == [
        {"owner_id": VIC, "expected_updated_at": READ_AT}
    ]


def test_a_second_run_on_the_same_state_file_is_refused(tmp_path):
    from geolens_cli.arcgis_migrate_state import MigrationState, StateError
    from geolens_cli.arcgis_portal import Redactor

    path = tmp_path / "arcgis-migration-state.json"
    first = MigrationState.load(path, PORTAL, GEOLENS_INSTANCE, Redactor())
    with pytest.raises(StateError, match="another `geolens arcgis migrate` run"):
        MigrationState.load(path, PORTAL, GEOLENS_INSTANCE, Redactor())
    MigrationState.load(path, PORTAL, GEOLENS_INSTANCE, Redactor(), persist=False)
    release_locks()
    MigrationState.load(path, PORTAL, GEOLENS_INSTANCE, Redactor())
    release_locks()
    assert first.path == path


def test_the_lock_is_released_when_a_run_stops_on_an_error(
    runner, tmp_path, geolens, monkeypatch
):
    def handler(ctx, item, entry):
        raise typer.Exit(4)

    _install(monkeypatch, handler)
    _run(runner, tmp_path, _plan([_item(L1)]))

    result, _ = _run(runner, tmp_path, _plan([_item(L1)]), "--dry-run")
    assert "another `geolens arcgis migrate` run" not in result.output
    from geolens_cli.arcgis_migrate_state import MigrationState
    from geolens_cli.arcgis_portal import Redactor

    MigrationState.load(
        tmp_path / "arcgis-migration-state.json", PORTAL, GEOLENS_INSTANCE, Redactor()
    )
    release_locks()


def test_the_state_file_is_locked_where_flock_is_missing(tmp_path, monkeypatch):
    import sys
    import types

    from geolens_cli.arcgis_migrate_state import MigrationState, StateError
    from geolens_cli.arcgis_portal import Redactor

    held: set[str] = set()

    def locking(fd, mode, length):
        key = str(os.fstat(fd).st_ino)
        if key in held:
            raise OSError("locked")
        held.add(key)

    fake = types.SimpleNamespace(LK_NBLCK=2, locking=locking)
    monkeypatch.setitem(sys.modules, "fcntl", None)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    path = tmp_path / "arcgis-migration-state.json"

    MigrationState.load(path, PORTAL, GEOLENS_INSTANCE, Redactor())
    with pytest.raises(StateError, match="another `geolens arcgis migrate` run"):
        MigrationState.load(path, PORTAL, GEOLENS_INSTANCE, Redactor())
    release_locks()


def test_a_state_file_that_is_not_utf8_is_a_usage_error(runner, tmp_path, geolens):
    (tmp_path / "arcgis-migration-state.json").write_bytes(b"\xff\xfe\x00garbage")
    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))
    assert result.exit_code == 2 and "not UTF-8 text" in result.output


@pytest.mark.parametrize(
    ("version", "says"),
    [("99", "written by a newer geolens-cli"), ("x", "unknown schema_version")],
)
def test_a_state_file_from_a_newer_cli_says_to_upgrade(
    runner, tmp_path, geolens, handled, version, says
):
    (tmp_path / "arcgis-migration-state.json").write_text(
        json.dumps(
            {
                "schema_version": version,
                "portal_url": PORTAL,
                "geolens_instance": GEOLENS_INSTANCE,
                "items": {},
            }
        )
    )
    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))
    assert result.exit_code == 2
    assert says in result.output
    assert handled == []


def test_no_configured_instance_stays_a_usage_error(
    runner, tmp_path, tmp_xdg_home, monkeypatch
):
    for name in ("GEOLENS_INSTANCE", "GEOLENS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))
    assert result.exit_code == 2
    assert "No instance configured" in result.output


def test_a_dataset_share_refused_while_a_map_needs_the_group_is_retried_after_maps(
    monkeypatch, tmp_path
):
    from geolens_cli.arcgis_migrate_state import MigrationState
    from geolens_cli.arcgis_portal import Redactor

    narrowed: list[bool] = []
    calls: list[str] = []

    def share(ctx, item, entry, *, with_map=True):
        calls.append(item["id"])
        if item["action"] == "import_map":
            narrowed.append(True)
        elif not narrowed:
            raise migrate.ItemFailed(
                "sharing it with its GeoLens groups failed, Cannot restrict "
                "visibility: dataset is used in shared maps: m"
            )
        return []

    monkeypatch.setattr(migrate, "share", share)
    state = MigrationState(
        tmp_path / "state.json", PORTAL, GEOLENS_INSTANCE, Redactor(), persist=False
    )
    items = [_item(L1), _item(M1, "import_map")]
    for item in items:
        state.items[item["id"]] = migrate.ItemState(status="done")
    summary = migrate.RunSummary()

    migrate.refresh_finished(SimpleNamespace(sharing=None), state, items, summary)

    assert calls == [L1, M1, L1]
    assert state.items[L1].stale == [] and state.items[M1].stale == []


def test_a_share_refused_again_after_the_maps_keeps_its_first_reason(
    monkeypatch, tmp_path
):
    from geolens_cli.arcgis_migrate_state import MigrationState
    from geolens_cli.arcgis_portal import Redactor

    answers = iter(["changed in GeoLens while it was shared", "something else"])

    def share(ctx, item, entry, *, with_map=True):
        raise migrate.ItemFailed(next(answers))

    monkeypatch.setattr(migrate, "share", share)
    state = MigrationState(
        tmp_path / "state.json", PORTAL, GEOLENS_INSTANCE, Redactor(), persist=False
    )
    state.items[L1] = migrate.ItemState(status="done")

    migrate.refresh_finished(
        SimpleNamespace(sharing=None), state, [_item(L1)], migrate.RunSummary()
    )

    assert state.items[L1].stale == ["changed in GeoLens while it was shared"]
