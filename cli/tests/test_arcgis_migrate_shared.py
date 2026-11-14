"""`geolens arcgis migrate`: plan items over the same ArcGIS service layer
share one dataset, which only the item owning that layer writes."""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from geolens_cli import arcgis_migrate_shared as shared_mod
from geolens_cli import arcgis_migrate_state as state_mod
from geolens_cli.arcgis_migrate_state import ItemState, MigrationState, StateError

from . import test_arcgis_migrate_layers as layers
from .arcgis_fake import A1, A2, A3, PORTAL
from .conftest import GEOLENS_INSTANCE
from .test_arcgis_migrate_collections import FakeCollections
from .test_arcgis_migrate_layers import (
    FakeImport,
    _layer,
    _migrate,
    _state,
    _write_plan,
    dataset_id,
)
from .test_arcgis_migrate_refresh import FakeRefresh

geolens = layers.geolens
quick = layers.quick

SERVICE = (
    "https://services1.arcgis.com/ExAmPlEoRg0123/arcgis/rest/services/"
    "Parcels/FeatureServer"
)
PARCELS, OWNERS, ROADS = (
    dataset_id("Parcels"),
    dataset_id("Owners"),
    dataset_id("Roads"),
)
TOKEN = secrets.token_urlsafe(16)
PREVIEW = "POST /services/preview/"
ALICE = "00000000-0000-0000-0000-0000000000a1"


class OneCopy(FakeImport):
    """GeoLens keeping one copy per source: a layer imported once answers 409
    to every later preview, a layer URL selects that layer, and every PATCH
    moves the dataset's updated_at on."""

    def _serve_dataset(self, dataset: str) -> None:
        super()._serve_dataset(dataset)
        route = f"PATCH /datasets/{dataset}"
        patch = self.fake.routes[route]

        def stamped(seen):
            patch(seen)
            fields = self.fields.setdefault(dataset, {})
            now = datetime.fromisoformat(fields.get("updated_at", layers.NOW))
            fields["updated_at"] = (now + timedelta(seconds=1)).isoformat()
            return self.dataset(dataset, seen.json().get("owner_id", layers.OPERATOR))

        if not getattr(patch, "stamped", False):
            stamped.stamped = True
            self.fake.routes[route] = stamped

    def probe(self, seen):
        found = super().probe(seen)
        layer = re.search(r"/FeatureServer/(\d+)/?$", seen.json()["url"])
        if layer:
            found["layers"] = [
                x for x in found["layers"] if str(x["layer_id"]) == layer.group(1)
            ]
        return {**found, "selected_layer_id": int(layer.group(1)) if layer else None}

    def commit(self, seen, name: str):
        answer = super().commit(seen, name)
        self.duplicates.setdefault(name, dataset_id(name))
        return answer


class NoOwners:
    """The earlier CLI: no item owns a shared layer."""

    def __init__(self, items, rows) -> None:
        self.items = {item["id"]: item for item in items}

    def dependencies(self) -> dict:
        return {}

    def service_of(self, item_id, entry) -> None:
        return None


def _plan(
    tmp_path: Path,
    *,
    url_first: bool,
    url_suffix: str = "",
    hosted: bool = True,
    hosted_access: str = "org",
) -> tuple[Path, str, str]:
    """A plan whose hosted item and URL item import SERVICE; (plan, hosted
    item id, URL item id). The URL item comes first in plan order when
    *url_first*."""
    url_item, hosted_item = (A1, A2) if url_first else (A2, A1)
    rows = {
        hosted_item: {
            "url": SERVICE,
            "hosted": hosted,
            "snippet": "From the hosted item",
            "tags": ["hosted"],
            "sharing": {"access": hosted_access, "groups": []},
            "title": "Hosted parcels",
        },
        url_item: {
            "url": SERVICE + url_suffix,
            "hosted": False,
            "snippet": "From the URL item",
            "tags": ["by-url"],
            "sharing": {
                "access": "org" if hosted_access == "public" else "public",
                "groups": [],
            },
            "title": "Parcels by URL",
        },
    }
    tmp_path.mkdir(exist_ok=True)
    path = _write_plan(tmp_path, rows=rows)
    plan = json.loads(path.read_text())
    for item in plan["items"]:
        if item["id"] in rows:
            item["target"]["collections"] = [f"{rows[item['id']]['title']} folder"]
    path.write_text(json.dumps(plan))
    return path, hosted_item, url_item


