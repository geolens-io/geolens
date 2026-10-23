"""`geolens arcgis migrate`: plan order, state file, resume and owner mapping."""

from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

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
    monkeypatch.setattr(migrate, "_inventory_rows", lambda *args: ({}, None))


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
        }
    )
    return fake_geolens


def _allow_transfers(fake, *ids: str, map_ids: tuple[str, ...] = ()) -> None:
    for dataset_id in ids:
        fake.routes[f"PATCH /datasets/{dataset_id}"] = (
            lambda seen, d=dataset_id: _dataset(d, seen.json()["owner_id"])
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
            entry.map_id = _created_id(item["id"])
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
        "--cutover",
        "--accept-incomplete-inventory",
        "--accept-unfinished-items",
        "--accept-attachment-loss",
    )
    assert payload["cutover"]["refused"] == ["unresolved-users"]


def test_a_state_file_is_written_as_v2_and_v1_still_loads(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1), _created_id(L2))
    _write_state(
        tmp_path,
        {L1: {"status": "done", "dataset_ids": [_created_id(L1)], "owner_id": ALICE}},
    )

    result, _ = _run(runner, tmp_path, _plan([_item(L1), _item(L2)]))

    assert result.exit_code == 0, result.output
    assert _state(tmp_path)["schema_version"] == "2"


def test_cutover_counts_an_item_whose_plan_owner_moved_to_another_user(
    runner, tmp_path, geolens, handled
):
    _allow_transfers(geolens, _created_id(L1))
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
        runner, tmp_path, plan, "--unmapped-owner", "operator", "--cutover"
    )

    assert result.exit_code == 1
    assert "unresolved-users" in payload["cutover"]["refused"]
    [check] = [
        c for c in payload["cutover"]["checks"] if c["check"] == "unresolved-users"
    ]
    assert check["items"] == [
        {"item": L1, "reason": "newbie is not a GeoLens user yet"}
    ]


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


def test_a_non_admin_operator_is_refused(runner, tmp_path, geolens, handled):
    geolens.routes["GET /auth/me/"] = _user(ALICE, "alice", ["editor"])
    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))
    assert result.exit_code == 2 and "admin" in result.output
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


def test_an_owner_changed_after_import_is_reported_not_reimported(
    runner, tmp_path, geolens, handled
):
    _write_state(tmp_path, {L1: {"status": "done", "owner_id": ALICE}})
    plan = _plan([_item(L1)], owner_map={"agol_alice": "operator"})

    result, payload = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert handled == []
    assert payload["owner_changed"] == [{"item": L1, "owner": "operator"}]
    assert [s for s in geolens.seen if s.method == "PATCH"] == []


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


def test_no_configured_instance_stays_a_usage_error(
    runner, tmp_path, tmp_xdg_home, monkeypatch
):
    for name in ("GEOLENS_INSTANCE", "GEOLENS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))
    assert result.exit_code == 2
    assert "No instance configured" in result.output
