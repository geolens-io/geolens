"""`geolens arcgis plan`: default actions, mappings, dependency order, file safety."""

from __future__ import annotations

import json
import stat
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from geolens_cli import arcgis_plan as plan_mod
from geolens_cli.main import app

from .arcgis_fake import (
    A1,
    A2,
    A3,
    A4,
    B1,
    B2,
    C1,
    D1,
    D2,
    D3,
    D4,
    D5,
    HYDRANTS,
    ORG_ID,
    USER,
    inventory_report,
    item_data_path,
)

STRANGER = "9c" * 16


def _plan(overrides: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    return plan_mod.build_plan(
        inventory_report(overrides), inventory_path="inv.json", **kwargs
    )


def _items(plan: dict) -> dict[str, dict]:
    return {item["id"]: item for item in plan["items"]}


def _validator() -> Draft202012Validator:
    path = files("geolens_cli.manifest.schemas").joinpath(
        "arcgis-migration-plan-v2.schema.json"
    )
    schema = json.loads(path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _related(by_kind: dict[tuple[str, str], list[dict]]):
    def answer(seen):
        key = (seen.params["relationshipType"], seen.params["direction"])
        return {"relatedItems": by_kind.get(key, [])}

    return answer


def test_default_actions_follow_the_inventory_class():
    items = _items(_plan())
    actions = {
        i: items[i]["action"] for i in (A1, A2, A3, A4, B1, C1, D1, D2, D3, D4, D5)
    }
    assert actions == {
        A1: "import_layers",
        A2: "import_layers",
        A3: "import_layers",
        A4: "export_only",
        B1: "import_map",
        C1: "export_only",
        D1: "export_only",
        D2: "export_only",
        D3: "import_file",
        D4: "export_only",
        D5: "export_only",
    }
    assert items[A1]["reason"] == "hosted_feature_layer"


def test_plan_validates_and_survives_hand_edits():
    plan = _plan()
    _validator().validate(plan)
    edited = json.loads(json.dumps(plan))
    edited["items"][0]["action"] = "skip"
    edited["items"][0]["target"]["owner"] = "someone@example.org"
    edited["items"][1]["alias_of"] = A1
    edited["owner_map"][USER] = "gina"
    _validator().validate(edited)


def test_owner_map_lists_every_owner_and_takes_a_prepared_mapping():
    plan = _plan()
    assert plan["owner_map"] == {USER: ""}
    mapped = _plan(owner_map={USER: "gina", "nobody": "x"})
    assert mapped["owner_map"] == {USER: "gina"}
    assert mapped["items"][0]["target"]["owner"] is None


def test_groups_and_folders_become_collections():
    groups = {
        "admin": [{"id": "g1", "title": "GIS team", "access": "org"}],
        "other": [{"id": "g2", "title": "Public maps", "access": "public"}],
    }
    plan = _plan(
        {
            f"content/items/{A1}": {
                **json.loads(
                    (
                        Path(__file__).parent
                        / "fixtures/arcgis_inventory/item_detail_rich.json"
                    ).read_text()
                )
            },
            f"content/items/{A1}/groups": groups,
        }
    )
    assert plan["group_map"] == {
        "g1": {
            "collection": "GIS team",
            "visibility": "internal",
            "geolens_group": None,
        },
        "g2": {
            "collection": "Public maps",
            "visibility": "public",
            "geolens_group": None,
        },
    }
    target = _items(plan)[A1]["target"]
    assert target["collections"] == ["Apps"]
    assert target["groups"] == ["g1", "g2"]
    assert target["visibility"] == "internal"
    assert _items(plan)[A2]["target"]["visibility"] == "public"
    assert _items(plan)[A1]["target"]["tags"] == ["parcels", "cadastre"]


def test_basemap_urls_of_web_maps_are_listed_for_mapping():
    plan = _plan()
    assert plan["basemap_map"]
    assert set(plan["basemap_map"].values()) == {""}
    assert all(url.startswith("http") for url in plan["basemap_map"])


def test_web_map_depends_on_its_layers_and_notes_what_the_inventory_lacks():
    data = {
        "operationalLayers": [
            {"id": "x", "layerType": "ArcGISFeatureLayer", "itemId": STRANGER},
            {"id": "y", "layerType": "ArcGISFeatureLayer", "itemId": A1},
        ],
        "baseMap": {"baseMapLayers": []},
    }
    plan = _plan(
        {item_data_path(B1): data, f"content/items/{STRANGER}": {"orgId": ORG_ID}}
    )
    item = _items(plan)[B1]
    assert item["depends_on"] == [STRANGER, A1]
    assert f"not in the inventory: {STRANGER}" in item["reason"]
    assert A1 not in item["reason"]


def test_other_organizations_items_are_not_dependencies():
    assert HYDRANTS not in _items(_plan())[B1]["depends_on"]
    data = {
        "operationalLayers": [
            {"id": "x", "layerType": "ArcGISFeatureLayer", "itemId": STRANGER},
            {"id": "y", "layerType": "ArcGISFeatureLayer", "itemId": A1},
        ],
        "baseMap": {"baseMapLayers": []},
    }
    plan = _plan(
        {item_data_path(B1): data, f"content/items/{STRANGER}": {"orgId": "Elsewhere"}}
    )
    item = _items(plan)[B1]
    assert item["depends_on"] == [A1]
    assert "not in the inventory" not in item["reason"]


def test_view_depends_on_its_parent():
    view_parent = _related(
        {("Service2Service", "reverse"): [{"id": A1, "type": "Feature Service"}]}
    )
    plan = _plan({f"content/items/{A2}/relatedItems": view_parent})
    assert _items(plan)[A2]["depends_on"] == [A1]


def test_source_file_of_a_hosted_layer_is_export_only_and_not_a_dependency():
    source = _related({("Service2Data", "forward"): [{"id": D3, "type": "CSV"}]})
    plan = _plan({f"content/items/{A1}/relatedItems": source})
    items = _items(plan)
    assert items[D3]["action"] == "export_only"
    assert items[D3]["superseded_by"] == A1
    assert D3 not in items[A1]["depends_on"]
    _validator().validate(plan)


def test_inventory_v1_is_refused_with_the_command_to_rerun(tmp_path):
    path = tmp_path / "arcgis-inventory.json"
    path.write_text(json.dumps({"schema_version": "1", "items": []}))
    with pytest.raises(plan_mod.PlanError, match="geolens arcgis inventory"):
        plan_mod.load_inventory(path)


@pytest.fixture
def inventory_file(tmp_path):
    path = tmp_path / "inv" / "arcgis-inventory.json"
    path.parent.mkdir()
    path.write_text(json.dumps(inventory_report()))
    return path


def _plan_cli(runner, *args: str, json_mode: bool = False):
    argv = (["--json"] if json_mode else []) + ["arcgis", "plan", *args]
    return runner.invoke(app, argv)


def test_cli_writes_a_private_plan_next_to_the_inventory(runner, inventory_file):
    result = _plan_cli(runner, str(inventory_file))
    assert result.exit_code == 0, result.output
    path = inventory_file.parent / "arcgis-migration-plan.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    plan = json.loads(path.read_text())
    _validator().validate(plan)
    assert plan["inventory"]["path"] == "arcgis-inventory.json"
    assert "import_layers: 4" in result.stdout


def test_running_twice_gives_the_same_file(runner, inventory_file):
    path = inventory_file.parent / "arcgis-migration-plan.json"
    assert _plan_cli(runner, str(inventory_file)).exit_code == 0
    first = path.read_text()
    assert _plan_cli(runner, str(inventory_file)).exit_code == 0
    assert path.read_text() == first


def test_an_edited_plan_is_merged_and_force_replaces_it(runner, inventory_file):
    path = inventory_file.parent / "arcgis-migration-plan.json"
    _plan_cli(runner, str(inventory_file))
    plan = json.loads(path.read_text())
    plan["items"][0]["action"] = "skip"
    path.write_text(json.dumps(plan))
    merged = _plan_cli(runner, str(inventory_file))
    assert merged.exit_code == 0, merged.output
    assert json.loads(path.read_text())["items"][0]["action"] == "skip"
    forced = _plan_cli(runner, str(inventory_file), "--force")
    assert forced.exit_code == 0
    assert json.loads(path.read_text())["items"][0]["action"] != "skip"


# Merging a newer inventory into an existing plan


def _row(report: dict, item_id: str) -> dict:
    return next(r for r in report["items"] if r["id"] == item_id)


def _merge(current: dict, report: dict, **kwargs: Any) -> tuple[dict, dict]:
    fresh = plan_mod.build_plan(report, inventory_path="inv.json", **kwargs)
    return plan_mod.merge_plan(current, fresh, report)


def _as_v1(plan: dict) -> dict:
    """*plan* as the v1 CLI wrote it: no recorded defaults."""
    old = json.loads(json.dumps(plan))
    old["schema_version"] = "1"
    del old["inventory"]["scope"], old["inventory"]["auth"]
    old["inventory"].pop("started_at", None)
    for item in old["items"]:
        del item["defaults"]
    return old


def _v1_validator() -> Draft202012Validator:
    path = files("geolens_cli.manifest.schemas").joinpath(
        "arcgis-migration-plan-v1.schema.json"
    )
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def test_a_merge_keeps_operator_edits_and_takes_changed_defaults():
    plan = _plan()
    items = _items(plan)
    items[A1]["action"] = "skip"
    items[A1]["target"]["owner"] = "someone@example.org"
    items[A1]["target"]["title"] = "Parcels (2026)"
    items[A2]["alias_of"] = A1
    plan["owner_map"][USER] = "gina"
    report = inventory_report()
    _row(report, A1)["title"] = "Parcels, renamed in the portal"
    _row(report, A3)["title"] = "Roads"
    _row(report, A3)["sharing"]["access"] = "public"

    merged, changes = _merge(plan, report)

    _validator().validate(merged)
    out = _items(merged)
    assert out[A1]["action"] == "skip"
    assert out[A1]["target"]["owner"] == "someone@example.org"
    assert out[A1]["target"]["title"] == "Parcels (2026)"
    assert out[A1]["title"] == "Parcels, renamed in the portal"
    assert out[A2]["alias_of"] == A1
    assert merged["owner_map"] == {USER: "gina"}
    assert out[A3]["target"]["title"] == "Roads"
    assert out[A3]["target"]["visibility"] == "public"
    assert changes["conflicts"] == [
        {
            "item": A1,
            "field": "target.title",
            "plan": "Parcels (2026)",
            "inventory": "Parcels, renamed in the portal",
        }
    ]
    assert out[A1]["defaults"]["target"]["title"] == "Parcels"
    assert out[A3]["defaults"]["target"]["title"] == "Roads"


def test_a_merge_of_the_same_inventory_changes_nothing():
    plan = _plan()
    _items(plan)[A1]["target"]["tags"] = ["mine"]
    merged, changes = _merge(json.loads(json.dumps(plan)), inventory_report())
    assert merged == plan
    assert not any(changes.values())


def test_new_portal_items_get_defaults():
    plan = _plan()
    report = inventory_report()
    new_id = "f1" * 16
    report["items"].append({**_row(report, A3), "id": new_id, "title": "Trails"})

    merged, changes = _merge(plan, report)

    assert changes["added"] == [new_id]
    entry = _items(merged)[new_id]
    assert entry["action"] == "import_layers"
    assert entry["target"]["title"] == "Trails"
    assert entry["defaults"]["target"] == entry["target"]


def test_an_item_gone_from_the_portal_is_kept_and_marked_removed():
    plan = _plan()
    _items(plan)[D3]["target"]["title"] = "Inspections (edited)"
    report = inventory_report()
    report["items"] = [r for r in report["items"] if r["id"] != D3]

    merged, changes = _merge(plan, report)

    _validator().validate(merged)
    entry = _items(merged)[D3]
    assert entry["removed"] is True
    assert entry["target"]["title"] == "Inspections (edited)"
    assert changes["removed"] == [D3]
    assert plan_mod.summary(merged, report)["removed"] == 1
    again, changes = _merge(merged, report)
    assert _items(again)[D3]["removed"] is True
    assert changes["removed"] == []
    back, changes = _merge(again, inventory_report())
    assert "removed" not in _items(back)[D3]
    assert changes["restored"] == [D3]


def test_a_partial_inventory_removes_nothing():
    plan = _plan()
    report = inventory_report()
    report["items"] = [r for r in report["items"] if r["id"] != D3]
    report["truncated"] = True

    merged, changes = _merge(plan, report)

    assert "removed" not in _items(merged)[D3]
    assert changes["unlisted"] == [D3]
    assert changes["removed"] == []


def test_a_v1_plan_reads_and_upgrades_keeping_every_value():
    plan = _plan()
    _items(plan)[A1]["target"]["visibility"] = "public"
    v1 = _as_v1(plan)
    _v1_validator().validate(v1)
    report = inventory_report()
    _row(report, A3)["title"] = "Roads"

    merged, changes = _merge(v1, report)

    _validator().validate(merged)
    assert merged["schema_version"] == "2"
    out = _items(merged)
    # Nothing records what v1 defaulted, so every value counts as an edit.
    assert out[A3]["target"]["title"] == "County roads"
    assert out[A1]["target"]["visibility"] == "public"
    assert {(c["item"], c["field"]) for c in changes["conflicts"]} == {
        (A1, "target.visibility"),
        (A3, "target.title"),
    }
    assert "defaults" not in out[A3]


def test_a_v1_value_stays_an_edit_when_the_portal_default_matches_it_once():
    plan = _plan()
    _items(plan)[A2]["target"]["visibility"] = "private"
    unshared = inventory_report()
    _row(unshared, A2)["sharing"]["access"] = "private"

    merged, _ = _merge(_as_v1(plan), unshared)
    again, changes = _merge(merged, inventory_report())

    assert _items(again)[A2]["target"]["visibility"] == "private"
    assert {
        "item": A2,
        "field": "target.visibility",
        "plan": "private",
        "inventory": "public",
    } in changes["conflicts"]


def test_load_plan_reads_v1_and_v2(tmp_path):
    plan = _plan()
    path = tmp_path / "arcgis-migration-plan.json"
    for version in (plan, _as_v1(plan)):
        path.write_text(json.dumps(version))
        assert plan_mod.load_plan(path) == version
    path.write_text(json.dumps({**plan, "schema_version": "1"}))
    with pytest.raises(plan_mod.PlanError, match="not a valid migration plan"):
        plan_mod.load_plan(path)


def test_defaults_that_changed_between_versions_follow_unless_edited(monkeypatch):
    plan = _plan()
    _items(plan)[D1]["action"] = "skip"
    _items(plan)[D3]["action"] = "skip"
    monkeypatch.setattr(
        plan_mod,
        "_default_action",
        lambda row: "skip" if row["type"] == "WMS" else plan_mod.EXPORT_ONLY,
    )

    merged, changes = _merge(plan, inventory_report())

    out = _items(merged)
    assert out[D2]["action"] == "skip"
    assert out[A1]["action"] == "export_only"
    assert out[D1]["action"] == "skip"
    assert out[D3]["action"] == "skip"
    assert out[D3]["defaults"]["action"] == "import_file"
    conflicts = [(c["item"], c["plan"], c["inventory"]) for c in changes["conflicts"]]
    assert conflicts == [(D3, "skip", "export_only")]


def test_unread_portal_data_does_not_replace_what_the_plan_knows():
    groups = {"admin": [{"id": "g1", "title": "GIS team", "access": "org"}]}
    plan = _plan({f"content/items/{A1}/groups": groups})
    assert _items(plan)[A1]["target"]["groups"] == ["g1"]
    unread = inventory_report(_unreadable_web_map(), read_groups=False)

    merged, changes = _merge(plan, unread)

    out = _items(merged)
    assert out[A1]["target"]["groups"] == ["g1"]
    assert out[A1]["defaults"]["target"]["groups"] == ["g1"]
    assert out[B1]["action"] == "import_map"
    assert out[B1]["depends_on"] == _items(plan)[B1]["depends_on"]
    assert merged["group_map"]["g1"]["collection"] == "GIS team"
    assert changes["conflicts"] == []


def test_owner_map_entries_in_the_plan_win_over_owner_map_file():
    plan = _plan()
    plan["owner_map"][USER] = "gina"
    merged, changes = _merge(plan, inventory_report(), owner_map={USER: "other"})
    assert merged["owner_map"] == {USER: "gina"}
    assert changes["owner_conflicts"] == [
        {"owner": USER, "plan": "gina", "owner_map": "other"}
    ]
    filled, _ = _merge(_plan(), inventory_report(), owner_map={USER: "gina"})
    assert filled["owner_map"] == {USER: "gina"}


def test_cli_merges_a_newer_inventory_into_the_plan(runner, inventory_file):
    path = inventory_file.parent / "arcgis-migration-plan.json"
    assert _plan_cli(runner, str(inventory_file)).exit_code == 0
    plan = json.loads(path.read_text())
    _items(plan)[A1]["action"] = "skip"
    path.write_text(json.dumps(_as_v1(plan)))
    report = inventory_report()
    report["generated_at"] = "2026-10-20T00:00:00Z"
    report["items"] = [r for r in report["items"] if r["id"] != D3]
    inventory_file.write_text(json.dumps(report))

    result = _plan_cli(runner, str(inventory_file), json_mode=True)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["merge"]["removed"] == [D3]
    merged = json.loads(path.read_text())
    _validator().validate(merged)
    assert merged["inventory"]["generated_at"] == "2026-10-20T00:00:00Z"
    assert _items(merged)[A1]["action"] == "skip"
    assert _items(merged)[D3]["removed"] is True
    before = path.read_text()
    text = _plan_cli(runner, str(inventory_file))
    assert "Merged the inventory" in text.stdout
    assert path.read_text() == before


def test_cli_refuses_to_merge_a_plan_for_another_portal(runner, inventory_file):
    path = inventory_file.parent / "arcgis-migration-plan.json"
    _plan_cli(runner, str(inventory_file))
    plan = json.loads(path.read_text())
    plan["portal"]["url"] = "https://other.maps.arcgis.com"
    path.write_text(json.dumps(plan))
    result = _plan_cli(runner, str(inventory_file))
    assert result.exit_code == 1
    assert "--force" in result.output + result.stderr
    assert (
        json.loads(path.read_text())["portal"]["url"] == "https://other.maps.arcgis.com"
    )


def test_cli_owner_map_and_json_summary(runner, inventory_file, tmp_path):
    owners = tmp_path / "owners.json"
    owners.write_text(json.dumps({USER: "gina@example.org"}))
    result = _plan_cli(
        runner, str(inventory_file), "--owner-map", str(owners), json_mode=True
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["owners_to_map"] == 0
    assert summary["by_action"]["import_map"] == 1
    assert summary["external_dependencies"] == 3
    assert summary["unresolved_dependencies"] == []
    plan = json.loads(
        (inventory_file.parent / "arcgis-migration-plan.json").read_text()
    )
    assert plan["owner_map"] == {USER: "gina@example.org"}


def test_cli_rejects_a_v1_inventory(runner, tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"schema_version": "1"}))
    result = _plan_cli(runner, str(path))
    assert result.exit_code == 2
    assert "geolens arcgis inventory" in result.output + result.stderr


def test_a_partial_inventory_is_flagged_in_the_plan(runner, tmp_path):
    report = inventory_report()
    report["complete"] = False
    path = tmp_path / "arcgis-inventory.json"
    path.write_text(json.dumps(report))
    result = _plan_cli(runner, str(path))
    assert result.exit_code == 0
    plan = json.loads((tmp_path / "arcgis-migration-plan.json").read_text())
    assert plan["inventory"]["complete"] is False


def test_a_malformed_inventory_is_a_usage_error(runner, tmp_path):
    report = inventory_report()
    del report["items"][0]["folder"]
    path = tmp_path / "arcgis-inventory.json"
    path.write_text(json.dumps(report))
    result = _plan_cli(runner, str(path))
    assert result.exit_code == 2
    assert "malformed" in result.output + result.stderr
    assert not (tmp_path / "arcgis-migration-plan.json").exists()


def test_an_unreadable_existing_plan_is_an_error_not_a_traceback(
    runner, inventory_file
):
    (inventory_file.parent / "arcgis-migration-plan.json").write_bytes(b"\xff\xfe\x00")
    result = _plan_cli(runner, str(inventory_file))
    assert result.exit_code == 1
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(generated_at=12345),
        lambda r: r["items"][0].update(tags="parcels"),
    ],
    ids=["generated_at", "tags"],
)
def test_an_inventory_off_its_schema_is_a_usage_error(runner, tmp_path, mutate):
    report = inventory_report()
    mutate(report)
    path = tmp_path / "arcgis-inventory.json"
    path.write_text(json.dumps(report))
    result = _plan_cli(runner, str(path))
    assert result.exit_code == 2
    assert "geolens arcgis inventory" in result.output + result.stderr
    assert not (tmp_path / "arcgis-migration-plan.json").exists()


