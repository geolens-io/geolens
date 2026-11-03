"""`geolens arcgis migrate` run by an editor on their own content."""

from __future__ import annotations

import json
from typing import Any

import pytest

from geolens_cli import arcgis_migrate as migrate

from .conftest import GEOLENS_INSTANCE
from .test_arcgis_migrate import (  # noqa: F401
    L1,
    L2,
    M1,
    ALICE,
    _map,
    PORTAL,
    READ_AT,
    _allow_transfers as _allow_any,
    _dataset,
    _created_id,
    _item,
    _plan,
    _run,
    _state,
    _user,
    _write_state,
    geolens,
    handled,
    no_inventory,
    refreshed,
)

ERIN = "00000000-0000-0000-0000-0000000000e1"
TEAM = "00000000-0000-0000-0000-0000000000f1"
OTHER = "00000000-0000-0000-0000-0000000000f2"
OWN = {"agol_alice": "erin"}


def _editors_dataset(dataset_id: str, owner: str = ERIN) -> dict[str, Any]:
    return {**_dataset(dataset_id, owner), "updated_by": ERIN}


def _allow_transfers(fake, *ids, map_ids=()):
    """Routes for datasets and maps the editor owns."""
    _allow_any(fake, *ids, map_ids=map_ids)
    for dataset_id in ids:
        fake.routes[f"GET /datasets/{dataset_id}"] = _editors_dataset(dataset_id)
    for map_id in map_ids:
        fake.routes[f"GET /maps/{map_id}"] = _map(map_id, ERIN)


@pytest.fixture
def editor(geolens):  # noqa: F811
    """The fake instance with an editor operator and no admin endpoints."""
    for route in [r for r in geolens.routes if " /admin/" in r or "/settings/all" in r]:
        del geolens.routes[route]
    geolens.routes.update(
        {
            "GET /auth/me/": _user(ERIN, "erin", ["editor"]),
            "GET /auth/me/permissions/": {
                "permissions": {"upload": True, "manage_collections": True}
            },
            "GET /groups/mine/": {"groups": [], "total": 0},
        }
    )
    return geolens


@pytest.fixture
def ran(handled):  # noqa: F811
    """The ids of the items whose handler ran."""
    return handled


def _sharing_targets(monkeypatch) -> dict[str, dict[str, Any]]:
    """The target each item is shared with, as `share` receives it."""
    seen: dict[str, dict[str, Any]] = {}

    def share(ctx, item, entry, **kwargs):
        seen[item["id"]] = item["target"]
        return []

    monkeypatch.setattr(migrate, "share", share)
    return seen


def _restricted(item_id: str, *groups: str) -> dict[str, Any]:
    item = _item(item_id)
    item["target"].update(visibility="restricted", groups=list(groups))
    return item


def _public(item_id: str) -> dict[str, Any]:
    item = _item(item_id)
    item["target"]["visibility"] = "public"
    return item


def _follow_ups(tmp_path) -> dict[str, str]:
    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    return {row["kind"]: row["item"] for row in report["follow_ups"]}


def test_an_editor_migrates_their_own_items_without_a_transfer(
    runner, tmp_path, editor, ran
):
    _allow_transfers(editor, _created_id(L1), map_ids=(_created_id(M1),))
    plan = _plan([_item(L1), _item(M1, "import_map", depends_on=[L1])], OWN)

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert ran == [L1, M1]
    assert [s for s in editor.seen if s.method == "PATCH"] == []
    assert [s for s in editor.seen if "/admin/" in s.url] == []
    items = _state(tmp_path)["items"]
    assert items[L1]["owner_id"] == items[M1]["owner_id"] == ERIN


def test_a_public_item_under_the_restriction_becomes_internal_and_is_reported(
    runner, tmp_path, editor, ran, monkeypatch
):
    editor.routes["GET /settings/feature-flags/"] = {"restrict_public_visibility": True}
    _allow_transfers(editor, _created_id(L1), _created_id(L2))
    seen = _sharing_targets(monkeypatch)
    plan = _plan([_public(L1), _item(L2)], OWN)

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert _state(tmp_path)["items"][L1]["visibility"] == {_created_id(L1): "internal"}
    assert seen[L1]["visibility"] == "internal"
    assert _follow_ups(tmp_path)["public_blocked_by_policy"] == L1


