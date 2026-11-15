"""`geolens arcgis migrate`: plan items over the same ArcGIS service layer
share one dataset, which only the item owning that layer writes."""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from geolens_cli import arcgis_migrate_cutover as cutover_mod
from geolens_cli import arcgis_migrate_layers as layers_mod
from geolens_cli import arcgis_migrate_session as session
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
                x for x in found["layers"] if x["layer_id"] == int(layer.group(1))
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

    def dependencies(self, items, blocking=False) -> dict:
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
        m.setattr(shared_mod, "may_write", lambda *args: None)
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


def _add_hosted_root(plan_file: Path, hosted: str, *, removed: bool) -> None:
    def edit(plan):
        item = next(i for i in plan["items"] if i["id"] == hosted)
        if removed:
            item["removed"] = True
        else:
            item.pop("removed", None)

    _edit_plan(plan_file, edit)


def _alice_edits(service, dataset: str) -> None:
    service.fields[dataset].update(
        title="Alice's title", updated_by=ALICE, updated_at="2026-10-05T00:00:00Z"
    )


@pytest.mark.parametrize(
    ("pending", "only_hosted"), [(True, False), (False, False), (True, True)]
)
def test_an_item_holding_a_layer_keeps_it_when_a_hosted_root_is_added(
    runner, tmp_path, geolens, pending, only_hosted
):
    service, _c, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, url_first=True, hosted_access="public", url_suffix="/0"
    )
    _add_hosted_root(plan_file, hosted, removed=True)
    _run(runner, plan_file, by_url)
    if pending:
        # The import stopped after its commit; its job finished without it.
        state_file = plan_file.parent / "arcgis-migration-state.json"
        state = json.loads(state_file.read_text())
        entry = state["items"][by_url]
        entry.update(
            status="failed",
            layer_datasets={},
            dataset_ids=[],
            layer_jobs={"0": entry["job_ids"][0]},
            import_pass=None,
            last_update={},
        )
        state_file.write_text(json.dumps(state))
    _alice_edits(service, PARCELS)
    _add_hosted_root(plan_file, hosted, removed=False)
    previews = len(service.bodies(PREVIEW))

    # --only the hosted item runs the holder first; the hosted item then
    # borrows what the holder's job settled.
    result, payload = _migrated(runner, plan_file, hosted if only_hosted else by_url)

    assert result.exit_code != 0
    assert payload["waiting"] == []
    assert service.fields[PARCELS]["title"] == "Alice's title"
    if only_hosted:
        assert _state(plan_file)["items"][hosted]["shared"] == {"0": PARCELS}
    else:
        assert hosted not in _state(plan_file)["items"]
    assert not [
        b for b in service.bodies(PREVIEW)[previews:] if b["layer_name"] == "Parcels"
    ]
    entry = _state(plan_file)["items"][by_url]
    assert entry["layer_datasets"] == {"0": PARCELS}
    assert "changed" in (entry["error"] or " ".join(entry["stale"]))

    _migrated(runner, plan_file, A1, A2)

    items = _state(plan_file)["items"]
    assert service.fields[PARCELS]["title"] == "Alice's title"
    assert items[hosted]["shared"] == {"0": PARCELS}
    assert {b["item_id"] for b in service.bodies(PREVIEW)[previews:]} <= {hosted}
    assert not [
        b for b in service.bodies(PREVIEW)[previews:] if b["layer_name"] == "Parcels"
    ]


# State from the earlier CLI


def _double(plan_file: Path) -> str:
    items = _state(plan_file)["items"]
    assert PARCELS in items[A1]["layer_datasets"].values()
    assert PARCELS in items[A2]["layer_datasets"].values()
    return (
        f"dataset {PARCELS} is recorded by items {A1}, {A2}, as an earlier version "
        "of this command left it; none of them writes it until all but one are "
        "set to skip in the plan"
    )