def _unreadable_web_map() -> dict[str, Any]:
    return {item_data_path(B1): (500, {"error": {"code": 500, "message": "boom"}})}


def test_a_web_map_whose_data_could_not_be_read_is_export_only():
    plan = _plan(_unreadable_web_map())
    entry = _items(plan)[B1]
    assert entry["action"] == "export_only"
    assert "dependencies could not be read" in entry["reason"]
    assert "import_map by hand" in entry["reason"]
    errors = plan_mod.summary(plan, inventory_report(_unreadable_web_map()))[
        "dependency_read_errors"
    ]
    assert B1 in errors
    assert errors == sorted(errors)


def test_cli_warns_about_unread_dependencies(runner, tmp_path):
    path = tmp_path / "arcgis-inventory.json"
    path.write_text(json.dumps(inventory_report(_unreadable_web_map())))
    result = _plan_cli(runner, str(path))
    assert result.exit_code == 0, result.output
    assert "could not read" in result.output + result.stderr
    assert B1 in result.output + result.stderr


def test_a_web_map_whose_dependencies_were_not_fetched_is_export_only():
    report = inventory_report()
    row = next(r for r in report["items"] if r["id"] == B1)
    row["dependencies_status"] = "not_fetched"
    plan = plan_mod.build_plan(report, inventory_path="inv.json")
    assert _items(plan)[B1]["action"] == "export_only"
    assert B1 in plan_mod.summary(plan, report)["dependency_read_errors"]


