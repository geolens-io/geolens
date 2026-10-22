"""`geolens arcgis migrate`: filing migrated datasets into collections."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest

from .arcgis_fake import A1, A2
from . import test_arcgis_migrate_layers as layers
from .test_arcgis_migrate_layers import (
    FakeImport,
    _layer,
    _migrate,
    _problem,
    _state,
    _uuid,
    _write_plan,
    dataset_id,
)

# Fixtures of the import tests: the fake GeoLens with an admin operator, and
# the cleared ArcGIS credential variables.
geolens = layers.geolens
quick = layers.quick

COLLECTIONS = "/catalog/collections/"
URLS = {
    A1: "https://services1.arcgis.com/ExAmPlEoRg0123/arcgis/rest/services/Roads/FeatureServer",
    A2: "https://services1.arcgis.com/ExAmPlEoRg0123/arcgis/rest/services/Parcels/FeatureServer",
}
LAYERS = {URLS[A1]: [_layer(0, "Roads")], URLS[A2]: [_layer(0, "Parcels")]}


class FakeCollections:
    """The collection routes: unique names, idempotent membership."""

    def __init__(self, fake, taken: tuple[str, ...] = ()) -> None:
        self.fake = fake
        self.taken = set(taken)
        self.created = 0
        self.names: dict[str, str] = {}
        self.members: dict[str, set[str]] = {}
        fake.routes[f"POST {COLLECTIONS}"] = self.create

    def create(self, seen):
        name = seen.json()["name"]
        if name in self.taken or name in self.names.values():
            return (409, _problem(409, f"Collection with name '{name}' already exists"))
        self.created += 1
        collection = _uuid("c0", f"{self.created:02d}")
        self.names[collection] = name
        self.members[collection] = set()
        self.fake.routes[f"POST {COLLECTIONS}{collection}/datasets/"] = (
            lambda s, c=collection: self.add(c, s)
        )
        return (201, self.response(collection))

    def add(self, collection: str, seen):
        new = set(seen.json()["dataset_ids"]) - self.members[collection]
        self.members[collection] |= new
        return {"added": len(new)}

    def response(self, collection: str) -> dict:
        return {
            "id": collection,
            "name": self.names[collection],
            "description": None,
            "created_by": None,
            "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-01T00:00:00Z",
            "dataset_count": 0,
        }

    def membership(self) -> dict[str, set[str]]:
        return {self.names[c]: ids for c, ids in self.members.items()}


def _plan(tmp_path: Path, edit=None, *, private: bool = False) -> Path:
    public = {"sharing": {"access": "public", "groups": []}}
    path = _write_plan(tmp_path, urls=URLS, rows=None if private else {A1: public})
    plan = json.loads(path.read_text())
    for item in plan["items"]:
        if item["id"] in (A1, A2):
            item["target"]["collections"] = ["Transportation"]
    if edit:
        edit(plan)
    path.write_text(json.dumps(plan))
    return path


def _services(geolens) -> FakeImport:
    service = FakeImport(geolens, [])
    probe = service.probe

    def by_url(seen):
        service.layers = LAYERS[seen.json()["url"]]
        return probe(seen)

    geolens.routes["POST /services/probe/"] = by_url
    return service


def test_items_in_one_folder_share_a_collection(runner, tmp_path, geolens):
    _services(geolens)
    collections = FakeCollections(geolens)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", A1, "--only", A2)

    assert result.exit_code == 0, result.output
    assert collections.membership() == {
        "Transportation": {dataset_id("Roads"), dataset_id("Parcels")}
    }
    state = _state(plan_file)
    [collection] = collections.names
    assert state["collections"] == {"Transportation": collection}
    assert state["items"][A1]["collection_ids"] == [collection]


def test_a_name_held_by_another_collection_gets_the_portal_prefix(
    runner, tmp_path, geolens
):
    _services(geolens)
    collections = FakeCollections(geolens, taken=("Transportation",))
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", A1)

    assert result.exit_code == 0, result.output
    assert list(collections.membership()) == ["Example County GIS - Transportation"]


def test_a_failed_filing_is_redone_without_a_second_collection(
    runner, tmp_path, geolens
):
    _services(geolens)
    collections = FakeCollections(geolens)
    plan_file = _plan(tmp_path)
    create = collections.create

    def create_then_break_adding(seen):
        reply = create(seen)
        [collection] = collections.names
        geolens.routes[f"POST {COLLECTIONS}{collection}/datasets/"] = (
            500,
            _problem(500, "database unavailable"),
        )
        return reply

    geolens.routes[f"POST {COLLECTIONS}"] = create_then_break_adding
    result, _ = _migrate(runner, plan_file, "--only", A1)
    assert result.exit_code == 1
    entry = _state(plan_file)["items"][A1]
    assert entry["status"] == "failed" and "collection" in entry["error"]
    assert entry["dataset_ids"] == [dataset_id("Roads")]

    [collection] = collections.names
    geolens.routes[f"POST {COLLECTIONS}{collection}/datasets/"] = (
        lambda s: collections.add(collection, s)
    )
    geolens.routes[f"POST {COLLECTIONS}"] = collections.create
    result, _ = _migrate(runner, plan_file, "--only", A1)

    assert result.exit_code == 0, result.output
    assert len(collections.names) == 1
    assert collections.membership() == {"Transportation": {dataset_id("Roads")}}
    posts = [s for s in geolens.seen if s.url.endswith(COLLECTIONS)]
    assert len(posts) == 1


@pytest.mark.parametrize("mode", ["none", "group"])
def test_other_modes_file_nothing(runner, tmp_path, geolens, mode):
    _services(geolens)
    collections = FakeCollections(geolens)

    def edit(plan):
        plan["defaults"]["collection_from"] = mode
        for item in plan["items"]:
            if item["id"] == A1:
                item["target"]["groups"] = ["g1"]

    plan_file = _plan(tmp_path, edit)

    result, _ = _migrate(runner, plan_file, "--only", A1)

    assert result.exit_code == 0, result.output
    assert not collections.names
    assert not [s for s in geolens.seen if "/catalog/" in s.url]
    notes = _state(plan_file)["items"][A1]["notes"]
    assert bool(notes) == (mode == "group")
    if notes:
        assert "GeoLens groups" in notes[0]


def test_an_operator_without_manage_collections_skips_filing(runner, tmp_path, geolens):
    _services(geolens)
    geolens.routes[f"POST {COLLECTIONS}"] = (403, _problem(403, "Permission denied"))
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", A1, "--only", A2)

    assert result.exit_code == 0, result.output
    items = _state(plan_file)["items"]
    assert items[A1]["status"] == items[A2]["status"] == "done"
    assert "can't manage collections" in items[A1]["notes"][0]
    assert "can't manage collections" in items[A2]["notes"][0]
    assert len([s for s in geolens.seen if s.url.endswith(COLLECTIONS)]) == 1


def test_a_collection_error_echoing_the_token_is_redacted(runner, tmp_path, geolens):
    _services(geolens)
    token = secrets.token_urlsafe(16)
    geolens.routes[f"POST {COLLECTIONS}"] = (
        500,
        _problem(500, f"failed for token {token}"),
    )
    plan_file = _plan(tmp_path, private=True)

    result, _ = _migrate(runner, plan_file, "--only", A1, "--token", token)

    assert result.exit_code == 1
    error = _state(plan_file)["items"][A1]["error"]
    assert "token [REDACTED]" in error and token not in error
    assert token not in result.output


def test_a_service_with_many_layers_is_filed_in_batches(runner, tmp_path, geolens):
    names = [f"Layer{n:03d}" for n in range(130)]
    FakeImport(geolens, [_layer(n, name) for n, name in enumerate(names)])
    collections = FakeCollections(geolens)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    sizes = [
        len(s.json()["dataset_ids"])
        for s in geolens.seen
        if s.url.endswith("/datasets/") and s.method == "POST"
    ]
    assert sizes == [100, 30]
    assert len(collections.membership()["Transportation"]) == 130


def test_a_refused_add_to_a_known_collection_skips_filing(runner, tmp_path, geolens):
    _services(geolens)
    collections = FakeCollections(geolens)
    plan_file = _plan(tmp_path)
    _migrate(runner, plan_file, "--only", A1)
    [collection] = collections.names
    geolens.routes[f"POST {COLLECTIONS}{collection}/datasets/"] = (
        403,
        _problem(403, "Permission denied"),
    )
    state = _state(plan_file)
    state["items"][A2] = {"status": "pending"}
    (plan_file.parent / "arcgis-migration-state.json").write_text(json.dumps(state))

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][A2]
    assert entry["status"] == "done"
    assert "can't manage collections" in entry["notes"][0]


def test_a_collection_deleted_since_the_last_run_is_created_again(
    runner, tmp_path, geolens
):
    _services(geolens)
    collections = FakeCollections(geolens)
    plan_file = _plan(tmp_path)
    _migrate(runner, plan_file, "--only", A1)
    [old] = collections.names
    geolens.routes[f"POST {COLLECTIONS}{old}/datasets/"] = (
        404,
        _problem(404, "Collection not found"),
    )
    collections.names.clear()
    collections.members.clear()
    state = _state(plan_file)
    state["items"][A2] = {"status": "pending"}
    (plan_file.parent / "arcgis-migration-state.json").write_text(json.dumps(state))

    result, _ = _migrate(runner, plan_file, "--only", A2)

    assert result.exit_code == 0, result.output
    [new] = collections.names
    assert new != old
    assert _state(plan_file)["collections"] == {"Transportation": new}
    state = _state(plan_file)
    assert state["items"][A2]["collection_ids"] == [new]
    assert state["items"][A1]["collection_ids"] == [new]
    assert collections.members[new] == {dataset_id("Roads"), dataset_id("Parcels")}