@pytest.mark.parametrize(
    ("url_first", "status"), [(True, "done"), (False, "done"), (True, "failed")]
)
def test_a_dataset_two_items_recorded_is_written_by_neither(
    runner, tmp_path, geolens, monkeypatch, url_first, status
):
    service, _c, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, url_first=url_first, hosted_access="public"
    )
    FakeRefresh(geolens, service).allow(PARCELS, OWNERS)
    _legacy(runner, plan_file, monkeypatch, A1, A2)
    reason = _double(plan_file)
    # An unsettled refresh one of them recorded stays as it is.
    state_file = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(state_file.read_text())
    state["items"][by_url]["refreshing"][PARCELS] = {"pending": 1, "revision": 0}
    if status == "failed":
        # Imported again rather than refreshed, and failed before it recorded
        # a last update: every write of the import is open to it.
        for item in (A1, A2):
            state["items"][item].update(status="failed", last_update={})
        # The portal item changed since, so its metadata has something to write.
        inventory_file = plan_file.parent / "arcgis-inventory.json"
        inventory = json.loads(inventory_file.read_text())
        for row in inventory["items"]:
            if row["id"] in (A1, A2):
                row["access_information"] = "Example County GIS"
        inventory_file.write_text(json.dumps(inventory))
        _edit_plan(
            plan_file,
            lambda plan: next(i for i in plan["items"] if i["id"] == hosted)[
                "target"
            ].update(visibility="private"),
        )
    state_file.write_text(json.dumps(state))
    before = _state(plan_file)["items"]
    start = len(geolens.seen)

    result, payload = _migrated(runner, plan_file, A1, A2)

    assert result.exit_code != 0
    sent = [s for s in geolens.seen[start:] if s.method != "GET"]
    for dataset in (PARCELS, OWNERS):
        assert not [
            s for s in sent if dataset in s.url or dataset.encode() in s.body
        ], dataset
    items = _state(plan_file)["items"]
    for item in (A1, A2):
        if status == "failed" and item == by_url:
            # It waits on the hosted item, which owns the layers nobody holds.
            assert payload["waiting"] == [{"item": by_url, "waiting_on": [hosted]}]
            continue
        found = payload["not_up_to_date"].get(item) or [items[item]["error"]]
        assert sum(reason in r for r in found) == 1, found
    after = _state(plan_file)["items"]
    for item in (A1, A2):
        for name in (
            "layer_datasets",
            "metadata_baseline",
            "last_update",
            "visibility",
        ):
            assert after[item][name] == before[item][name], (item, name)
    assert after[by_url]["refreshing"] == before[by_url]["refreshing"]


def test_cutover_refuses_a_double_recorded_dataset_whatever_is_accepted(
    runner, tmp_path, geolens, monkeypatch
):
    service, _c, plan_file, _hosted, _by_url = _fresh(
        tmp_path, geolens, url_first=True, hosted_access="public"
    )
    FakeRefresh(geolens, service).allow(PARCELS, OWNERS)
    _legacy(runner, plan_file, monkeypatch, A1, A2)
    _double(plan_file)

    def only_these(plan):
        for item in plan["items"]:
            if item["id"] not in (A1, A2):
                item["action"] = "skip"

    _edit_plan(plan_file, only_these)

    _result, payload = _migrate(
        runner,
        plan_file,
        "--token",
        TOKEN,
        "--cutover",
        *(f"--accept-{c}" for c in cutover_mod.CHECKS),
    )

    cutover = payload["cutover"]
    assert cutover["marked"] is False
    assert cutover["refused"] == [cutover_mod.DOUBLE_RECORDED]
    [found] = [c for c in cutover["checks"] if c["check"] == "double-recorded-datasets"]
    assert {f["item"] for f in found["items"]} == {f"{A1}, {A2}"}