def test_unread_group_sharing_is_null_in_the_plan_and_warned_about(runner, tmp_path):
    report = inventory_report(read_groups=False)
    plan = plan_mod.build_plan(report, inventory_path="inv.json")
    _validator().validate(plan)
    assert all(i["target"]["groups"] is None for i in plan["items"])
    assert plan_mod.summary(plan, report)["group_sharing_unknown"] == sorted(
        i["id"] for i in plan["items"]
    )
    path = tmp_path / "arcgis-inventory.json"
    path.write_text(json.dumps(report))
    result = _plan_cli(runner, str(path))
    assert result.exit_code == 0, result.output
    assert "--no-groups" in result.output + result.stderr


def test_an_edit_stays_when_the_portal_default_passes_through_it():
    plan = _plan()
    _items(plan)[A2]["target"]["visibility"] = "private"
    unshared = inventory_report()
    _row(unshared, A2)["sharing"]["access"] = "private"

    merged, changes = _merge(plan, unshared)
    assert _items(merged)[A2]["target"]["visibility"] == "private"
    assert changes["conflicts"] == []
    again, _ = _merge(merged, inventory_report())

    assert _items(again)[A2]["target"]["visibility"] == "private"
    assert _items(again)[A2]["defaults"]["target"]["visibility"] == "public"


