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
    path = files("geolens_cli.manifest.schemas").joinpath("arcgis-migration-plan-v1.schema.json")
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
        "g1": {"collection": "GIS team", "visibility": "internal"},
        "g2": {"collection": "Public maps", "visibility": "public"},
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


def test_an_edited_plan_is_not_overwritten_without_force(runner, inventory_file):
    path = inventory_file.parent / "arcgis-migration-plan.json"
    _plan_cli(runner, str(inventory_file))
    plan = json.loads(path.read_text())
    plan["items"][0]["action"] = "skip"
    path.write_text(json.dumps(plan))
    refused = _plan_cli(runner, str(inventory_file))
    assert refused.exit_code == 1
    assert json.loads(path.read_text())["items"][0]["action"] == "skip"
    forced = _plan_cli(runner, str(inventory_file), "--force")
    assert forced.exit_code == 0
    assert json.loads(path.read_text())["items"][0]["action"] != "skip"


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