def _edit_plan(plan_file: Path, edit) -> None:
    plan = json.loads(plan_file.read_text())
    edit(plan)
    plan_file.write_text(json.dumps(plan))


def _migrated(runner, plan_file: Path, *items: str):
    only = [arg for item in items for arg in ("--only", item)]
    return _migrate(runner, plan_file, *only, "--token", TOKEN)


def _run(runner, plan_file: Path, *items: str):
    result, _ = _migrated(runner, plan_file, *items)
    assert result.exit_code == 0, result.output
    return _state(plan_file)["items"]


def _dataset(service: FakeImport, collections: FakeCollections, dataset: str) -> dict:
    fields = service.dataset(dataset, layers.OPERATOR)
    return {
        "title": fields["title"],
        "visibility": fields["visibility"],
        "summary": fields["summary"],
        "keywords": service.keywords.get(dataset, []),
        "collections": sorted(
            name for name, ids in collections.membership().items() if dataset in ids
        ),
    }


def _origin(service: FakeImport, dataset: str) -> str:
    return next(
        b["item_id"]
        for b in service.bodies(PREVIEW)
        if dataset_id(b["layer_name"]) == dataset
    )


def _writes(seen) -> list[tuple[str, str]]:
    return [
        (s.method, s.url.split("/api", 1)[1])
        for s in seen
        if s.method != "GET" and "/services/" not in s.url
    ]


def _fresh(tmp_path, geolens, service_class=OneCopy, **kwargs):
    geolens.seen.clear()
    service = service_class(
        geolens, [_layer(0, "Parcels"), _layer(1, "Owners", "Table")]
    )
    collections = FakeCollections(geolens)
    plan_file, hosted_item, url_item = _plan(tmp_path, **kwargs)
    return service, collections, plan_file, hosted_item, url_item


def _legacy(runner, plan_file, monkeypatch, *items: str) -> dict:
    """The state the earlier CLI leaves: a run and a rerun with no owner."""
    with monkeypatch.context() as m:
        m.setattr(layers.migrate, "SharedLayers", NoOwners)
        m.setattr(layers.migrate, "settle_recorded", lambda *args: False)
        _run(runner, plan_file, *items)
        _migrated(runner, plan_file, *items)
    return _state(plan_file)["items"]


# Fresh runs


@pytest.mark.parametrize("url_first", [True, False])
def test_the_hosted_item_owns_the_shared_dataset_in_either_plan_order(
    runner, tmp_path, geolens, url_first
):
    service, collections, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, url_first=url_first
    )

    items = _run(runner, plan_file, A1, A2)

    assert _dataset(service, collections, PARCELS) == {
        "title": "Hosted parcels - Parcels",
        "visibility": "internal",
        "summary": "From the hosted item",
        "keywords": ["hosted"],
        "collections": ["Hosted parcels folder"],
    }
    assert _origin(service, PARCELS) == hosted
    assert items[hosted]["status"] == "done"
    assert items[hosted]["dataset_ids"] == [PARCELS, OWNERS]
    assert not any("edited in GeoLens" in n for n in items[hosted]["notes"])
    entry = items[by_url]
    assert entry["status"] == "exists"
    assert entry["dataset_ids"] == [] and entry["layer_datasets"] == {}
    assert entry["shared"] == {"0": PARCELS, "1": OWNERS}
    assert entry["attachments"] == {} and entry["relationships"] == {}
    assert entry["notes"][0].startswith(
        f"reuses dataset {PARCELS} of item {hosted} (Hosted parcels)"
    )
    assert any(
        n.startswith(f"shared public in ArcGIS, more widely than item {hosted}")
        for n in entry["notes"]
    )


def test_both_plan_orders_send_the_same_writes(runner, tmp_path, geolens):
    logs = []
    for url_first in (True, False):
        _service, _c, plan_file, *_ = _fresh(
            tmp_path / str(url_first), geolens, url_first=url_first
        )
        _run(runner, plan_file, A1, A2)
        logs.append(_writes(geolens.seen))

    assert logs[0] == logs[1]