def _narrower(report: dict) -> dict:
    report["items"] = [r for r in report["items"] if r["id"] not in (A3, D3)]
    return report


def test_a_listed_item_is_no_longer_unlisted():
    truncated = _narrower(inventory_report())
    truncated["truncated"] = True
    partial, _ = _merge(_plan(), truncated)
    assert _items(partial)[A3]["unlisted"] is True
    full, changes = _merge(partial, inventory_report())
    assert "unlisted" not in _items(full)[A3]
    assert changes["unlisted"] == []


def _without(report: dict, *ids: str) -> dict:
    report["items"] = [r for r in report["items"] if r["id"] not in ids]
    return report


def _user_scope(report: dict) -> dict:
    report["scope"].update(mode="user", owner=USER)
    return report


def _inventories() -> dict[str, dict]:
    truncated = _without(inventory_report(), D3)
    truncated["truncated"] = True
    aborted = _without(inventory_report(), D3)
    aborted["complete"] = False
    anonymous = _without(inventory_report(), B2, D3)
    anonymous["auth"].update(mode="anonymous", user=None, role=None)
    other_admin = _without(inventory_report(), D3)
    other_admin["auth"].update(user="another_admin")
    member = _without(inventory_report(), D3)
    member["auth"].update(user="field_tech", role="org_user")
    role_unknown = _without(inventory_report(), D3)
    del role_unknown["auth"]["role"]
    return {
        "org": inventory_report(),
        "gone": _without(inventory_report(), D3),
        "other_admin": other_admin,
        "member": member,
        "role_unknown": role_unknown,
        # A3 and D3 belong to someone else, so a user-scope read misses them.
        "user": _user_scope(_without(inventory_report(), A3, D3)),
        # A1 has since been handed to another owner.
        "user_transfer": _user_scope(_without(inventory_report(), A1, A3, D3)),
        "anonymous": anonymous,
        "truncated": truncated,
        "aborted": aborted,
    }