def test_once_the_plan_skips_one_the_other_refreshes_it_on_its_own_records(
    runner, tmp_path, geolens, monkeypatch
):
    service, _c, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, url_first=True, hosted_access="public"
    )
    refresh = FakeRefresh(geolens, service).allow(PARCELS, OWNERS)
    _legacy(runner, plan_file, monkeypatch, A1, A2)
    _double(plan_file)
    _edit_plan(
        plan_file,
        lambda plan: next(i for i in plan["items"] if i["id"] == by_url).update(
            action="skip"
        ),
    )
    skipped = _state(plan_file)["items"][by_url]
    refreshed = len(refresh.bodies)

    items = _run(runner, plan_file, hosted)

    assert items[hosted]["stale"] == []
    assert len(refresh.bodies) == refreshed + 2
    assert items[hosted]["layer_datasets"] == {"0": PARCELS, "1": OWNERS}
    assert {k: v for k, v in items[by_url].items() if k != "status"} == {
        k: v for k, v in skipped.items() if k != "status"
    }


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

    assert layers_.dependencies({}) == {"root": ["l0", "l1"]}
    assert [layers_.plan_owner("root", k)["id"] for k in ("0", "1", "2")] == [
        "l0",
        "l1",
        "root",
    ]
    disjoint = shared_mod.SharedLayers(_items("l0", "l1"), rows)
    assert disjoint.dependencies({}) == {}


def test_the_hosted_root_owns_every_layer_it_shares():
    rows = {
        "l0": {"url": SERVICE + "/0", "hosted": False},
        "root": {"url": SERVICE, "hosted": True},
        "other": {"url": SERVICE.upper() + "/", "hosted": False},
    }
    layers_ = shared_mod.SharedLayers(_items("l0", "root", "other"), rows)

    assert layers_.dependencies({}) == {"l0": ["root"], "other": ["root"]}


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


def test_a_zero_padded_layer_id_is_that_layer():
    assert shared_mod.service_layer(SERVICE + "/01") == (SERVICE.lower(), "1")


def test_ipv6_hosts_keep_their_brackets():
    with_port = shared_mod.service_layer(
        "https://[2606:4700:4700::1111]:443/arcgis/rest/services/P/FeatureServer"
    )
    longer = shared_mod.service_layer(
        "https://[2606:4700:4700::1111:443]/arcgis/rest/services/P/FeatureServer"
    )

    assert with_port[0].startswith("https://[2606:4700:4700::1111]:443/")
    assert longer[0].startswith("https://[2606:4700:4700::1111:443]/")
    assert with_port != longer
    rows = {"a": {"url": with_port[0]}, "b": {"url": longer[0]}}
    assert shared_mod.SharedLayers(_items("a", "b"), rows).dependencies({}) == {}


def test_a_zero_padded_layer_url_and_the_root_run_without_waiting(
    runner, tmp_path, geolens
):
    geolens.seen.clear()
    OneCopy(geolens, [_layer(0, "Parcels"), _layer(1, "Owners", "Table")])
    FakeCollections(geolens)
    public = {"sharing": {"access": "public", "groups": []}}
    plan_file = _write_plan(
        tmp_path,
        rows={
            A1: {"url": SERVICE + "/01", "hosted": False, **public},
            A2: {"url": SERVICE, "hosted": False, **public},
        },
    )

    items = _run(runner, plan_file, A1, A2)

    assert items[A1]["layer_datasets"] == {"1": OWNERS}
    assert items[A2]["layer_datasets"] == {"0": PARCELS}
    assert items[A2]["shared"] == {"1": OWNERS}


def test_holders_that_would_wait_on_each_other_run_in_plan_order():
    rows = {"a": {"url": SERVICE}, "b": {"url": SERVICE.upper()}}
    items = {
        "a": ItemState(status="failed", service_url=SERVICE, layer_jobs={"0": "j0"}),
        "b": ItemState(status="failed", service_url=SERVICE, layer_jobs={"1": "j1"}),
    }

    deps = shared_mod.SharedLayers(_items("a", "b"), rows).dependencies(items)

    assert deps == {"b": ["a"]}


# Every write is checked when it is made