def test_the_borrower_sends_no_preview_and_no_write(runner, tmp_path, geolens):
    # A plain fake imports every preview again, as GeoLens does when the
    # items' target owners differ and its duplicate check doesn't see the copy.
    service, _c, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, service_class=FakeImport, url_first=False
    )
    _run(runner, plan_file, hosted)
    previews = len(service.bodies(PREVIEW))
    start = len(geolens.seen)

    items = _run(runner, plan_file, by_url)

    assert items[by_url]["status"] == "exists"
    assert items[by_url]["shared"] == {"0": PARCELS, "1": OWNERS}
    assert len(service.bodies(PREVIEW)) == previews
    assert _writes(geolens.seen[start:]) == []


def test_a_url_item_over_one_layer_borrows_only_that_layer(runner, tmp_path, geolens):
    service, collections, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, url_first=True, url_suffix="/1"
    )

    items = _run(runner, plan_file, A1, A2)

    assert items[by_url]["shared"] == {"1": OWNERS}
    assert items[by_url]["status"] == "exists"
    assert items[hosted]["dataset_ids"] == [PARCELS, OWNERS]
    assert _dataset(service, collections, OWNERS)["summary"] == "From the hosted item"


def test_without_a_hosted_item_the_first_in_plan_order_owns_it(
    runner, tmp_path, geolens
):
    service, collections, plan_file, _hosted, by_url = _fresh(
        tmp_path, geolens, url_first=True, hosted=False
    )

    items = _run(runner, plan_file, A1, A2)

    assert by_url == A1
    assert _dataset(service, collections, PARCELS)["summary"] == "From the URL item"
    assert items[A2]["status"] == "exists"
    assert items[A2]["shared"] == {"0": PARCELS, "1": OWNERS}


def test_layer_urls_and_the_root_share_layer_by_layer(runner, tmp_path, geolens):
    geolens.seen.clear()
    service = OneCopy(
        geolens,
        [_layer(0, "Parcels"), _layer(1, "Owners", "Table"), _layer(2, "Roads")],
    )
    FakeCollections(geolens)
    rows = {
        A1: {"url": SERVICE + "/0", "hosted": False},
        A2: {"url": SERVICE + "/1/", "hosted": False},
        A3: {"url": SERVICE, "hosted": False},
    }
    public = {"sharing": {"access": "public", "groups": []}}
    plan_file = _write_plan(
        tmp_path, rows={k: {**v, **public} for k, v in rows.items()}
    )

    items = _run(runner, plan_file, A1, A2, A3)

    assert items[A1]["layer_datasets"] == {"0": PARCELS}
    assert items[A2]["layer_datasets"] == {"1": OWNERS}
    assert items[A3]["layer_datasets"] == {"2": ROADS}
    assert items[A3]["shared"] == {"0": PARCELS, "1": OWNERS}
    assert {_origin(service, d) for d in (PARCELS, OWNERS, ROADS)} == {A1, A2, A3}


# Reruns


def test_a_rerun_leaves_the_shared_dataset_to_its_owner(runner, tmp_path, geolens):
    service, collections, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, url_first=True, hosted_access="public"
    )
    _run(runner, plan_file, A1, A2)
    before = _dataset(service, collections, PARCELS)
    notes = _state(plan_file)["items"][by_url]["notes"]
    FakeRefresh(geolens, service).allow(PARCELS, OWNERS)
    start = len(geolens.seen)

    items = _run(runner, plan_file, A1, A2)

    assert _dataset(service, collections, PARCELS) == before
    assert items[by_url]["notes"] == notes
    assert items[by_url]["stale"] == [] and items[hosted]["stale"] == []
    sent = [s.body for s in geolens.seen[start:] if s.method != "GET"]
    assert sent and not any(b"From the URL item" in body for body in sent)

    again = _run(runner, plan_file, A1, A2)

    assert again[by_url]["notes"] == notes
    assert again[hosted]["notes"] == items[hosted]["notes"]
    assert again[by_url]["stale"] == [] and again[hosted]["stale"] == []


