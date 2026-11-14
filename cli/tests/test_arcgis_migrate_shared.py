"""`geolens arcgis migrate`: two plan items over one service share one dataset,
which only the item owning the service writes."""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from geolens_cli import arcgis_migrate_shared as shared_mod

from . import test_arcgis_migrate_layers as layers
from .arcgis_fake import A1, A2
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
PARCELS, OWNERS = dataset_id("Parcels"), dataset_id("Owners")
TOKEN = secrets.token_urlsafe(16)
PREVIEW = "POST /services/preview/"


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
        layer = re.search(r"/FeatureServer/(\d+)$", seen.json()["url"])
        return {**found, "selected_layer_id": int(layer.group(1)) if layer else None}

    def commit(self, seen, name: str):
        answer = super().commit(seen, name)
        self.duplicates.setdefault(name, dataset_id(name))
        return answer


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


def _run(runner, plan_file: Path, *items: str):
    only = [arg for item in items for arg in ("--only", item)]
    result, _ = _migrate(runner, plan_file, *only, "--token", TOKEN)
    assert result.exit_code == 0, result.output
    return _state(plan_file)["items"]


def _dataset(service: FakeImport, collections: FakeCollections, dataset: str) -> dict:
    fields = service.dataset(dataset, layers.OPERATOR)
    origin = next(
        b["item_id"]
        for b in service.bodies(PREVIEW)
        if dataset_id(b["layer_name"]) == dataset
    )
    return {
        "title": fields["title"],
        "visibility": fields["visibility"],
        "summary": fields["summary"],
        "keywords": service.keywords.get(dataset, []),
        "collections": sorted(
            name for name, ids in collections.membership().items() if dataset in ids
        ),
        "origin": origin,
    }


def _writes(geolens, item_requests) -> list[tuple[str, str]]:
    return [
        (s.method, s.url.split("/api", 1)[1])
        for s in item_requests
        if s.method != "GET" and "/services/" not in s.url
    ]


def _fresh(runner, tmp_path, geolens, **kwargs):
    geolens.seen.clear()
    service = OneCopy(geolens, [_layer(0, "Parcels"), _layer(1, "Owners", "Table")])
    collections = FakeCollections(geolens)
    plan_file, hosted_item, url_item = _plan(tmp_path, **kwargs)
    return service, collections, plan_file, hosted_item, url_item


@pytest.mark.parametrize("url_first", [True, False])
def test_the_hosted_item_owns_the_shared_dataset_in_either_plan_order(
    runner, tmp_path, geolens, url_first
):
    service, collections, plan_file, hosted, by_url = _fresh(
        runner, tmp_path, geolens, url_first=url_first
    )

    items = _run(runner, plan_file, A1, A2)

    assert _dataset(service, collections, PARCELS) == {
        "title": "Hosted parcels - Parcels",
        "visibility": "internal",
        "summary": "From the hosted item",
        "keywords": ["hosted"],
        "collections": ["Hosted parcels folder"],
        "origin": hosted,
    }
    assert items[hosted]["status"] == "done"
    assert items[hosted]["dataset_ids"] == [PARCELS, OWNERS]
    assert not any("edited in GeoLens" in n for n in items[hosted]["notes"])
    entry = items[by_url]
    assert entry["status"] == "exists"
    assert entry["dataset_ids"] == [] and entry["layer_datasets"] == {}
    assert entry["shared"] == {"0": PARCELS, "1": OWNERS}
    assert entry["attachments"] == {} and entry["relationships"] == {}
    assert entry["visibility"] == {} and entry["metadata_baseline"] == {}
    reuse = f"reuses dataset {PARCELS} of item {hosted} (Hosted parcels)"
    assert entry["notes"][0].startswith(reuse)
    assert any(
        n.startswith(f"shared public in ArcGIS, more widely than item {hosted}")
        for n in entry["notes"]
    )


def test_both_plan_orders_send_the_same_writes(runner, tmp_path, geolens):
    logs = []
    for url_first in (True, False):
        _fresh(runner, tmp_path / str(url_first), geolens, url_first=url_first)
        _run(runner, tmp_path / str(url_first) / "arcgis-migration-plan.json", A1, A2)
        logs.append(_writes(geolens, geolens.seen))

    assert logs[0] == logs[1]


def test_the_url_item_sends_no_write_at_all(runner, tmp_path, geolens):
    _service, _collections, plan_file, hosted, by_url = _fresh(
        runner, tmp_path, geolens, url_first=False
    )
    _run(runner, plan_file, hosted)
    geolens.seen.clear()

    items = _run(runner, plan_file, by_url)

    assert items[by_url]["status"] == "exists"
    assert _writes(geolens, geolens.seen) == []
    # Only the preview, which GeoLens refuses as a duplicate.
    assert [s.method for s in geolens.seen if "/services/" in s.url] == [
        "POST",
        "POST",
        "POST",
    ]


def test_a_url_item_over_one_layer_reuses_only_that_layer(runner, tmp_path, geolens):
    service, collections, plan_file, hosted, by_url = _fresh(
        runner, tmp_path, geolens, url_first=True, url_suffix="/1"
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
        runner, tmp_path, geolens, url_first=True, hosted=False
    )

    items = _run(runner, plan_file, A1, A2)

    assert by_url == A1
    assert _dataset(service, collections, PARCELS)["summary"] == "From the URL item"
    assert items[A2]["status"] == "exists"
    assert items[A2]["shared"] == {"0": PARCELS, "1": OWNERS}


