"""`geolens arcgis migrate`: plan order, state file, resume and owner mapping."""

from __future__ import annotations

import json
import secrets
import stat
from pathlib import Path
from typing import Any

import pytest

from geolens_cli import arcgis_migrate as migrate
from geolens_cli.main import app

PORTAL = "https://examplecounty.maps.arcgis.com"
OPERATOR = "00000000-0000-0000-0000-0000000000a0"
ALICE = "00000000-0000-0000-0000-0000000000a1"
VIC = "00000000-0000-0000-0000-0000000000a2"
GONE = "00000000-0000-0000-0000-0000000000a3"
L1, L2, M1, S1 = "11" * 16, "22" * 16, "33" * 16, "44" * 16
NOW = "2026-10-01T00:00:00Z"


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
    for map_id in map_ids:
        fake.routes[f"PATCH /maps/{map_id}"] = lambda seen, m=map_id: _map(
            m, seen.json()["owner_id"]
        )


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


def _write_state(tmp_path: Path, items: dict[str, dict]) -> None:
    (tmp_path / "arcgis-migration-state.json").write_text(
        json.dumps({"schema_version": "1", "portal_url": PORTAL, "items": items})
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
    _allow_transfers(geolens, _created_id(L2), _created_id(S1))
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
    assert result.exit_code == 0 and handled == []

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
    (tmp_path / "arcgis-migration-state.json").write_text(
        json.dumps(
            {"schema_version": "1", "portal_url": "https://other.example", "items": {}}
        )
    )
    result, _ = _run(runner, tmp_path, _plan([_item(L1)]))
    assert result.exit_code == 2 and "other.example" in result.output
    assert handled == []


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
        }
    ]
    assert not (tmp_path / "arcgis-migration-state.json").exists()
    assert handled == []
    assert all(s.method == "GET" for s in geolens.seen)


def test_an_action_without_a_handler_is_left_pending(runner, tmp_path, geolens):
    plan = _plan([_item(L1), _item(M1, "import_map", depends_on=[L1])])

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
        ("datasets", {"owner_id": ALICE}),
        ("maps", {"owner_id": ALICE}),
    ]
    assert _state(tmp_path)["items"][L1]["owner_id"] == ALICE


def test_items_owned_by_the_operator_are_not_transferred(
    runner, tmp_path, geolens, handled
):
    plan = _plan([_item(L1)], owner_map={"agol_alice": "operator@example.org"})

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert [s for s in geolens.seen if s.method == "PATCH"] == []
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
        ({"agol_alice": "vic"}, "don't grant upload"),
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
        owner_map={"agol_alice": "vic", "agol_bob": ""},
    )

    result, payload = _run(runner, tmp_path, plan, "--unmapped-owner", "alice")

    assert result.exit_code == 0, result.output
    assert [r["owner"] for r in payload["items"]] == ["alice", "alice"]
    assert len(payload["owner_reassigned"]) == 2


def test_unmapped_owner_does_not_cover_an_unknown_name(
    runner, tmp_path, geolens, handled
):
    plan = _plan([_item(L1)], owner_map={"agol_alice": "nobody"})
    result, _ = _run(runner, tmp_path, plan, "--unmapped-owner", "alice")
    assert result.exit_code == 2 and handled == []


def test_an_unusable_unmapped_owner_is_refused(runner, tmp_path, geolens, handled):
    plan = _plan([_item(L1)], owner_map={"agol_alice": ""})
    result, _ = _run(runner, tmp_path, plan, "--unmapped-owner", "vic")
    assert result.exit_code == 2 and "--unmapped-owner: vic's roles" in result.output
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


def test_a_map_owner_needs_only_edit_metadata(runner, tmp_path, geolens, handled):
    _allow_transfers(geolens, map_ids=(_created_id(M1),))
    geolens.routes["GET /settings/all/"] = _settings(
        {**DEFAULT_ROLES, "viewer": {"upload": False, "edit_metadata": True}}
    )
    owner_map = {"agol_alice": "vic"}

    result, _ = _run(runner, tmp_path, _plan([_item(M1, "import_map")], owner_map))
    assert result.exit_code == 0, result.output

    result, _ = _run(runner, tmp_path, _plan([_item(L1)], owner_map))
    assert result.exit_code == 2 and "don't grant upload" in result.output


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