def test_a_reordered_plan_keeps_the_recorded_owner(runner, tmp_path, geolens):
    service, _c, plan_file, _hosted, _by_url = _fresh(
        tmp_path, geolens, url_first=True, hosted=False
    )
    _run(runner, plan_file, A1, A2)
    FakeRefresh(geolens, service).allow(PARCELS, OWNERS)
    _edit_plan(plan_file, lambda plan: plan["items"].sort(key=lambda i: i["id"] != A2))
    # The plan now picks A2, which imports afresh.
    state_file = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(state_file.read_text())
    del state["items"][A2]
    state_file.write_text(json.dumps(state))

    items = _run(runner, plan_file, A1, A2)

    assert items[A1]["layer_datasets"] == {"0": PARCELS, "1": OWNERS}
    assert items[A2]["shared"] == {"0": PARCELS, "1": OWNERS}
    assert items[A2]["layer_datasets"] == {}


@pytest.mark.parametrize("gone", ["skip", "removed"])
def test_a_borrower_whose_owner_left_the_plan_reports_it(
    runner, tmp_path, geolens, gone
):
    _service, _c, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, url_first=True, hosted_access="public"
    )
    _run(runner, plan_file, A1, A2)

    def drop(plan):
        item = next(i for i in plan["items"] if i["id"] == hosted)
        if gone == "skip":
            item["action"] = "skip"
        else:
            item["removed"] = True

    _edit_plan(plan_file, drop)

    result, payload = _migrated(runner, plan_file, by_url)

    assert result.exit_code != 0
    [reason, *_] = payload["not_up_to_date"][by_url]
    assert reason == (
        f"dataset {PARCELS} belongs to item {hosted}, which the plan no longer "
        "migrates; this item doesn't import or refresh it"
    )
    assert _state(plan_file)["items"][by_url]["layer_datasets"] == {}


def test_an_owner_added_later_borrows_from_the_item_that_recorded_it(
    runner, tmp_path, geolens
):
    _service, _c, plan_file, hosted, by_url = _fresh(tmp_path, geolens, url_first=True)
    _edit_plan(
        plan_file,
        lambda plan: next(i for i in plan["items"] if i["id"] == hosted).update(
            removed=True
        ),
    )
    _run(runner, plan_file, by_url)
    _edit_plan(
        plan_file,
        lambda plan: next(i for i in plan["items"] if i["id"] == hosted).pop("removed"),
    )

    _migrated(runner, plan_file, A1, A2)
    items = _state(plan_file)["items"]

    assert items[by_url]["layer_datasets"] == {"0": PARCELS, "1": OWNERS}
    assert items[hosted]["shared"] == {"0": PARCELS, "1": OWNERS}
    assert items[hosted]["status"] == "exists"


def test_a_layer_its_owner_has_not_imported_waits_for_it(runner, tmp_path, geolens):
    service, _c, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, url_first=False, url_suffix="/1"
    )
    service.layers = [_layer(0, "Parcels")]
    _run(runner, plan_file, hosted)
    # The layer is added to the service after the owner was migrated.
    service.layers = [_layer(0, "Parcels"), _layer(1, "Owners", "Table")]
    previews = len(service.bodies(PREVIEW))

    result, _ = _migrated(runner, plan_file, by_url)

    assert result.exit_code != 0
    entry = _state(plan_file)["items"][by_url]
    assert entry["status"] == "failed"
    assert entry["error"].startswith(f"layer 1 belongs to item {hosted}")
    assert len(service.bodies(PREVIEW)) == previews


def test_a_retry_after_a_failed_write_keeps_another_users_edit(
    runner, tmp_path, geolens, monkeypatch
):
    service, _c, plan_file, hosted, _by_url = _fresh(tmp_path, geolens, url_first=False)

    def fail(*args, **kwargs):
        raise layers.session.ItemFailed("writing the item metadata failed")

    with monkeypatch.context() as m:
        m.setattr(layers.migrate, "apply_item_metadata", fail)
        _migrated(runner, plan_file, hosted)
    assert _state(plan_file)["items"][hosted]["status"] == "failed"
    service.fields[PARCELS].update(
        title="Alice's title", updated_by=ALICE, updated_at="2026-10-05T00:00:00Z"
    )

    for _attempt in range(2):
        _migrated(runner, plan_file, A1, A2)
        assert service.fields[PARCELS]["title"] == "Alice's title"
        assert "changed" in _state(plan_file)["items"][hosted]["error"]