def test_a_public_item_stays_public_when_the_instance_allows_it(
    runner, tmp_path, editor, ran
):
    _allow_transfers(editor, _created_id(L1))

    result, _ = _run(runner, tmp_path, _plan([_public(L1)], OWN))

    assert result.exit_code == 0, result.output
    assert _state(tmp_path)["items"][L1]["visibility"] == {_created_id(L1): "public"}
    assert "public_blocked_by_policy" not in _follow_ups(tmp_path)


def test_collections_are_skipped_when_the_role_withholds_manage_collections(
    runner, tmp_path, editor, ran
):
    editor.routes["GET /auth/me/permissions/"] = {
        "permissions": {"upload": True, "manage_collections": False}
    }
    _allow_transfers(editor, _created_id(L1))
    item = _item(L1)
    item["target"]["collections"] = ["Roads"]

    result, _ = _run(runner, tmp_path, _plan([item], OWN))

    assert result.exit_code == 0, result.output
    assert [s for s in editor.seen if "/catalog/collections" in s.url] == []
    assert _state(tmp_path)["items"][L1]["status"] == "done"
    assert "collections" in _follow_ups(tmp_path)


@pytest.mark.parametrize("restrict", [False, True])
@pytest.mark.parametrize(
    ("mine", "group_map", "shared", "visibility"),
    [
        ([("Roads Team", TEAM)], {}, [TEAM], "restricted"),
        ([("ROADS TEAM", TEAM)], {}, [TEAM], "restricted"),
        (
            [("Roads Team", TEAM), ("Planners", OTHER)],
            {"g1": "Planners"},
            [OTHER],
            "restricted",
        ),
        ([("Planners", OTHER)], {}, [], "private"),
        ([], {}, [], "private"),
        (
            [("Roads Team", TEAM)],
            {"g1": "Not Mine"},
            [],
            "private",
        ),
        ([("Roads Team", TEAM)], {"g1": ""}, [], "private"),
    ],
    ids=[
        "title",
        "title-case",
        "group-map",
        "other-group-only",
        "no-groups",
        "mapped-group-not-mine",
        "unmapped",
    ],
)
def test_a_group_only_item_goes_to_the_editors_matching_groups_or_stays_private(
    runner,
    tmp_path,
    editor,
    ran,
    monkeypatch,
    restrict,
    mine,
    group_map,
    shared,
    visibility,
):
    editor.routes["GET /settings/feature-flags/"] = {
        "restrict_public_visibility": restrict
    }
    editor.routes["GET /groups/mine/"] = {
        "groups": [{"id": gid, "name": name} for name, gid in mine],
        "total": len(mine),
    }
    monkeypatch.setattr(
        migrate,
        "_inventory_rows",
        lambda *args: ({}, None, {"g1": {"id": "g1", "title": "Roads Team"}}),
    )
    _allow_transfers(editor, _created_id(L1))
    seen = _sharing_targets(monkeypatch)
    plan = {**_plan([_restricted(L1, "g1")], OWN), "schema_version": "2"}
    plan["group_map"] = {
        "g1": {
            "collection": "Roads Team",
            "visibility": "private",
            "geolens_group": group_map.get("g1"),
        }
    }

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert seen[L1]["visibility"] == visibility
    assert seen[L1]["geolens_groups"] == shared
    assert visibility not in ("internal", "public") or shared
    assert [s for s in editor.seen if "/admin/" in s.url] == []
    assert [s for s in editor.seen if s.method in ("POST", "PUT")] == []
    kinds = _follow_ups(tmp_path)
    assert ("private_no_matching_group" in kinds) == (visibility == "private")


def test_a_plan_naming_another_owner_needs_an_admin(runner, tmp_path, editor, ran):
    plan = _plan([_item(L1), _item(L2, owner="agol_vic")], {**OWN, "agol_vic": "vic"})

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 2
    assert "admin" in result.output and "vic" in result.output
    assert ran == []
    assert [s for s in editor.seen if s.method != "GET"] == []


@pytest.mark.parametrize("owner_map", [{}, {"agol_alice": ""}])
def test_an_item_with_no_owner_needs_an_admin(runner, tmp_path, editor, ran, owner_map):
    result, _ = _run(runner, tmp_path, _plan([_item(L1)], owner_map))

    assert result.exit_code == 2 and ran == []


def test_unmapped_owner_naming_someone_else_needs_an_admin(
    runner, tmp_path, editor, ran
):
    result, _ = _run(
        runner, tmp_path, _plan([_item(L1)], OWN), "--unmapped-owner", "vic"
    )

    assert result.exit_code == 2 and ran == []