def _pending(plan_file: Path, item: str, layer: str, job: str, **extra) -> None:
    """Leave *item* as an import that stopped after committing *job*."""
    inventory = json.loads((plan_file.parent / "arcgis-inventory.json").read_text())
    url = next(row["url"] for row in inventory["items"] if row["id"] == item)
    state_file = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(state_file.read_text())
    entry = state["items"].setdefault(item, {"status": "failed"})
    entry.update(
        status="failed",
        service_url=url,
        layer_datasets={},
        dataset_ids=[],
        layer_jobs={layer: job},
        import_pass=None,
        last_update={},
        **extra,
    )
    state_file.write_text(json.dumps(state))


def test_a_pending_job_that_settles_on_another_items_dataset_writes_nothing(
    runner, tmp_path, geolens
):
    service, _c, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, url_first=False, hosted_access="public"
    )
    _run(runner, plan_file, hosted)
    # The URL item's earlier import committed the job that made that dataset.
    job = _state(plan_file)["items"][hosted]["job_ids"][0]
    _pending(plan_file, by_url, "0", job)
    start = len(geolens.seen)

    result, _ = _migrated(runner, plan_file, by_url)

    assert result.exit_code != 0
    entry = _state(plan_file)["items"][by_url]
    assert entry["status"] == "failed"
    assert f"dataset {PARCELS} is recorded by items" in entry["error"]
    assert not [
        s
        for s in geolens.seen[start:]
        if s.method != "GET" and (PARCELS in s.url or PARCELS.encode() in s.body)
    ]


def test_every_dataset_writer_asks_before_it_writes(monkeypatch):
    from geolens_cli import arcgis_item_metadata as metadata_mod
    from geolens_cli import arcgis_migrate_collections as collections_mod
    from geolens_cli import arcgis_migrate_groups as groups_mod
    from geolens_cli import arcgis_migrate_refresh as refresh_mod

    asked: list[str] = []

    def refuse(ctx, entry, dataset):
        asked.append(dataset)
        return "refused"

    monkeypatch.setattr(shared_mod, "may_write", refuse)

    class NoGeoLens:
        def __getattr__(self, name):
            raise AssertionError(f"GeoLens was called ({name})")

    entry = ItemState(
        status="done", layer_datasets={"0": PARCELS}, dataset_ids=[PARCELS]
    )
    item = {
        "id": A1,
        "action": "import_layers",
        "title": "Parcels",
        "owner": "gis_admin",
        "target": {
            "title": None,
            "visibility": "restricted",
            "collections": ["Folder"],
            "geolens_groups": ["g1"],
            "groups": [],
            "tags": ["t"],
        },
    }
    ctx = session.MigrationContext(
        geolens=NoGeoLens(),
        inventory={A1: {"id": A1, "snippet": "s", "url": SERVICE}},
        portal=None,
        save=lambda: None,
        items={A1: entry},
    )
    owner = layers.migrate.Owner(id=layers.OPERATOR, username="operator")
    writers = {
        "target": lambda: layers_mod._apply_target(
            ctx, entry, PARCELS, SimpleNamespace(title="t", visibility="private")
        ),
        "metadata": lambda: metadata_mod.apply_item_metadata(ctx, item, entry),
        "collections": lambda: collections_mod.file_into_collections(ctx, item, entry),
        "sharing": lambda: groups_mod.share(ctx, item, entry),
        "transfer": lambda: layers.migrate.transfer(ctx, entry, owner, {}),
        "keep_own": lambda: layers.migrate._keep_own(ctx, entry, owner, {}),
        "handover": lambda: layers.migrate._hand_over_one(ctx, entry, owner),
        "refresh": lambda: refresh_mod._bring_each(ctx, item, entry, None),
    }

    for name, write in writers.items():
        asked.clear()
        try:
            write()
        except session.ItemFailed as exc:
            assert "refused" in str(exc), name
        assert PARCELS in asked, name