NONE: frozenset[str] = frozenset()


# start: the inventory the plan is built from, as v2 or v1.
# Each step: (inventory, removed after it, unlisted after it, recorded complete).
@pytest.mark.parametrize(
    ("start", "steps"),
    [
        (("org", "v2"), [("gone", {D3}, NONE, True), ("gone", {D3}, NONE, True)]),
        (("org", "v1"), [("gone", {D3}, NONE, True)]),
        (("org", "v2"), [("other_admin", {D3}, NONE, True)]),
        (("org", "v2"), [("member", NONE, {D3}, True), ("gone", {D3}, NONE, True)]),
        (("org", "v2"), [("role_unknown", NONE, {D3}, True)]),
        (
            ("user", "v2"),
            [("org", NONE, NONE, True), ("user", NONE, {A3, D3}, True)],
        ),
        (
            ("user", "v1"),
            [
                ("user", NONE, NONE, True),
                ("org", NONE, NONE, True),
                ("user", NONE, {A3, D3}, True),
            ],
        ),
        (
            ("user", "v2"),
            [("user_transfer", NONE, {A1}, True), ("user_transfer", NONE, {A1}, True)],
        ),
        (
            ("org", "v2"),
            [("anonymous", NONE, {B2, D3}, True), ("anonymous", NONE, {B2, D3}, True)],
        ),
        (
            ("org", "v2"),
            [
                ("user", NONE, {A3, D3}, True),
                ("org", NONE, NONE, True),
                ("user", NONE, {A3, D3}, True),
            ],
        ),
        (
            ("org", "v2"),
            [
                ("truncated", NONE, {D3}, False),
                ("aborted", NONE, {D3}, False),
                ("gone", {D3}, NONE, True),
            ],
        ),
        (
            ("org", "v2"),
            [
                ("gone", {D3}, NONE, True),
                ("user", {D3}, {A3}, True),
                ("org", NONE, NONE, True),
            ],
        ),
    ],
    ids=[
        "org_admin_removes_and_repeats",
        "v1_org_admin_removes",
        "another_org_admin_removes",
        "non_admin_org_reader_removes_nothing",
        "inventory_without_a_role_removes_nothing",
        "narrow_wide_narrow",
        "v1_narrow_wide_narrow",
        "user_scope_owner_change",
        "anonymous_complete",
        "wide_narrow_wide_narrow",
        "partial_then_aborted_then_complete",
        "removed_kept_then_restored",
    ],
)
def test_only_an_org_admin_inventory_removes_items(start, steps):
    inventories = _inventories()
    source, version = start
    plan = plan_mod.build_plan(inventories[source], inventory_path="inv.json")
    if version == "v1":
        plan = _as_v1(plan)
    previous = None
    for name, removed, unlisted, complete in steps:
        report = json.loads(json.dumps(inventories[name]))
        plan, _ = _merge(plan, report)
        _validator().validate(plan)
        items = plan["items"]
        assert {i["id"] for i in items if i.get("removed")} == removed, name
        assert {i["id"] for i in items if i.get("unlisted")} == unlisted, name
        assert plan["inventory"]["complete"] is complete, name
        if previous is not None and previous[0] == name:
            assert plan == previous[1], f"{name} twice is not a no-op"
        previous = (name, json.loads(json.dumps(plan)))