def test_a_rerun_leaves_the_shared_dataset_to_its_owner(runner, tmp_path, geolens):
    service, collections, plan_file, hosted, by_url = _fresh(
        runner, tmp_path, geolens, url_first=True, hosted_access="public"
    )
    _run(runner, plan_file, A1, A2)
    before = _dataset(service, collections, PARCELS)
    notes = _state(plan_file)["items"][by_url]["notes"]
    FakeRefresh(geolens, service).allow(PARCELS, OWNERS)
    start = len(geolens.seen)

    items = _run(runner, plan_file, A1, A2)

    assert _dataset(service, collections, PARCELS) == before
    assert items[by_url]["notes"] == notes
    assert items[by_url]["shared"] == {"0": PARCELS, "1": OWNERS}
    assert items[by_url]["stale"] == [] and items[hosted]["stale"] == []
    sent = [s.body for s in geolens.seen[start:] if s.method != "GET"]
    assert sent and not any(b"From the URL item" in body for body in sent)
    owner_notes = items[hosted]["notes"]

    again = _run(runner, plan_file, A1, A2)

    assert again[by_url]["notes"] == notes and again[hosted]["notes"] == owner_notes
    assert again[by_url]["stale"] == [] and again[hosted]["stale"] == []


@pytest.mark.parametrize("url_first", [True, False])
def test_a_state_from_before_ownership_converges_on_a_rerun(
    runner, tmp_path, geolens, monkeypatch, url_first
):
    service, collections, plan_file, hosted, by_url = _fresh(
        runner, tmp_path, geolens, url_first=url_first, hosted_access="public"
    )
    FakeRefresh(geolens, service).allow(PARCELS, OWNERS)
    # No owner decided: each item writes the dataset as it runs, in plan order,
    # and a rerun refuses the item that ran first.
    with monkeypatch.context() as m:
        m.setattr(layers.migrate, "service_owners", lambda items, rows: {})
        _run(runner, plan_file, A1, A2)
        _migrate(runner, plan_file, "--only", A1, "--only", A2, "--token", TOKEN)
    old = _state(plan_file)["items"]
    first, second = (by_url, hosted) if url_first else (hosted, by_url)
    assert PARCELS in old[by_url]["layer_datasets"].values()
    assert any("changed in GeoLens" in s for s in old[first]["stale"])
    # The second item's false note, which a rerun doesn't add again.
    edited = [n for n in old[second]["notes"] if "edited in GeoLens" in n]
    assert edited and len(edited) == len(set(edited))

    items = _run(runner, plan_file, A1, A2)

    dataset = _dataset(service, collections, PARCELS)
    assert dataset["title"] == "Hosted parcels - Parcels"
    assert dataset["visibility"] == "public"
    assert dataset["summary"] == "From the hosted item"
    assert items[by_url]["status"] == "exists"
    assert items[by_url]["layer_datasets"] == {}
    assert items[by_url]["shared"] == {"0": PARCELS, "1": OWNERS}
    assert items[hosted]["status"] == "done"
    assert items[hosted]["reused"] == []
    assert items[hosted]["stale"] == [] and items[by_url]["stale"] == []
    assert not any("edited in GeoLens" in n for n in items[hosted]["notes"])
    assert not any("edited in GeoLens" in n for n in items[by_url]["notes"])

    again = _run(runner, plan_file, A1, A2)

    assert again[hosted]["stale"] == [] and again[by_url]["stale"] == []
    assert again[hosted]["notes"] == items[hosted]["notes"]
    assert again[by_url]["notes"] == items[by_url]["notes"]
    assert _dataset(service, collections, PARCELS) == dataset


def test_an_owner_that_runs_after_an_earlier_import_takes_the_dataset_over(
    runner, tmp_path, geolens
):
    service, collections, plan_file, hosted, by_url = _fresh(
        runner, tmp_path, geolens, url_first=True
    )
    plan = json.loads(plan_file.read_text())
    hosted_item = next(i for i in plan["items"] if i["id"] == hosted)
    hosted_item["removed"] = True
    plan_file.write_text(json.dumps(plan))
    _run(runner, plan_file, by_url)
    del hosted_item["removed"]
    plan_file.write_text(json.dumps(plan))
    FakeRefresh(geolens, service).allow(PARCELS, OWNERS)

    items = _run(runner, plan_file, A1, A2)

    dataset = _dataset(service, collections, PARCELS)
    assert dataset["title"] == "Hosted parcels - Parcels"
    assert dataset["visibility"] == "internal"
    assert dataset["summary"] == "From the hosted item"
    assert items[hosted]["status"] == "done" and items[hosted]["reused"] == []
    assert items[by_url]["shared"] == {"0": PARCELS, "1": OWNERS}
    assert not any("edited in GeoLens" in n for n in items[hosted]["notes"])


def test_service_owners_prefers_the_hosted_item_at_the_service_root():
    def item(item_id):
        return {"id": item_id, "action": "import_layers", "depends_on": []}

    rows = {
        "u": {"url": SERVICE.upper() + "/", "hosted": False},
        "l": {"url": SERVICE + "/3", "hosted": True},
        "h": {"url": SERVICE, "hosted": True},
        "x": {"url": SERVICE.replace("Parcels", "Roads"), "hosted": True},
    }

    owners = shared_mod.service_owners([item(i) for i in "ulhx"], rows)

    assert {i: r.owner["id"] for i, r in owners.items()} == {"u": "h", "l": "h"}