def test_a_recovered_jobs_dataset_is_kept_in_the_items_datasets(
    runner, tmp_path, geolens
):
    service = FakeImport(geolens, [_layer(0, "Parcels")])
    plan_file = _write_plan(tmp_path)
    _run(runner, plan_file, A2)
    job = _state(plan_file)["items"][A2]["job_ids"][0]
    _pending(plan_file, A2, "0", job, job_ids=[job])
    patch = geolens.routes[f"PATCH /datasets/{PARCELS}"]
    geolens.routes[f"PATCH /datasets/{PARCELS}"] = (
        500,
        {"title": "Error", "status": 500, "detail": "boom"},
    )

    _migrated(runner, plan_file, A2)

    entry = _state(plan_file)["items"][A2]
    assert entry["status"] == "failed"
    assert entry["layer_datasets"] == {"0": PARCELS}
    assert entry["dataset_ids"] == [PARCELS]

    # A state that pinned the layer without listing its dataset gets it back.
    state_file = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(state_file.read_text())
    state["items"][A2]["dataset_ids"] = []
    state_file.write_text(json.dumps(state))
    geolens.routes[f"PATCH /datasets/{PARCELS}"] = patch

    items = _run(runner, plan_file, A2)

    assert items[A2]["dataset_ids"] == [PARCELS]
    assert service.fields[PARCELS]["visibility"] == "public"


def test_two_roots_each_holding_a_pending_job_both_finish(runner, tmp_path, geolens):
    service, _c, plan_file, _hosted, _by_url = _fresh(
        tmp_path, geolens, url_first=True, hosted=False, hosted_access="public"
    )
    _edit_plan(
        plan_file,
        lambda plan: next(i for i in plan["items"] if i["id"] == A2).update(
            removed=True
        ),
    )
    _run(runner, plan_file, A1)
    jobs = _state(plan_file)["items"][A1]["job_ids"]
    _pending(plan_file, A1, "0", jobs[0])
    _pending(plan_file, A2, "1", jobs[1])
    _edit_plan(
        plan_file,
        lambda plan: next(i for i in plan["items"] if i["id"] == A2).pop("removed"),
    )
    previews = len(service.bodies(PREVIEW))

    # Each settles its own pending job before either borrows, so one run does.
    _migrated(runner, plan_file, A1, A2)

    items = _state(plan_file)["items"]
    assert items[A1]["status"] in ("done", "exists"), items[A1]["error"]
    assert items[A2]["status"] in ("done", "exists"), items[A2]["error"]
    assert items[A1]["layer_datasets"] == {"0": PARCELS}
    assert items[A1]["shared"] == {"1": OWNERS}
    assert items[A2]["layer_datasets"] == {"1": OWNERS}
    assert items[A2]["shared"] == {"0": PARCELS}
    assert len(service.bodies(PREVIEW)) == previews
    FakeRefresh(geolens, service).allow(PARCELS, OWNERS)
    for dataset in (PARCELS, OWNERS):
        service.fields[dataset]["origin_ref"] = {"url": SERVICE}

    again = _run(runner, plan_file, A1, A2)

    assert again[A1]["stale"] == [] and again[A2]["stale"] == []
    assert len(service.bodies(PREVIEW)) == previews


@pytest.mark.parametrize(
    ("group", "loss"),
    [
        (None, "maps to no GeoLens group"),
        ({"id": "x", "name": "G", "members_unread": "403"}, "weren't read"),
        ({"id": "x", "name": "G", "unsynced": [{"member": "bob"}]}, "aren't in"),
    ],
)
def test_a_restricted_borrower_still_reports_its_sharing_losses(tmp_path, group, loss):
    plan = json.loads(_write_plan(tmp_path).read_text())
    item = next(i for i in plan["items"] if i["id"] == A1)
    item["target"].update(visibility="restricted", groups=["g1"])
    state = MigrationState(tmp_path / "s.json", PORTAL, GEOLENS_INSTANCE, str)
    state.items[A1] = ItemState(status="exists", shared={"0": PARCELS})
    if group is not None:
        state.groups["g1"] = group

    losses = cutover_mod.sharing_losses(plan, state, item)

    assert any(loss in reason for reason in losses), losses
    # Its group stays in use while only its records name the item.
    item["unlisted"] = True
    assert "g1" in cutover_mod.groups_in_use(plan, state)


