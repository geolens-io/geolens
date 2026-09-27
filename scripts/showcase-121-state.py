#!/usr/bin/env python3
"""Save and restore the editable showcase state without replacing the database."""

import argparse
import importlib.util
import json
import os
from pathlib import Path

SEED = Path(__file__).with_name("seed-showcase.py")
spec = importlib.util.spec_from_file_location("seed_showcase", SEED)
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

MAP_NAMES = set(seed.MAP_DESCRIPTIONS) | {
    seed.HURRICANE_MAP,
    "Everything That Fell From the Sky",
}
COLLECTION_NAMES = set(seed.COLLECTIONS)
MAP_FIELDS = (
    "name",
    "description",
    "notes",
    "center_lng",
    "center_lat",
    "zoom",
    "bearing",
    "pitch",
    "basemap_style",
    "show_basemap_labels",
    "basemap_config",
    "terrain_config",
    "visibility",
    "plugins",
    "legend_title",
)
LAYER_FIELDS = (
    "sort_order",
    "visible",
    "opacity",
    "paint",
    "layout",
    "display_name",
    "filter",
    "label_config",
    "popup_config",
    "style_config",
    "layer_type",
    "show_in_legend",
)
DATASET_FIELDS = (
    "title",
    "summary",
    "visibility",
    "license",
    "attribution",
    "source_organization",
    "source_url",
    "data_vintage_start",
    "data_vintage_end",
    "update_frequency",
    "theme_category",
    "quality_statement",
    "owner_org",
    "usage_constraints",
    "access_constraints",
    "sensitivity_classification",
)


def get(api, path):
    response = api.client.get(f"{api.base}{path}", headers=api.h)
    response.raise_for_status()
    return response.json()


def request(api, method, path, body):
    response = api.client.request(method, f"{api.base}{path}", headers=api.h, json=body)
    response.raise_for_status()


def collection_members(api, collection_id):
    ids = []
    skip = 0
    while True:
        page = get(
            api,
            f"/api/catalog/collections/{collection_id}/datasets/?limit=200&skip={skip}",
        )
        ids.extend(item["id"] for item in page["datasets"])
        skip += len(page["datasets"])
        if skip >= page["total"]:
            return ids


def snapshot(api):
    maps = {}
    for item in api.list_all_maps():
        if (
            item["name"] not in MAP_NAMES
            or item.get("created_by_username") != api.username
        ):
            continue
        if item["name"] in maps:
            raise RuntimeError(f"ambiguous owned map: {item['name']}")
        detail = api.get_map(item["id"])
        maps[item["name"]] = {
            "id": detail["id"],
            "created_by": detail["created_by"],
            "fields": {field: detail.get(field) for field in MAP_FIELDS},
            "layers": {
                layer["id"]: {
                    "dataset_id": layer["dataset_id"],
                    "fields": {field: layer.get(field) for field in LAYER_FIELDS},
                }
                for layer in detail["layers"]
            },
        }
    datasets = {}
    for item in api.list_own_datasets():
        if item["title"] not in seed.SHOWCASE_METADATA:
            continue
        if item["title"] in datasets:
            raise RuntimeError(f"ambiguous owned dataset: {item['title']}")
        detail = api.get_dataset(item["id"])
        record_id = detail["record_id"]
        keywords = get(api, f"/api/records/{record_id}/keywords/")["keywords"]
        datasets[item["title"]] = {
            "id": detail["id"],
            "created_by": detail["created_by"],
            "record_id": record_id,
            "fields": {field: detail.get(field) for field in DATASET_FIELDS},
            "keywords": [
                {
                    field: keyword.get(field)
                    for field in ("id", "keyword", "keyword_type", "vocabulary_uri")
                }
                for keyword in keywords
                if not keyword.get("inherited")
            ],
        }
    collections = {}
    for item in api.list_collections():
        if item["name"] in COLLECTION_NAMES:
            collections[item["name"]] = {
                "id": item["id"],
                "description": item.get("description"),
                "dataset_ids": collection_members(api, item["id"]),
            }
    return {
        "version": 1,
        "base_url": api.base,
        "owner": api.username,
        "maps": maps,
        "datasets": datasets,
        "collections": collections,
    }


def write_private(path, state):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(state, stream, indent=2, sort_keys=True)
        stream.write("\n")


def verify_restorable(api, saved, current):
    if saved["base_url"] != api.base or saved["owner"] != api.username:
        raise RuntimeError("snapshot target or owner differs from this session")
    for name, original in saved["maps"].items():
        now = current["maps"].get(name)
        if not now or (now["id"], now["created_by"]) != (
            original["id"],
            original["created_by"],
        ):
            raise RuntimeError(f"map identity changed: {name}")
        for layer_id, layer in original["layers"].items():
            present = now["layers"].get(layer_id)
            if not present or present["dataset_id"] != layer["dataset_id"]:
                raise RuntimeError(f"map layer identity changed: {name} / {layer_id}")
        extra = set(now["layers"]) - set(original["layers"])
        if any(
            now["layers"][layer_id]["fields"]["display_name"]
            != "Atlantic basin regions (context)"
            for layer_id in extra
        ):
            raise RuntimeError(f"unexpected new layer on {name}")
    for title, original in saved["datasets"].items():
        now = current["datasets"].get(title)
        if not now or (now["id"], now["created_by"]) != (
            original["id"],
            original["created_by"],
        ):
            raise RuntimeError(f"dataset identity changed: {title}")
    for name, original in saved["collections"].items():
        now = current["collections"].get(name)
        if not now or now["id"] != original["id"]:
            raise RuntimeError(f"collection identity changed: {name}")