# State from the earlier CLI


@pytest.mark.parametrize("url_first", [True, False])
def test_a_state_from_before_ownership_converges_on_a_rerun(
    runner, tmp_path, geolens, monkeypatch, url_first
):
    service, collections, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, url_first=url_first, hosted_access="public"
    )
    FakeRefresh(geolens, service).allow(PARCELS, OWNERS)
    old = _legacy(runner, plan_file, monkeypatch, A1, A2)
    first, second = (by_url, hosted) if url_first else (hosted, by_url)
    assert PARCELS in old[by_url]["layer_datasets"].values()
    assert any("changed in GeoLens" in s for s in old[first]["stale"])
    # The note dedupe: the earlier rerun didn't add the false note twice.
    edited = [n for n in old[second]["notes"] if "edited in GeoLens" in n]
    assert edited and len(edited) == len(set(edited))

    items = _run(runner, plan_file, A1, A2)

    dataset = _dataset(service, collections, PARCELS)
    assert dataset["title"] == "Hosted parcels - Parcels"
    assert dataset["visibility"] == "public"
    assert dataset["summary"] == "From the hosted item"
    assert items[hosted]["stale"] == [] and items[by_url]["stale"] == []
    assert not any("edited in GeoLens" in n for n in items[hosted]["notes"])
    assert not any("edited in GeoLens" in n for n in items[by_url]["notes"])
    assert items[by_url]["shared"] == {"0": PARCELS, "1": OWNERS}
    # Nothing moved: the borrower's own records stay as the earlier CLI left them.
    for name in ("metadata_baseline", "last_update", "visibility", "groups"):
        assert items[by_url][name] == old[by_url][name], name
    assert items[hosted]["layer_datasets"] == old[hosted]["layer_datasets"]

    again = _run(runner, plan_file, A1, A2)

    assert again[hosted]["stale"] == [] and again[by_url]["stale"] == []
    assert again[hosted]["notes"] == items[hosted]["notes"]
    assert again[by_url]["notes"] == items[by_url]["notes"]
    assert _dataset(service, collections, PARCELS) == dataset


def test_another_users_edit_of_a_legacy_dataset_is_kept_on_every_rerun(
    runner, tmp_path, geolens, monkeypatch
):
    service, _c, plan_file, hosted, _by_url = _fresh(
        tmp_path, geolens, url_first=True, hosted_access="public"
    )
    FakeRefresh(geolens, service).allow(PARCELS, OWNERS)
    _legacy(runner, plan_file, monkeypatch, A1, A2)
    service.fields[PARCELS].update(
        title="Alice's title", updated_by=ALICE, updated_at="2026-10-05T00:00:00Z"
    )

    for _attempt in range(2):
        _migrated(runner, plan_file, A1, A2)
        assert service.fields[PARCELS]["title"] == "Alice's title"
        [reason] = [
            s for s in _state(plan_file)["items"][hosted]["stale"] if PARCELS in s
        ]
        assert "changed in GeoLens" in reason


def test_an_unsettled_refresh_of_the_other_item_leaves_the_dataset_alone(
    runner, tmp_path, geolens, monkeypatch
):
    service, _c, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, url_first=False, hosted_access="public"
    )
    FakeRefresh(geolens, service).allow(PARCELS, OWNERS)
    _legacy(runner, plan_file, monkeypatch, A1, A2)
    state_file = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(state_file.read_text())
    state["items"][by_url]["refreshing"][PARCELS] = {"pending": 1, "revision": 0}
    state_file.write_text(json.dumps(state))
    start = len(geolens.seen)

    _migrated(runner, plan_file, A1, A2)

    [reason] = [s for s in _state(plan_file)["items"][hosted]["stale"] if PARCELS in s]
    assert "hasn't settled" in reason
    assert not [w for w in _writes(geolens.seen[start:]) if PARCELS in w[1]]