def test_an_items_own_copy_of_a_layer_another_item_owns_is_not_written(
    runner, tmp_path, geolens
):
    service, _c, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, url_first=True, hosted_access="public"
    )
    _run(runner, plan_file, A1, A2)
    # An earlier version imported a second copy of layer 0 for the URL item.
    copy = dataset_id("Second copy")
    service._serve_dataset(copy)
    state_file = plan_file.parent / "arcgis-migration-state.json"
    state = json.loads(state_file.read_text())
    state["items"][by_url].update(
        layer_datasets={"0": copy}, dataset_ids=[copy], shared={"1": OWNERS}
    )
    state_file.write_text(json.dumps(state))
    FakeRefresh(geolens, service).allow(PARCELS, OWNERS, copy)
    start = len(geolens.seen)

    _migrated(runner, plan_file, A1, A2)

    [reason] = [s for s in _state(plan_file)["items"][by_url]["stale"] if copy in s]
    assert f"this item's copy of layer 0, which item {hosted}" in reason
    assert not [s for s in geolens.seen[start:] if s.method != "GET" and copy in s.url]


def test_a_new_item_over_a_layer_only_a_departed_item_holds_imports_nothing(
    runner, tmp_path, geolens
):
    service, _c, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, service_class=FakeImport, url_first=False
    )
    _run(runner, plan_file, hosted)
    _edit_plan(
        plan_file,
        lambda plan: next(i for i in plan["items"] if i["id"] == hosted).update(
            action="skip"
        ),
    )
    previews = len(service.bodies(PREVIEW))

    result, _ = _migrated(runner, plan_file, by_url)

    assert result.exit_code != 0
    entry = _state(plan_file)["items"][by_url]
    assert f"dataset {PARCELS} belongs to item {hosted}" in entry["error"]
    assert len(service.bodies(PREVIEW)) == previews


def test_a_layer_its_owner_refused_for_good_is_refused_for_the_borrower_too(
    runner, tmp_path, geolens
):
    service, _c, plan_file, hosted, by_url = _fresh(
        tmp_path, geolens, url_first=False, url_suffix="/1"
    )
    layers._refuse_preview(geolens, service, "Owners", layers.MULTIPATCH)
    items = _run(runner, plan_file, hosted)
    assert items[hosted]["status"] == "done"
    assert set(items[hosted]["refused_layers"]) == {"1"}
    previews = len(service.bodies(PREVIEW))

    result, _ = _migrated(runner, plan_file, by_url)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][by_url]
    assert entry["status"] == "skipped" and entry["error"] is None
    assert entry["left_behind"] == [items[hosted]["refused_layers"]["1"]["reason"]]
    assert entry["shared"] == {}
    assert len(service.bodies(PREVIEW)) == previews


def test_the_report_says_why_a_borrower_waits_on_the_owner_of_its_layers(
    runner, tmp_path, geolens
):
    _service, _c, plan_file, hosted, by_url = _fresh(tmp_path, geolens, url_first=False)
    plan = json.loads(plan_file.read_text())
    assert not next(i for i in plan["items"] if i["id"] == by_url)["depends_on"]
    geolens.routes[layers.PROBE] = (503, layers._problem(503, "service unavailable"))

    result, payload = _migrated(runner, plan_file, hosted, by_url)

    assert result.exit_code != 0
    assert payload["waiting"] == [{"item": by_url, "waiting_on": [hosted]}]
    report = json.loads((plan_file.parent / "arcgis-migration-report.json").read_text())
    [text] = [
        f["text"]
        for f in report["follow_ups"]
        if f["item"] == by_url and f["kind"] == "unresolved_dependency"
    ]
    assert text.startswith(f"waits on {hosted} (failed: probe failed")