def test_an_editors_map_is_recorded_as_left_so_a_rerun_can_change_its_groups(
    runner, tmp_path, editor, ran
):
    _allow_transfers(editor, map_ids=(_created_id(M1),))
    editor.routes[f"GET /maps/{_created_id(M1)}"] = _map(_created_id(M1), ERIN)

    result, _ = _run(runner, tmp_path, _plan([_item(M1, "import_map")], OWN))

    assert result.exit_code == 0, result.output
    assert _state(tmp_path)["items"][M1]["map_snapshot"] == {
        "owner": ERIN,
        "updated_at": READ_AT,
    }
    assert [s for s in editor.seen if s.method == "PATCH"] == []


ADMIN_GROUP = {
    "id": TEAM,
    "name": "Roads Team",
    "created": True,
    "added": [ALICE],
    "joined": {ALICE: ["agol_alice"]},
}


@pytest.mark.parametrize(
    ("mine", "named"),
    [
        ([("Roads Team", OTHER)], None),
        ([], None),
        ([("Roads Team", TEAM)], "Roads Team"),
    ],
    ids=["other-match", "no-match", "same-group"],
)
def test_an_editor_run_keeps_the_group_record_an_admin_run_made(
    runner, tmp_path, editor, ran, monkeypatch, mine, named
):
    editor.routes["GET /groups/mine/"] = {
        "groups": [{"id": gid, "name": name} for name, gid in mine],
        "total": len(mine),
    }
    monkeypatch.setattr(
        migrate,
        "_inventory_rows",
        lambda *args: ({}, None, {"g1": {"id": "g1", "title": "Roads Team"}}),
    )
    _sharing_targets(monkeypatch)
    _allow_transfers(editor, _created_id(L1))
    path = tmp_path / "arcgis-migration-state.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "portal_url": PORTAL,
                "geolens_instance": GEOLENS_INSTANCE,
                "items": {},
                "groups": {"g1": ADMIN_GROUP},
            }
        )
    )
    plan = {**_plan([_restricted(L1, "g1")], OWN), "schema_version": "2"}
    plan["group_map"] = {
        "g1": {
            "collection": "Roads Team",
            "visibility": "private",
            "geolens_group": named,
        }
    }

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert _state(tmp_path)["groups"]["g1"] == ADMIN_GROUP


def test_a_rerun_leaves_a_dataset_edited_in_geolens_alone(
    runner, tmp_path, editor, ran, monkeypatch
):
    editor.routes["GET /groups/mine/"] = {
        "groups": [{"id": TEAM, "name": "Roads Team"}],
        "total": 1,
    }
    monkeypatch.setattr(
        migrate,
        "_inventory_rows",
        lambda *args: ({}, None, {"g1": {"id": "g1", "title": "Roads Team"}}),
    )
    dataset_id = _created_id(L1)
    _allow_transfers(editor, dataset_id)
    editor.routes[f"PUT /datasets/{dataset_id}/groups/"] = {}
    plan = {**_plan([_item(L1)], OWN), "schema_version": "2"}
    plan["group_map"] = {
        "g1": {
            "collection": "Roads Team",
            "visibility": "private",
            "geolens_group": None,
        }
    }

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert list(_state(tmp_path)["items"][L1]["last_update"]) == [dataset_id]

    edited = {**_editors_dataset(dataset_id), "updated_at": "2026-10-02T00:00:00Z"}
    editor.routes[f"GET /datasets/{dataset_id}"] = edited
    plan["items"] = [_restricted(L1, "g1")]
    _run(runner, tmp_path, plan)

    assert [s for s in editor.seen if s.method == "PUT"] == []
    assert "changed in GeoLens" in " ".join(_state(tmp_path)["items"][L1]["stale"])


@pytest.mark.parametrize("kind", ["dataset", "map"])
def test_an_item_an_admin_run_handed_to_someone_else_is_left_for_an_admin(
    runner, tmp_path, editor, ran, kind
):
    created = _created_id(L1 if kind == "dataset" else M1)
    _allow_transfers(
        editor,
        *([created] if kind == "dataset" else []),
        map_ids=((created,) if kind == "map" else ()),
    )
    if kind == "dataset":
        editor.routes[f"GET /datasets/{created}"] = _editors_dataset(created, ALICE)
        item = _item(L1)
    else:
        editor.routes[f"GET /maps/{created}"] = _map(created, ALICE)
        item = _item(M1, "import_map")

    result, _ = _run(runner, tmp_path, _plan([item], OWN))

    entry = _state(tmp_path)["items"][item["id"]]
    assert result.exit_code == 1
    assert entry["status"] == "failed" and "an admin must finish" in entry["error"]
    assert not entry.get("owner_id")