def restore_maps(api, saved, current):
    for name, original in saved["maps"].items():
        now = current["maps"][name]
        delta = {
            key: value
            for key, value in original["fields"].items()
            if now["fields"][key] != value
        }
        if delta:
            request(api, "PUT", f"/api/maps/{original['id']}", delta)
        updated = [
            {"id": layer_id, **layer["fields"]}
            for layer_id, layer in original["layers"].items()
            if now["layers"][layer_id]["fields"] != layer["fields"]
        ]
        removed = list(set(now["layers"]) - set(original["layers"]))
        if updated or removed:
            request(
                api,
                "PATCH",
                f"/api/maps/{original['id']}/layers",
                {"updated": updated, "removed": removed},
            )
        print(f"restored map {name}")


def restore_datasets(api, saved, current):
    for title, original in saved["datasets"].items():
        now = current["datasets"][title]
        delta = {
            key: value
            for key, value in original["fields"].items()
            if now["fields"][key] != value
        }
        if delta:
            api.patch_dataset(original["id"], **delta)
        before = {
            (k["keyword"], k["keyword_type"], k["vocabulary_uri"])
            for k in original["keywords"]
        }
        after = {
            (k["keyword"], k["keyword_type"], k["vocabulary_uri"]): k
            for k in now["keywords"]
        }
        for key, keyword in after.items():
            if key not in before:
                request(
                    api,
                    "DELETE",
                    f"/api/records/{original['record_id']}/keywords/{keyword['id']}/",
                    None,
                )
        for keyword in original["keywords"]:
            key = (
                keyword["keyword"],
                keyword["keyword_type"],
                keyword["vocabulary_uri"],
            )
            if key not in after:
                request(
                    api,
                    "POST",
                    f"/api/records/{original['record_id']}/keywords/",
                    {
                        field: keyword[field]
                        for field in ("keyword", "keyword_type", "vocabulary_uri")
                    },
                )


def restore_collections(api, saved, current):
    for name, original in saved["collections"].items():
        now = current["collections"][name]
        if now["description"] != original["description"]:
            api.update_collection(original["id"], description=original["description"])
        for did in set(now["dataset_ids"]) - set(original["dataset_ids"]):
            request(
                api,
                "DELETE",
                f"/api/catalog/collections/{original['id']}/datasets/{did}",
                None,
            )
        missing = list(set(original["dataset_ids"]) - set(now["dataset_ids"]))
        if missing:
            request(
                api,
                "POST",
                f"/api/catalog/collections/{original['id']}/datasets/",
                {"dataset_ids": missing},
            )


def hide_new_content(api, saved, current):
    for name, item in current["maps"].items():
        if name not in saved["maps"]:
            request(api, "PUT", f"/api/maps/{item['id']}", {"visibility": "private"})
            print(f"unpublished new map {name}")
    for title, item in current["datasets"].items():
        if title not in saved["datasets"]:
            api.patch_dataset(item["id"], visibility="private")
            print(f"unpublished new dataset {title}")
    for name, item in current["collections"].items():
        if name not in saved["collections"]:
            new_ids = {
                dataset["id"]
                for title, dataset in current["datasets"].items()
                if title not in saved["datasets"]
            }
            if name != "Client Connections" or not set(item["dataset_ids"]) <= new_ids:
                raise RuntimeError(f"new collection has unexpected members: {name}")
            api.delete_collection(item["id"])
            print(f"removed new collection {name}")


def restore(api, saved):
    current = snapshot(api)
    verify_restorable(api, saved, current)
    restore_maps(api, saved, current)
    restore_datasets(api, saved, current)
    restore_collections(api, saved, current)
    hide_new_content(api, saved, current)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "restore"))
    parser.add_argument("path", help="protected JSON snapshot path")
    parser.add_argument(
        "--base-url", default=os.environ.get("GEOLENS_BASE_URL", seed.DEFAULT_BASE_URL)
    )
    parser.add_argument(
        "--username", default=os.environ.get("GEOLENS_ADMIN_USERNAME", "admin")
    )
    parser.add_argument("--password", default=os.environ.get("GEOLENS_ADMIN_PASSWORD"))
    args = parser.parse_args()
    if not args.password:
        parser.error("GEOLENS_ADMIN_PASSWORD is required")
    api = seed.Api.login(args.base_url, args.username, args.password)
    if args.action == "snapshot":
        write_private(args.path, snapshot(api))
        print(f"wrote protected state to {args.path}")
    else:
        with open(args.path, encoding="utf-8") as stream:
            restore(api, json.load(stream))


if __name__ == "__main__":
    main()