def test_groups_a_legacy_borrower_granted_are_reported_not_removed():
    owner = ItemState(
        status="done", layer_datasets={"0": PARCELS}, dataset_ids=[PARCELS]
    )
    owner.groups = {PARCELS: ["g-a"]}
    other = ItemState(
        status="done", layer_datasets={"0": PARCELS}, dataset_ids=[PARCELS]
    )
    other.groups, other.granted = {PARCELS: ["g-a", "g-b"]}, {PARCELS: ["g-b"]}
    items = [
        {"id": A1, "action": "import_layers", "title": "H", "target": {"title": None}},
        {"id": A2, "action": "import_layers", "title": "U", "target": {"title": None}},
    ]
    rows = {A1: {"url": SERVICE, "hosted": True}, A2: {"url": SERVICE + "/0"}}

    changed = shared_mod.settle_recorded(
        {A1: owner, A2: other}, shared_mod.SharedLayers(items, rows), {"g-b": "Field"}
    )

    assert changed
    assert other.granted == {PARCELS: ["g-b"]} and other.shared == {"0": PARCELS}
    assert (
        f"group Field was granted on dataset {PARCELS} by item {A2} in an earlier "
        "run and is no longer managed; remove it in GeoLens if it shouldn't have "
        "access"
    ) in owner.notes
    assert owner.layer_datasets == {"0": PARCELS}


# Ownership rules


def _items(*ids: str) -> list[dict]:
    return [{"id": i, "action": "import_layers", "depends_on": []} for i in ids]


def test_each_layer_has_its_own_owner_and_only_shared_layers_add_dependencies():
    rows = {
        "l0": {"url": SERVICE + "/0", "hosted": False},
        "l1": {"url": SERVICE + "/1", "hosted": False},
        "root": {"url": SERVICE, "hosted": False},
    }
    layers_ = shared_mod.SharedLayers(_items("l0", "l1", "root"), rows)

    assert layers_.dependencies() == {"root": ["l0", "l1"]}
    assert [layers_.plan_owner("root", k)["id"] for k in ("0", "1", "2")] == [
        "l0",
        "l1",
        "root",
    ]
    disjoint = shared_mod.SharedLayers(_items("l0", "l1"), rows)
    assert disjoint.dependencies() == {}


def test_the_hosted_root_owns_every_layer_it_shares():
    rows = {
        "l0": {"url": SERVICE + "/0", "hosted": False},
        "root": {"url": SERVICE, "hosted": True},
        "other": {"url": SERVICE.upper() + "/", "hosted": False},
    }
    layers_ = shared_mod.SharedLayers(_items("l0", "root", "other"), rows)

    assert layers_.dependencies() == {"l0": ["root"], "other": ["root"]}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (SERVICE, None),
        (SERVICE + "/", None),
        (SERVICE + "?f=json", None),
        (SERVICE + "/query", None),
        (SERVICE + "/query/?where=1%3D1", None),
        (SERVICE + "/3", "3"),
        (SERVICE + "/3/", "3"),
        (SERVICE + "/3/query", "3"),
        (SERVICE + "/3/QUERY?outFields=*", "3"),
        (SERVICE.upper() + "/3", "3"),
        (SERVICE.replace("FeatureServer", "MapServer") + "/3", "3"),
    ],
)
def test_every_url_spelling_the_service_import_accepts_names_the_same_layer(
    url, expected
):
    service, layer = shared_mod.service_layer(url)

    assert service == SERVICE.lower().replace(
        "featureserver", "mapserver" if "MapServer" in url else "featureserver"
    )
    assert layer == expected


def test_a_url_that_is_not_a_service_names_none():
    assert shared_mod.service_layer("https://example.com/data.csv") is None
    assert shared_mod.service_layer(SERVICE + "/3/extra") is None


def test_the_released_cli_refuses_a_state_file_this_version_writes(
    tmp_path, monkeypatch
):
    path = tmp_path / "state.json"
    state = MigrationState(path, PORTAL, GEOLENS_INSTANCE, str)
    state.items[A1] = ItemState(status="exists", shared={"0": PARCELS})
    state.save()
    assert json.loads(path.read_text())["schema_version"] == "7"
    monkeypatch.setattr(state_mod, "_READABLE_VERSIONS", ("1", "2", "3", "4", "5", "6"))

    with pytest.raises(StateError):
        MigrationState.load(path, PORTAL, GEOLENS_INSTANCE, str)