def _group_plan(visibility_item: dict[str, Any]) -> dict[str, Any]:
    plan = {**_plan([visibility_item], OWN), "schema_version": "2"}
    plan["group_map"] = {
        "g1": {
            "collection": "Roads Team",
            "visibility": "private",
            "geolens_group": None,
        }
    }
    return plan


def _team_inventory(monkeypatch, **extra: Any) -> None:
    monkeypatch.setattr(
        migrate,
        "_inventory_rows",
        lambda *args: ({}, None, {"g1": {"id": "g1", "title": "Roads Team", **extra}}),
    )


@pytest.mark.parametrize(
    ("inventory", "mentions"),
    [({}, ()), ({"members_unread": "no access"}, ("no access",))],
    ids=["read", "inventory-unread"],
)
def test_a_matched_group_is_flagged_because_its_members_cant_be_compared(
    runner, tmp_path, editor, ran, monkeypatch, inventory, mentions
):
    editor.routes["GET /groups/mine/"] = {
        "groups": [{"id": TEAM, "name": "Roads Team"}],
        "total": 1,
    }
    _team_inventory(monkeypatch, **inventory)
    _sharing_targets(monkeypatch)
    _allow_transfers(editor, _created_id(L1))

    result, _ = _run(runner, tmp_path, _group_plan(_restricted(L1, "g1")))

    assert result.exit_code == 0, result.output
    record = _state(tmp_path)["groups"]["g1"]
    assert "can't read the GeoLens group's members" in record["members_unread"]
    assert all(text in record["members_unread"] for text in mentions)
    report = json.loads((tmp_path / "arcgis-migration-report.json").read_text())
    rows = [r for r in report["follow_ups"] if r["kind"] == "under_shared"]
    assert any(r["item"] == L1 and "can't read" in r["text"] for r in rows)


def test_cutover_refuses_a_migrated_item_another_user_owns(
    runner, tmp_path, editor, ran
):
    _write_state(
        tmp_path,
        {L1: {"status": "done", "dataset_ids": [_created_id(L1)], "owner_id": ALICE}},
    )

    result, payload = _run(
        runner,
        tmp_path,
        _plan([_item(L1)], OWN),
        "--cutover",
        "--accept-incomplete-inventory",
    )

    assert payload["cutover"]["refused"] == ["unresolved-users"]
    assert payload["cutover"]["marked"] is False
    assert [u["item"] for u in payload["owner_unresolved"]] == [L1]


def test_a_rerun_that_maps_the_group_drops_the_private_note(
    runner, tmp_path, editor, ran, monkeypatch
):
    dataset_id = _created_id(L1)
    _team_inventory(monkeypatch)
    _allow_transfers(editor, dataset_id)
    editor.routes[f"PUT /datasets/{dataset_id}/groups/"] = {}
    plan = _group_plan(_restricted(L1, "g1"))

    result, _ = _run(runner, tmp_path, plan)

    assert result.exit_code == 0, result.output
    assert _follow_ups(tmp_path)["private_no_matching_group"] == L1
    assert any("made private" in n for n in _state(tmp_path)["items"][L1]["notes"])

    editor.routes["GET /groups/mine/"] = {
        "groups": [{"id": TEAM, "name": "Roads Team"}],
        "total": 1,
    }
    result, _ = _run(runner, tmp_path, plan)

    assert not any("made private" in n for n in _state(tmp_path)["items"][L1]["notes"])
    assert _state(tmp_path)["groups"]["g1"]["id"] == TEAM


def test_a_dataset_somebody_else_wrote_is_not_given_the_items_metadata(
    runner, tmp_path, editor, ran
):
    created = _created_id(L1)
    _allow_transfers(editor, created)
    editor.routes[f"GET /datasets/{created}"] = {
        **_editors_dataset(created),
        "updated_by": ALICE,
    }

    result, _ = _run(runner, tmp_path, _plan([_item(L1)], OWN))

    entry = _state(tmp_path)["items"][L1]
    assert result.exit_code == 1 and entry["status"] == "failed"
    assert "changed in GeoLens" in entry["error"]
    assert [s for s in editor.seen if s.method in ("PATCH", "PUT", "POST")] == []