def test_operator_maps_and_plan_defaults_win_over_the_inventory():
    groups = {"admin": [{"id": "g1", "title": "GIS team", "access": "org"}]}
    overrides = {f"content/items/{A1}/groups": groups}
    plan = _plan(overrides)
    basemap = next(iter(plan["basemap_map"]))
    plan["group_map"]["g1"] = {"collection": "Our team", "visibility": "private"}
    plan["basemap_map"][basemap] = "terrain"
    plan["defaults"] = {"visibility": "internal", "collection_from": "none"}

    merged, _ = _merge(plan, inventory_report(overrides))

    assert merged["group_map"]["g1"] == {
        "collection": "Our team",
        "visibility": "private",
    }
    assert merged["basemap_map"][basemap] == "terrain"
    assert merged["defaults"] == {"visibility": "internal", "collection_from": "none"}


def test_a_merge_keeps_the_operators_item_order():
    plan = _plan()
    plan["items"].reverse()
    report = inventory_report()
    new_id = "f1" * 16
    report["items"].append({**_row(report, A3), "id": new_id, "title": "Trails"})

    merged, _ = _merge(plan, report)

    order = [item["id"] for item in merged["items"]]
    assert order == [item["id"] for item in plan["items"]] + [new_id]


def test_conflict_warnings_are_capped(runner, inventory_file):
    path = inventory_file.parent / "arcgis-migration-plan.json"
    _plan_cli(runner, str(inventory_file))
    plan = json.loads(path.read_text())
    for item in plan["items"]:
        item["target"]["title"] = "edited"
    path.write_text(json.dumps(_as_v1(plan)))

    result = _plan_cli(runner, str(inventory_file))

    out = result.output
    assert result.exit_code == 0, out
    assert out.count("kept the plan's") == plan_mod.CONFLICT_LINES
    assert f"{len(plan['items']) - plan_mod.CONFLICT_LINES} more value(s)" in out


def test_cli_refuses_to_merge_an_inventory_of_another_organization(
    runner, inventory_file
):
    path = inventory_file.parent / "arcgis-migration-plan.json"
    _plan_cli(runner, str(inventory_file))
    before = path.read_text()
    report = inventory_report()
    report["scope"]["org_id"] = report["portal"]["org_id"] = "AnotherOrg000"
    inventory_file.write_text(json.dumps(report))

    result = _plan_cli(runner, str(inventory_file))

    assert result.exit_code == 1
    assert "ArcGIS organization" in result.output
    assert "--force" in result.output
    assert path.read_text() == before


def test_a_plan_without_an_org_id_merges_on_the_portal_url_alone():
    report = inventory_report()
    report["scope"]["org_id"] = "AnotherOrg000"
    merged, _ = _merge(_as_v1(_plan()), report)
    assert merged["inventory"]["scope"]["org_id"] == "AnotherOrg000"


def test_fresh_defaults_use_the_plans_fallback_visibility(runner, inventory_file):
    path = inventory_file.parent / "arcgis-migration-plan.json"
    report = inventory_report()
    _row(report, A1)["sharing"]["access"] = "custom"
    inventory_file.write_text(json.dumps(report))
    _plan_cli(runner, str(inventory_file))
    plan = json.loads(path.read_text())
    assert _items(plan)[A1]["target"]["visibility"] == "private"
    plan["defaults"]["visibility"] = "internal"
    path.write_text(json.dumps(plan))
    new_id = "f1" * 16
    report["items"].append({**_row(report, A1), "id": new_id, "title": "Trails"})
    inventory_file.write_text(json.dumps(report))

    result = _plan_cli(runner, str(inventory_file))

    assert result.exit_code == 0, result.output
    merged = _items(json.loads(path.read_text()))
    for item_id in (A1, new_id):
        assert merged[item_id]["target"]["visibility"] == "internal"
        assert merged[item_id]["defaults"]["target"]["visibility"] == "internal"


def test_a_merge_without_an_org_id_keeps_the_plans_org_id():
    anonymous = inventory_report()
    anonymous["auth"].update(mode="anonymous", user=None, role=None)
    anonymous["scope"]["org_id"] = anonymous["portal"]["org_id"] = None
    merged, _ = _merge(_plan(), anonymous)
    assert merged["inventory"]["scope"]["org_id"] == ORG_ID
    other = inventory_report()
    other["scope"]["org_id"] = other["portal"]["org_id"] = "AnotherOrg000"

    with pytest.raises(plan_mod.PlanError, match="ArcGIS organization"):
        _merge(merged, other)


def test_owners_to_map_counts_only_owners_plan_items_use():
    plan = _plan(owner_map={USER: "gina"})
    plan["owner_map"]["departed"] = ""
    _items(plan)[A1]["owner"] = "handed_over"
    _items(plan)[A1]["target"]["owner"] = "gina"
    plan["owner_map"]["handed_over"] = ""
    assert plan_mod.summary(plan, inventory_report())["owners_to_map"] == 0
    _items(plan)[A2]["owner"] = "needs_one"
    plan["owner_map"]["needs_one"] = ""
    assert plan_mod.summary(plan, inventory_report())["owners_to_map"] == 1


_CLAIMS_D3 = _related({("Service2Data", "forward"): [{"id": D3, "type": "CSV"}]})
_READ_FAILS = (500, {"error": {"code": 500}})


NEW_LAYER = "a6" * 16


def _supersession_inventory(old: str, new: str) -> dict:
    """An inventory where the old layer (A1) claims D3, is read without
    claiming it, is unread or isn't listed, and where another hosted layer
    claims D3, claims nothing, or is unread."""
    report = inventory_report({f"content/items/{A1}/relatedItems": _CLAIMS_D3})
    claim = next(
        d
        for d in report["dependencies"]
        if d["from_id"] == A1 and d["role"] == "published_from"
    )
    layer = {**json.loads(json.dumps(_row(report, A1))), "id": NEW_LAYER}
    layer["title"] = "Parcels, republished"
    report["items"].append(layer)
    if new == "claims":
        report["dependencies"].append({**claim, "from_id": NEW_LAYER})
    elif new == "unread":
        layer["dependencies_status"] = "error"
    if old != "claims":
        report["dependencies"].remove(claim)
    if old == "unread":
        _row(report, A1)["dependencies_status"] = "error"
    elif old == "missing":
        report = _without(report, A1)
        report["truncated"] = True
    return report


EXPORT, IMPORT = "export_only", "import_file"


# (old layer A1, other layer A2, D3's action and superseded_by when unedited)
@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("claims", "none", (EXPORT, A1)),
        ("claims", "unread", (EXPORT, A1)),
        ("read", "none", (IMPORT, None)),
        ("read", "claims", (EXPORT, NEW_LAYER)),
        ("read", "unread", (IMPORT, None)),
        ("unread", "none", (EXPORT, A1)),
        ("unread", "claims", (EXPORT, NEW_LAYER)),
        ("unread", "unread", (EXPORT, A1)),
        ("missing", "none", (EXPORT, A1)),
        ("missing", "claims", (EXPORT, NEW_LAYER)),
        ("missing", "unread", (EXPORT, A1)),
    ],
)
@pytest.mark.parametrize("edit", ["none", "skip", "import_file"])
def test_a_source_files_supersession_across_layer_reads(old, new, expected, edit):
    plan = _plan({f"content/items/{A1}/relatedItems": _CLAIMS_D3})
    assert (_items(plan)[D3]["action"], _items(plan)[D3]["superseded_by"]) == (
        EXPORT,
        A1,
    )
    if edit == "skip":
        _items(plan)[D3]["action"] = "skip"
    elif edit == "import_file":
        _items(plan)[D3]["action"] = IMPORT
        del _items(plan)[D3]["superseded_by"]

    merged, _ = _merge(plan, _supersession_inventory(old, new))

    entry = _items(merged)[D3]
    action, layer = expected
    if edit == "skip":
        action = "skip"
    elif edit == "import_file":
        action, layer = IMPORT, None
    assert (entry["action"], entry.get("superseded_by")) == (action, layer)
    _validator().validate(merged)


def test_a_source_file_without_a_layer_follows_a_new_claim():
    plan = _plan()
    assert _items(plan)[D3]["action"] == IMPORT

    merged, _ = _merge(plan, _supersession_inventory("read", "claims"))

    assert _items(merged)[D3]["action"] == EXPORT
    assert _items(merged)[D3]["superseded_by"] == NEW_LAYER


FOLDER_ID = "f7" * 16


def _set_folder(title: str | None):
    def mutate(report: dict) -> None:
        _row(report, A3)["folder"] = {"id": FOLDER_ID, "title": title}

    return mutate


def _set_groups(groups: list[dict] | None):
    def mutate(report: dict) -> None:
        _row(report, A3)["groups"] = groups

    return mutate


def _web_map_dependencies(status: str):
    def mutate(report: dict) -> None:
        _row(report, B1)["dependencies_status"] = status
        report["dependencies"] = [
            d for d in report["dependencies"] if d["from_id"] != B1
        ]

    return mutate


def _layer_relationships(status: str):
    def mutate(report: dict) -> None:
        _row(report, A1)["dependencies_status"] = status
        report["dependencies"] = [
            d for d in report["dependencies"] if d["from_id"] != A1
        ]

    return mutate


def _set_row(item_id: str, **values: Any):
    def mutate(report: dict) -> None:
        _row(report, item_id).update(values)

    return mutate


def _set_access(access: str):
    def mutate(report: dict) -> None:
        _row(report, A3)["sharing"]["access"] = access

    return mutate


GIS_TEAM = [{"id": "g1", "title": "GIS team", "access": "org"}]
PRIVATE_TEAM = [{"id": "g2", "title": "Assessors", "access": "private"}]
EXTRA_TEAM = [{"id": "g3", "title": "Planning", "access": "org"}]


def _value(item: dict, path: tuple[str, ...]) -> Any:
    for key in path:
        item = item.get(key)
    return item


# Every item value the plan derives from the inventory, against the read it
# comes from: failed ("unread": the plan keeps its value), read by an org
# admin, or read by a member who sees only what is shared with them. Item
# listing fields (title, tags, access, folder, type) are complete for any
# reader who sees the item; only an item's groups can be a subset.
# target.owner has no inventory default.
@pytest.mark.parametrize(
    ("item_id", "path", "mutate", "reader", "expected"),
    [
        (A3, ("target", "collections"), _set_folder(None), "admin", ["Projects"]),
        (A3, ("target", "collections"), _set_folder("Roads"), "admin", ["Roads"]),
        (A3, ("target", "collections"), _set_folder("Roads"), "member", ["Roads"]),
        (A3, ("target", "groups"), _set_groups(None), "admin", ["g1", "g2"]),
        (A3, ("target", "groups"), _set_groups(GIS_TEAM), "admin", ["g1"]),
        (A3, ("target", "groups"), _set_groups(GIS_TEAM), "member", ["g1", "g2"]),
        (A3, ("target", "groups"), _set_groups([]), "member", ["g1", "g2"]),
        (
            A3,
            ("target", "groups"),
            _set_groups(GIS_TEAM + PRIVATE_TEAM + EXTRA_TEAM),
            "member",
            ["g1", "g2", "g3"],
        ),
        (B1, ("action",), _web_map_dependencies("error"), "admin", "import_map"),
        (B1, ("depends_on",), _web_map_dependencies("not_fetched"), "admin", "KEEP"),
        (B1, ("depends_on",), _web_map_dependencies("parsed"), "admin", []),
        (B1, ("depends_on",), _web_map_dependencies("parsed"), "member", []),
        (D3, ("action",), _layer_relationships("error"), "admin", "export_only"),
        (D3, ("superseded_by",), _layer_relationships("error"), "admin", A1),
        (D3, ("action",), _layer_relationships("parsed"), "admin", "import_file"),
        (D3, ("superseded_by",), _layer_relationships("parsed"), "admin", None),
        (D3, ("action",), _layer_relationships("parsed"), "member", "import_file"),
        (A3, ("target", "visibility"), _set_access("public"), "admin", "public"),
        (A3, ("target", "visibility"), _set_access("public"), "member", "public"),
        (A3, ("target", "title"), _set_row(A3, title="Roads"), "admin", "Roads"),
        (A3, ("target", "title"), _set_row(A3, title="Roads"), "member", "Roads"),
        (A3, ("target", "tags"), _set_row(A3, tags=["roads"]), "admin", ["roads"]),
        (A3, ("target", "tags"), _set_row(A3, tags=["roads"]), "member", ["roads"]),
    ],
    ids=[
        "collections_folder_title_unread",
        "collections_admin_read",
        "collections_member_read",
        "groups_unread",
        "groups_admin_read_shrinks",
        "groups_member_read_keeps_unseen",
        "groups_member_read_empty_keeps_all",
        "groups_member_read_adds",
        "web_map_action_dependencies_unread",
        "depends_on_dependencies_not_fetched",
        "depends_on_admin_read",
        "depends_on_member_read",
        "file_action_layer_unread",
        "superseded_by_layer_unread",
        "file_action_admin_read",
        "superseded_by_admin_read",
        "file_action_member_read",
        "visibility_admin_read",
        "visibility_member_read",
        "title_admin_read",
        "title_member_read",
        "tags_admin_read",
        "tags_member_read",
    ],
)
def test_each_derived_value_follows_only_a_successful_read(
    item_id, path, mutate, reader, expected
):
    base = inventory_report({f"content/items/{A1}/relatedItems": _CLAIMS_D3})
    _set_folder("Projects")(base)
    _set_groups(GIS_TEAM + PRIVATE_TEAM)(base)
    plan = plan_mod.build_plan(base, inventory_path="inv.json")
    before = _value(_items(plan)[item_id], path)
    report = json.loads(json.dumps(base))
    mutate(report)
    if reader == "member":
        report["auth"]["role"] = "org_user"

    merged, _ = _merge(plan, report)

    after = _value(_items(merged)[item_id], path)
    assert after == (before if expected == "KEEP" else expected)
    if expected == "KEEP":
        assert before


def test_a_member_read_after_an_admin_read_keeps_a_private_group():
    admin = inventory_report()
    _set_groups(GIS_TEAM + PRIVATE_TEAM)(admin)
    plan = plan_mod.build_plan(admin, inventory_path="inv.json")
    member = inventory_report()
    _set_groups(GIS_TEAM)(member)
    member["auth"].update(user="field_tech", role="org_user")

    merged, changes = _merge(plan, member)

    assert _items(merged)[A3]["target"]["groups"] == ["g1", "g2"]
    assert _items(merged)[A3]["defaults"]["target"]["groups"] == ["g1", "g2"]
    assert merged["group_map"]["g2"]["collection"] == "Assessors"
    assert changes["groups_kept"] == [A3]
    assert changes["conflicts"] == []
    again, changes = _merge(merged, admin)
    assert _items(again)[A3]["target"]["groups"] == ["g1", "g2"]
    assert changes["groups_kept"] == []


def test_each_under_sharing_reason_is_named_with_its_items(runner, inventory_file):
    report = inventory_report()
    report["auth"]["role"] = "org_user"
    for row in report["items"]:
        if row["id"] == A1:
            row["sharing"]["access"] = "shared"
            row["groups"] = None
        if row["id"] == A2:
            row["sharing"]["access"] = "shared"
            row["groups"] = [{"id": "g1", "title": "Planning", "access": "org"}]
    inventory_file.write_text(json.dumps(report))

    result = runner.invoke(app, ["arcgis", "plan", str(inventory_file)])

    assert result.exit_code == 0, result.output
    text = " ".join(result.output.split())
    assert f"group sharing wasn't read: {A1}" in text
    assert f"which doesn't see private groups it isn't in: {A2}" in text
