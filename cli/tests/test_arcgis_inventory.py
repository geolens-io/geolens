"""`geolens arcgis inventory`: listing, classification, dependencies, report."""

from __future__ import annotations

import email.utils
import http.client
import http.server
import json
import shutil
import ssl
import stat
import subprocess
import threading
import time
import tracemalloc
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from geolens_cli import arcgis_inventory as inventory
from geolens_cli import arcgis_report
from geolens_cli.main import app

from .arcgis_fake import (
    A1,
    A2,
    A3,
    A4,
    A5,
    B1,
    B2,
    C1,
    C2,
    C3,
    D1,
    D2,
    D3,
    D4,
    D5,
    EMPTY_GROUPS,
    FOLDER,
    HYDRANTS,
    PORTAL,
    USER,
    FakePortal,
    item_data_path,
    load,
    portal_routes,
)

TOKEN = "fixture-token-for-offline-tests"


class FakeClock:
    """Monotonic clock that only moves when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def run(runner, monkeypatch):
    """Invoke the command against a FakePortal; returns (result, sleeps)."""
    for name in ("ARCGIS_TOKEN", "ARCGIS_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    def invoke(
        portal: FakePortal,
        *args: str,
        json_mode: bool = True,
        token: str | None = TOKEN,
        stdin: str | None = None,
        env: dict[str, str] | None = None,
    ):
        clock = FakeClock()
        monkeypatch.setattr(inventory, "build_opener", lambda: portal)
        monkeypatch.setattr(inventory, "_sleep", clock.sleep)
        monkeypatch.setattr(inventory, "_clock", clock)
        argv = ["--json"] if json_mode else []
        argv += ["arcgis", "inventory", "--portal-url", PORTAL, *args]
        if token is not None:
            argv += ["--token", token]
        result = runner.invoke(app, argv, input=stdin, env=env)
        return result, clock.sleeps

    return invoke


def _report(result) -> dict[str, Any]:
    return json.loads(result.stdout)


def _rows(report: dict) -> dict[str, dict]:
    return {row["id"]: row for row in report["items"]}


@pytest.mark.parametrize(
    ("item_type", "keywords", "klass", "reason", "retirement", "hosted"),
    [
        (
            "Feature Service",
            ["Hosted Service"],
            "supported",
            "hosted_feature_layer",
            None,
            True,
        ),
        (
            "Feature Service",
            ["Hosted Service", "View Service"],
            "supported",
            "hosted_feature_view",
            None,
            True,
        ),
        (
            "Feature Service",
            ["ArcGIS Server"],
            "supported",
            "non_hosted_service_reachability_external",
            None,
            False,
        ),
        (
            "Map Service",
            ["Hosted Service", "Tiled"],
            "partial",
            "hosted_tile_layer_cached_only",
            None,
            True,
        ),
        ("Map Service", [], "supported", "map_service_layer_import", None, False),
        ("Web Map", [], "partial", "web_map_styling_needs_translation", None, None),
        (
            "Image Service",
            ["Hosted Service"],
            "unsupported",
            "no_import_path",
            None,
            True,
        ),
        ("Vector Tile Service", [], "unsupported", "no_import_path", None, False),
        ("Scene Service", [], "unsupported", "no_scene_import", None, False),
        ("Web Scene", [], "unsupported", "no_scene_import", None, None),
        ("WMS", [], "partial", "ogc_service_reference", None, None),
        ("OGCFeatureServer", [], "partial", "ogc_service_reference", None, None),
        ("CSV", [], "partial", "data_file_import_candidate", None, None),
        ("File Geodatabase", [], "partial", "data_file_import_candidate", None, None),
        (
            "Web Mapping Application",
            ["Web AppBuilder", "WAB2D"],
            "unsupported",
            "web_appbuilder_app",
            "web_appbuilder",
            None,
        ),
        (
            "Web Mapping Application",
            ["Story Map", "MapJournal"],
            "unsupported",
            "classic_story_map",
            "classic_story_maps",
            None,
        ),
        (
            "Web Mapping Application",
            ["Instant App"],
            "unsupported",
            "no_equivalent_app",
            None,
            None,
        ),
        ("Dashboard", [], "unsupported", "no_equivalent_app", None, None),
        ("StoryMap", [], "unsupported", "no_equivalent_app", None, None),
        ("Geoprocessing Service", [], "unsupported", "not_catalog_data", None, None),
        ("Quantum Widget", [], "unsupported", "unknown_type", None, None),
    ],
)
def test_classify_table(item_type, keywords, klass, reason, retirement, hosted):
    """Each item type and keyword variant lands in its class with its flags."""
    verdict = inventory.classify({"type": item_type, "typeKeywords": keywords})
    assert verdict == {
        "class": klass,
        "reason": reason,
        "retirement": retirement,
        "hosted": hosted,
    }


def test_retirement_dates_cite_a_source():
    """A dated retirement always carries the Esri page it came from."""
    for entry in inventory.RETIREMENTS.values():
        if entry["date"] is not None:
            assert entry["source_url"].startswith("https://")


def test_org_scope_follows_pagination_to_the_last_page(run):
    """Org scope pages through search until nextStart is -1."""
    portal = FakePortal(portal_routes())
    result, _ = run(portal, "--scope", "org")
    assert result.exit_code == 0, result.output
    report = _report(result)
    assert set(_rows(report)) == {
        A1,
        A2,
        A3,
        A4,
        A5,
        B1,
        B2,
        C1,
        C2,
        C3,
        D1,
        D2,
        D3,
        D4,
        D5,
    }
    starts = [s.params["start"] for s in portal.requests_to("search")]
    assert starts == ["1", "9"]
    assert portal.requests_to("search")[0].params["q"] == "orgid:ExAmPlEoRg0123"
    assert report["counts"]["total"] == 15
    assert report["counts"]["by_class"] == {
        "supported": 4,
        "partial": 5,
        "unsupported": 6,
    }
    assert report["complete"] is True and report["truncated"] is False


def test_user_scope_is_the_default_and_reads_every_folder(run):
    """Without --scope the signed-in user's root folder and subfolders are listed."""
    portal = FakePortal(portal_routes())
    result, _ = run(portal)
    assert result.exit_code == 0, result.output
    report = _report(result)
    assert set(_rows(report)) == {A1, B1, C1}
    assert portal.requests_to("search") == []
    assert portal.requests_to(f"content/users/{USER}/{FOLDER}")
    assert report["scope"] == {"mode": "user", "owner": USER, "org_id": None}


def test_item_rows_record_size_sharing_owner_and_dates(run):
    """Sizes of -1 or missing become null, timestamps become ISO 8601."""
    result, _ = run(FakePortal(portal_routes()), "--scope", "org")
    rows = _rows(_report(result))
    assert rows[A1]["size_bytes"] == 1048576
    assert rows[A3]["size_bytes"] is None
    assert rows[D4]["size_bytes"] is None
    assert rows[A2]["sharing"] == {"access": "public", "groups": []}
    assert rows[A1]["owner"] == USER
    assert rows[A1]["created"] == "2026-01-01T00:00:00Z"
    assert rows[A1]["modified"] == "2026-01-02T00:00:00Z"


def _read_errors(report: dict) -> list[dict]:
    """Errors from the metadata reads; the fixture's broken web map is not one."""
    return [e for e in report["errors"] if e["phase"] != "item_data"]


def _rich_routes(**overrides: Any) -> dict[str, Any]:
    return portal_routes(
        {f"content/items/{A1}": load("item_detail_rich.json"), **overrides}
    )


def test_item_metadata_is_recorded_and_validates_against_v2(run):
    result, _ = run(FakePortal(_rich_routes()), "--scope", "org")
    report = _report(result)
    Draft202012Validator(
        arcgis_report.inventory_schema(), format_checker=FormatChecker()
    ).validate(report)
    row = _rows(report)[A1]
    assert report["schema_version"] == "2"
    assert row["snippet"] == "Tax parcels, updated nightly."
    assert row["description"] == "<p>County parcel boundaries.</p>"
    assert row["tags"] == ["parcels", "cadastre"]
    assert row["access_information"] == "Example County Assessor"
    assert row["license_info"] == "<p>Public domain.</p>"
    assert row["extent"] == [[-75.2, 40.5], [-74.1, 41.3]]
    assert row["thumbnail"] == "thumbnail/thumbnail.png"
    assert row["spatial_reference"] == "102711"
    assert row["culture"] == "en-us"
    assert row["layers"] == [
        {
            "id": 0,
            "url": "https://services1.arcgis.com/ExAmPlEoRg0123/arcgis/rest/services/Parcels/FeatureServer/0",
        }
    ]
    assert row["data_saved"] is False
    # v1 readers keep their fields.
    assert (row["id"], row["type"], row["title"], row["class"]) == (
        A1,
        "Feature Service",
        "Parcels",
        "supported",
    )


def test_org_scope_resolves_folder_titles_from_the_owners_folder_list(run):
    portal = FakePortal(_rich_routes())
    result, _ = run(portal, "--scope", "org")
    rows = _rows(_report(result))
    assert rows[A1]["folder"] == {"id": FOLDER, "title": "Apps"}
    assert rows[A2]["folder"] is None
    listings = portal.requests_to(f"content/users/{USER}")
    assert [s.params["num"] for s in listings] == ["1"]


def test_forbidden_folder_list_leaves_the_title_null_and_the_run_clean(run):
    portal = FakePortal(
        _rich_routes(**{f"content/users/{USER}": (403, {"error": {"code": 403}})})
    )
    result, _ = run(portal, "--scope", "org", "--strict")
    report = _report(result)
    assert _rows(report)[A1]["folder"] == {"id": FOLDER, "title": None}
    assert _read_errors(report) == []


def test_user_scope_folder_titles_come_from_the_listing(run):
    portal = FakePortal(portal_routes())
    result, _ = run(portal, "--scope", "user")
    rows = _rows(_report(result))
    assert rows[C1]["folder"] == {"id": FOLDER, "title": "Apps"}
    assert rows[A1]["folder"] is None
    assert len(portal.requests_to(f"content/users/{USER}")) == 1


def test_owner_profile_is_read_once_per_distinct_owner(run):
    portal = FakePortal(portal_routes())
    result, _ = run(portal, "--scope", "org")
    rows = _rows(_report(result))
    assert len(portal.requests_to(f"community/users/{USER}")) == 1
    assert rows[A1]["owner_full_name"] == "Gina Admin"
    assert rows[D5]["owner_email"] == "gina.admin@example.org"


@pytest.mark.parametrize("status", [400, 403])
def test_hidden_owner_profile_leaves_name_and_email_null(run, status):
    portal = FakePortal(
        portal_routes(
            {f"community/users/{USER}": (status, {"error": {"code": status}})}
        )
    )
    result, _ = run(portal, "--scope", "org")
    report = _report(result)
    assert _read_errors(report) == []
    assert {r["owner_full_name"] for r in report["items"]} == {None}
    assert {r["owner_email"] for r in report["items"]} == {None}


def test_groups_list_admin_member_and_other_groups(run):
    groups = {
        "admin": [{"id": "g1", "title": "GIS team", "access": "org"}],
        "member": [{"id": "g2", "title": "Planning", "access": "private"}],
        "other": [{"id": "g3", "title": "Public maps", "access": "public"}],
    }
    portal = FakePortal(portal_routes({f"content/items/{A1}/groups": groups}))
    result, _ = run(portal, "--scope", "org")
    row = _rows(_report(result))[A1]
    assert row["groups"] == [
        {"id": "g1", "title": "GIS team", "access": "org"},
        {"id": "g2", "title": "Planning", "access": "private"},
        {"id": "g3", "title": "Public maps", "access": "public"},
    ]
    assert row["sharing"]["groups"] == ["g1", "g2", "g3"]
    assert _rows(_report(result))[A2]["groups"] == []


def test_forbidden_group_read_is_an_error_row_and_the_run_continues(run):
    portal = FakePortal(
        portal_routes({f"content/items/{A1}/groups": (403, {"error": {"code": 403}})})
    )
    result, _ = run(portal, "--scope", "org")
    report = _report(result)
    rows = _rows(report)
    assert result.exit_code == 0
    assert rows[A1]["groups"] is None
    assert rows[A1]["sharing"]["groups"] is None
    assert rows[A2]["groups"] == []
    assert [
        (e["item_id"], e["phase"], e["http_status"]) for e in _read_errors(report)
    ] == [(A1, "item_groups", 403)]


def test_no_groups_makes_no_group_requests(run):
    portal = FakePortal(portal_routes())
    result, _ = run(portal, "--scope", "org", "--no-groups")
    report = _report(result)
    assert [s for s in portal.seen if s.path.endswith("/groups")] == []
    assert {r["groups"] for r in report["items"]} == {None}
    assert _read_errors(report) == []


def test_failed_item_read_keeps_the_search_result_fields(run):
    listing = load("search_page1.json")["results"][0] | {"snippet": "From the search."}
    portal = FakePortal(
        portal_routes(
            {
                "search": {
                    "total": 1,
                    "start": 1,
                    "num": 100,
                    "nextStart": -1,
                    "results": [listing],
                },
                f"content/items/{A1}": (500, {"error": {"code": 500}}),
            }
        )
    )
    result, _ = run(portal, "--scope", "org")
    report = _report(result)
    assert _rows(report)[A1]["snippet"] == "From the search."
    assert [(e["item_id"], e["phase"]) for e in _read_errors(report)] == [
        (A1, "item_details")
    ]


def test_token_rejected_while_reading_an_item_stops_the_run(run):
    portal = FakePortal(portal_routes({f"content/items/{A2}": load("error_498.json")}))
    result, _ = run(portal, "--scope", "org")
    assert result.exit_code == 3
    report = _report(result)
    assert report["complete"] is False
    assert _rows(report)[B1]["dependencies_status"] == "not_fetched"


def test_secrets_in_item_text_are_redacted_and_the_description_is_capped(run):
    detail = load("item_detail_rich.json") | {
        "spatialReference": {"wkt": "PROJCS[token=abc123SECRET]"},
        "description": "<a href='https://x/y?token=abc123SECRET'>link</a>"
        + "é" * inventory.MAX_DESCRIPTION_BYTES,
        "snippet": "password=hunter2 in the snippet",
    }
    result, _ = run(
        FakePortal(portal_routes({f"content/items/{A1}": detail})), "--scope", "org"
    )
    row = _rows(_report(result))[A1]
    assert "abc123SECRET" not in row["description"]
    assert "token=[REDACTED]" in row["description"]
    assert row["spatial_reference"] == "PROJCS[token=[REDACTED]"
    assert len(row["description"].encode()) <= inventory.MAX_DESCRIPTION_BYTES
    assert row["snippet"] == "password=[REDACTED] in the snippet"


def test_detail_url_replaces_a_thin_search_url_and_tolerates_a_trailing_slash(run):
    listing = load("search_page1.json")["results"][0] | {"url": None}
    detail = load("item_detail_rich.json")
    detail["url"] += "/"
    routes = portal_routes(
        {
            "search": {
                "total": 1,
                "start": 1,
                "num": 100,
                "nextStart": -1,
                "results": [listing],
            },
            f"content/items/{A1}": detail,
        }
    )
    result, _ = run(FakePortal(routes), "--scope", "org")
    row = _rows(_report(result))[A1]
    assert row["url"].endswith("/FeatureServer/0/")
    assert [layer["id"] for layer in row["layers"]] == [0]


def test_detail_without_a_url_clears_the_search_url(run):
    listing = load("search_page1.json")["results"][0]
    detail = {k: v for k, v in load("item_detail_rich.json").items() if k != "url"}
    routes = portal_routes(
        {
            "search": {
                "total": 1,
                "start": 1,
                "num": 100,
                "nextStart": -1,
                "results": [listing],
            },
            f"content/items/{A1}": detail,
        }
    )
    result, _ = run(FakePortal(routes), "--scope", "org")
    row = _rows(_report(result))[A1]
    assert (row["url"], row["layers"]) == (None, [])


def test_detail_type_keywords_reclassify_a_thin_search_row(run):
    listing = load("search_page1.json")["results"][0] | {"typeKeywords": []}
    routes = portal_routes(
        {
            "search": {
                "total": 1,
                "start": 1,
                "num": 100,
                "nextStart": -1,
                "results": [listing],
            },
            f"content/items/{A1}": load("item_detail_rich.json"),
        }
    )
    result, _ = run(FakePortal(routes), "--scope", "org")
    row = _rows(_report(result))[A1]
    assert (row["reason"], row["hosted"]) == ("hosted_feature_layer", True)
    assert "Hosted Service" in row["type_keywords"]


def test_search_folder_survives_a_failed_detail_read(run):
    listing = load("search_page1.json")["results"][0] | {"ownerFolder": FOLDER}
    routes = portal_routes(
        {
            "search": {
                "total": 1,
                "start": 1,
                "num": 100,
                "nextStart": -1,
                "results": [listing],
            },
            f"content/items/{A1}": (500, {"error": {"code": 500}}),
        }
    )
    result, _ = run(FakePortal(routes), "--scope", "org")
    assert _rows(_report(result))[A1]["folder"] == {"id": FOLDER, "title": "Apps"}


def test_detail_folder_replaces_a_stale_search_folder(run):
    listing = load("search_page1.json")["results"][0] | {"ownerFolder": "stale"}
    detail = {
        k: v for k, v in load("item_detail_rich.json").items() if k != "ownerFolder"
    }
    routes = portal_routes(
        {
            "search": {
                "total": 1,
                "start": 1,
                "num": 100,
                "nextStart": -1,
                "results": [listing],
            },
            f"content/items/{A1}": detail,
        }
    )
    result, _ = run(FakePortal(routes), "--scope", "org")
    assert _rows(_report(result))[A1]["folder"] is None


def test_detail_type_keywords_are_redacted(run):
    detail = load("item_detail_rich.json") | {
        "typeKeywords": ["Data", "token=abc123SECRET"]
    }
    result, _ = run(
        FakePortal(portal_routes({f"content/items/{A1}": detail})), "--scope", "org"
    )
    assert "abc123SECRET" not in result.stdout


def test_counts_failed_items_not_failed_reads(run):
    portal = FakePortal(
        portal_routes(
            {
                f"content/items/{A1}": (500, {"error": {"code": 500}}),
                f"content/items/{A1}/groups": (403, {"error": {"code": 403}}),
            }
        )
    )
    result, _ = run(portal, "--scope", "org")
    report = _report(result)
    assert len(_read_errors(report)) == 2
    assert report["counts"]["failed"] == len({e["item_id"] for e in report["errors"]})


def test_token_rejected_while_reading_an_owner_stops_the_remaining_owner_reads(run):
    listed = [
        load("search_page1.json")["results"][0] | {"owner": name}
        for name in ("zed", "amy", "bob")
    ]
    for n, row in enumerate(listed):
        row["id"] = f"{n:032x}"
    routes = portal_routes(
        {
            "search": {
                "total": 3,
                "start": 1,
                "num": 100,
                "nextStart": -1,
                "results": listed,
            },
            "community/users/amy": load("error_498.json"),
        }
    )
    for row in listed:
        routes[f"content/items/{row['id']}"] = row
        routes[f"content/items/{row['id']}/groups"] = EMPTY_GROUPS
    portal = FakePortal(routes)
    result, _ = run(portal, "--scope", "org")
    assert result.exit_code == 3
    assert portal.requests_to("community/users/bob") == []
    assert portal.requests_to("community/users/zed") == []


def test_group_and_folder_titles_are_redacted(run):
    leak = "https://x/y?token=abc123SECRET"
    portal = FakePortal(
        _rich_routes(
            **{
                f"content/items/{A1}/groups": {
                    "admin": [{"id": "g1", "title": leak, "access": "org"}]
                },
                f"content/users/{USER}": {
                    "folders": [{"id": FOLDER, "title": leak}],
                    "items": [],
                },
            }
        )
    )
    result, _ = run(portal, "--scope", "org")
    assert "abc123SECRET" not in result.stdout
    row = _rows(_report(result))[A1]
    assert row["groups"][0]["title"].endswith("token=[REDACTED]")
    assert row["folder"]["title"].endswith("token=[REDACTED]")


def test_exhausted_rate_limit_on_an_owner_read_is_an_error_row(run):
    portal = FakePortal(
        portal_routes({f"community/users/{USER}": (429, {"error": {"code": 429}})})
    )
    result, _ = run(portal, "--scope", "org", "--strict")
    assert result.exit_code == 1
    errors = [e for e in _report(result)["errors"] if e["phase"] == "owner"]
    assert [(e["item_id"], e["http_status"]) for e in errors] == [(USER, 429)]


def test_secret_in_a_detail_url_is_redacted(run):
    detail = load("item_detail_rich.json") | {
        "url": f"https://services1.arcgis.com/{TOKEN}/FeatureServer/0"
    }
    result, _ = run(
        FakePortal(portal_routes({f"content/items/{A1}": detail})), "--scope", "org"
    )
    row = _rows(_report(result))[A1]
    assert TOKEN not in result.stdout
    assert "[REDACTED]" in row["url"]


def test_anonymous_run_does_not_read_groups(run):
    portal = FakePortal(portal_routes())
    result, _ = run(portal, "--scope", "org", token=None)
    assert [s for s in portal.seen if s.path.endswith("/groups")] == []
    assert {r["groups"] for r in _report(result)["items"]} == {None}


def test_markdown_lists_folders_and_owners(run):
    result, _ = run(FakePortal(_rich_routes()), "--scope", "org", json_mode=False)
    assert "## Folders" in result.stdout
    assert "| Apps |" in result.stdout
    assert "## Owners" in result.stdout
    assert "gina.admin@example.org" in result.stdout


def test_web_map_and_app_dependencies(run):
    """Web map layers (nested, external, unlisted) and app-to-map links are recorded."""
    result, _ = run(FakePortal(portal_routes()), "--scope", "org")
    report = _report(result)
    deps = [d for d in report["dependencies"] if d["from_id"] == B1]
    summary = [
        (d["order"], d["role"], d["to_id"], d["layer_id"], d["hosted"], d["resolved"])
        for d in deps
    ]
    assert summary == [
        (0, "operational_layer", A1, "parcels_0", True, True),
        (1, "operational_layer", None, "roads_2", False, False),
        (2, "operational_layer", A2, "view_0", True, True),
        (3, "operational_layer", HYDRANTS, "hydrants_0", True, False),
        (4, "basemap", None, "World_Hillshade", False, False),
        (5, "table", A1, "owners_1", True, True),
    ]
    assert (
        deps[1]["to_url"]
        == "https://gis.example.gov/arcgis/rest/services/Roads/MapServer/2"
    )
    app_links = {
        (d["from_id"], d["to_id"], d["resolved"])
        for d in report["dependencies"]
        if d["role"] == "app_web_map"
    }
    assert app_links == {(C1, B1, True), (C3, B1, True)}
    rows = _rows(report)
    assert rows[B1]["dependencies_status"] == "parsed"
    assert rows[C1]["dependencies_status"] == "parsed"
    assert rows[C2]["dependencies_status"] == "unparsed"
    assert rows[A1]["dependencies_status"] == "not_applicable"


def test_item_data_is_read_only_for_maps_and_apps(run):
    """Feature layers and files are never fetched; only web maps and apps."""
    portal = FakePortal(portal_routes())
    run(portal, "--scope", "org")
    fetched = {s.path for s in portal.seen if s.path.endswith("/data")}
    assert fetched == {item_data_path(i) for i in (B1, B2, C1, C2, C3)}
    assert all(s.method == "GET" for s in portal.seen)


def test_failing_item_becomes_an_error_row_and_the_run_continues(run):
    """One /data 500 is an error row; the rest is read and the exit is 0."""
    portal = FakePortal(portal_routes())
    result, _ = run(portal, "--scope", "org")
    assert result.exit_code == 0, result.output
    report = _report(result)
    assert report["errors"] == [
        {
            "item_id": B2,
            "phase": "item_data",
            "http_status": 500,
            "message": f"HTTP 500 from /sharing/rest/content/items/{B2}/data",
        }
    ]
    assert report["counts"]["failed"] == 1
    assert _rows(report)[B2]["dependencies_status"] == "error"
    assert _rows(report)[C3]["dependencies_status"] == "parsed"
    assert len(portal.requests_to(item_data_path(B2))) == 1


def test_strict_turns_a_failed_item_into_a_nonzero_exit(run):
    """--strict exits 1 when any item could not be read."""
    result, _ = run(FakePortal(portal_routes()), "--scope", "org", "--strict")
    assert result.exit_code == 1
    assert _report(result)["counts"]["failed"] == 1


def test_token_rejected_mid_run_writes_a_partial_report_and_exits_3(run, tmp_path):
    """A 498 while reading item data stops the run, keeps a partial report, exits 3."""
    routes = portal_routes({item_data_path(C1): load("error_498.json")})
    portal = FakePortal(routes)
    result, _ = run(
        portal, "--scope", "org", "--output-dir", str(tmp_path), json_mode=False
    )
    assert result.exit_code == 3
    assert "fresh token" in result.stderr
    report = json.loads((tmp_path / "arcgis-inventory.json").read_text())
    assert report["complete"] is False
    assert "498" in report["abort_reason"]
    assert report["counts"]["total"] == 15
    assert _rows(report)[C1]["dependencies_status"] == "not_fetched"
    assert "Partial report" in (tmp_path / "arcgis-inventory.md").read_text()


def test_listing_failure_after_retries_keeps_earlier_pages(run):
    """A second search page that keeps failing yields a partial report, exit 5."""

    def search(seen):
        if seen.params["start"] == "1":
            return load("search_page1.json")
        return (503, {"error": {"code": 503}})

    result, sleeps = run(
        FakePortal(portal_routes({"search": search})), "--scope", "org"
    )
    assert result.exit_code == 5
    report = _report(result)
    assert report["complete"] is False
    assert report["counts"]["total"] == 8
    assert _rows(report)[B1]["dependencies_status"] == "not_fetched"
    assert [s for s in sleeps if s > inventory.MIN_REQUEST_INTERVAL + 1e-6] == [
        0.5,
        1.0,
    ]


def test_retry_after_is_honoured(run):
    """A 429 waits the Retry-After seconds, then the read succeeds."""
    routes = portal_routes(
        {"portals/self": [(429, {}, {"Retry-After": "7"}), load("portal_self.json")]}
    )
    result, sleeps = run(FakePortal(routes))
    assert result.exit_code == 0, result.output
    assert 7.0 in sleeps


def test_requests_are_spaced_out(run):
    """Consecutive requests are at least the minimum interval apart."""
    result, sleeps = run(FakePortal(portal_routes()), "--scope", "org")
    assert result.exit_code == 0
    assert sleeps and all(
        s == pytest.approx(inventory.MIN_REQUEST_INTERVAL) for s in sleeps
    )


def test_concurrent_item_reads_give_the_same_report(run):
    """--concurrency 4 reads the same items into the same rows."""
    serial, _ = run(FakePortal(portal_routes()), "--scope", "org")
    parallel, _ = run(
        FakePortal(portal_routes()), "--scope", "org", "--concurrency", "4"
    )
    first, second = _report(serial), _report(parallel)
    for key in ("items", "dependencies", "errors", "counts"):
        assert first[key] == second[key]


@pytest.mark.parametrize("value", ["0", "5"])
def test_concurrency_is_bounded(run, value):
    """--concurrency outside 1-4 is a usage error."""
    portal = FakePortal(portal_routes())
    result, _ = run(portal, "--concurrency", value)
    assert result.exit_code == 2
    assert portal.seen == []


def test_max_items_truncates_and_says_so(run):
    """--max-items stops listing early and marks the report truncated."""
    portal = FakePortal(portal_routes())
    result, _ = run(portal, "--scope", "org", "--max-items", "3")
    report = _report(result)
    assert report["counts"]["total"] == 3
    assert report["truncated"] is True
    assert [s.params["start"] for s in portal.requests_to("search")] == ["1"]
    markdown = arcgis_report.render_markdown(report)
    assert "Item cap reached" in markdown


def test_max_items_equal_to_the_total_is_not_truncated(run):
    """A cap that exactly fits the organization is not reported as truncation."""
    result, _ = run(FakePortal(portal_routes()), "--scope", "org", "--max-items", "15")
    assert _report(result)["truncated"] is False


def test_report_validates_against_the_packaged_schema(run):
    """The JSON report, complete or partial, matches the v2 schema."""
    validator = Draft202012Validator(
        arcgis_report.inventory_schema(), format_checker=FormatChecker()
    )
    result, _ = run(FakePortal(portal_routes()), "--scope", "org")
    validator.validate(_report(result))
    partial, _ = run(
        FakePortal(portal_routes({item_data_path(C1): load("error_498.json")})),
        "--scope",
        "org",
    )
    validator.validate(_report(partial))


def test_markdown_leads_with_the_retirement_deadlines(run):
    """The Markdown summary opens with dated, sourced retirement callouts."""
    result, _ = run(FakePortal(portal_routes()), "--scope", "org", json_mode=False)
    assert result.exit_code == 0, result.output
    markdown = result.stdout
    assert markdown.index("## Retirement deadlines") < markdown.index("## Summary")
    assert "**Web AppBuilder** (retiring, 2027-Q2): 1 item(s)" in markdown
    assert "Q4 2026" in markdown
    assert "**Classic Esri Story Maps** (retired, 2026-Q1): 1 item(s)" in markdown
    assert "wab-retirement.htm" in markdown
    assert "Our county \\| a story" in markdown
    assert "| Supported | 4 |" in markdown


def test_markdown_without_retired_items_has_no_callout(run):
    """No retirement section when nothing is retiring."""
    result, _ = run(
        FakePortal(portal_routes()),
        "--scope",
        "org",
        "--max-items",
        "2",
        json_mode=False,
    )
    assert "Retirement deadlines" not in result.stdout


def test_md_escape_neutralizes_markup():
    """Titles can't open links, tables, HTML or headings in the summary."""
    escaped = arcgis_report.md_escape("<img src=x> [a](b) | # *x*\nnext")
    assert "<" not in escaped and "\n" not in escaped
    assert "\\[a\\]" in escaped and "\\|" in escaped and "\\*x\\*" in escaped


def test_output_dir_files_are_private(run, tmp_path):
    """Report files are written with mode 0600."""
    out = tmp_path / "report"
    result, _ = run(FakePortal(portal_routes()), "--output-dir", str(out))
    assert result.exit_code == 0, result.output
    for name in ("arcgis-inventory.json", "arcgis-inventory.md"):
        assert stat.S_IMODE((out / name).stat().st_mode) == 0o600


def test_anonymous_user_scope_is_a_usage_error(run):
    """With no credentials only --scope org (public items) makes sense."""
    portal = FakePortal(portal_routes())
    result, _ = run(portal, token=None)
    assert result.exit_code == 2
    assert portal.seen == []


def test_anonymous_org_scope_lists_without_credentials(run):
    """Anonymous org scope sends no credential and records auth mode anonymous."""
    portal = FakePortal(portal_routes())
    result, _ = run(portal, "--scope", "org", token=None)
    assert result.exit_code == 0, result.output
    assert _report(result)["auth"]["mode"] == "anonymous"
    assert all(
        inventory.ESRI_AUTHORIZATION_HEADER.lower() not in s.headers
        for s in portal.seen
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://portal.example.com/portal",
        "https://portal.example.com/portal?x=1",
        "https://user:pw@portal.example.com/portal",
        "portal.example.com",
    ],
)
def test_portal_url_must_be_plain_https(runner, monkeypatch, url):
    """http, query strings, userinfo and relative URLs are refused up front."""
    portal = FakePortal(portal_routes())
    monkeypatch.setattr(inventory, "build_opener", lambda: portal)
    result = runner.invoke(
        app, ["arcgis", "inventory", "--portal-url", url, "--token", TOKEN]
    )
    assert result.exit_code == 2
    assert portal.seen == []


def test_http_portal_needs_the_explicit_flag(run, runner, monkeypatch):
    """--allow-insecure-http admits an http:// test portal."""
    portal = FakePortal(portal_routes())
    monkeypatch.setattr(inventory, "build_opener", lambda: portal)
    monkeypatch.setattr(inventory, "_sleep", lambda s: None)
    result = runner.invoke(
        app,
        [
            "--json",
            "arcgis",
            "inventory",
            "--portal-url",
            "http://portal.test/portal",
            "--allow-insecure-http",
            "--token",
            TOKEN,
        ],
    )
    assert result.exit_code == 0, result.output
    assert portal.seen[0].url.startswith(
        "http://portal.test/portal/sharing/rest/portals/self"
    )


def test_oversized_item_data_is_an_error_row(run):
    """A /data body past the 8 MiB cap is refused as an item error."""
    huge = b'{"pad": "' + b"x" * inventory.MAX_RESPONSE_BYTES + b'"}'
    routes = portal_routes({item_data_path(B1): (200, huge)})
    result, _ = run(FakePortal(routes), "--scope", "org")
    assert result.exit_code == 0, result.output
    errors = {e["item_id"]: e["message"] for e in _report(result)["errors"]}
    assert "larger than 8 MiB" in errors[B1]


def test_org_search_reaching_the_ceiling_is_flagged_truncated(run):
    """A search that hits ArcGIS's 10,000-result ceiling is truncated, whatever --max-items says."""

    def search(seen):
        start = int(seen.params["start"])
        rows = [
            {
                "id": f"{n:032x}",
                "type": "CSV",
                "title": f"File {n}",
                "owner": USER,
                "typeKeywords": [],
                "access": "org",
            }
            for n in range(start, start + 100)
        ]
        next_start = (
            start + 100 if start + 100 <= inventory.SEARCH_RESULT_CEILING else -1
        )
        return {
            "total": inventory.SEARCH_RESULT_CEILING,
            "start": start,
            "num": 100,
            "nextStart": next_start,
            "results": rows,
        }

    portal = FakePortal(portal_routes({"search": search}))
    result, _ = run(portal, "--scope", "org", "--max-items", "20000")
    assert result.exit_code == 0, result.output
    report = _report(result)
    assert len(portal.requests_to("search")) == 100
    assert report["counts"]["total"] == inventory.SEARCH_RESULT_CEILING
    assert report["truncated"] is True
    assert report["truncation_reasons"] == ["search_ceiling"]
    markdown = arcgis_report.render_markdown(report)
    assert "Search limit reached" in markdown
    assert "can't get past this server limit" in markdown


def test_dependency_collection_does_not_retain_item_configurations():
    """Peak memory stays flat however many large web map configurations are read."""
    payload = json.dumps(
        {
            "baseMap": {"baseMapLayers": []},
            "operationalLayers": [
                {"id": "l0", "itemId": A1, "layerType": "ArcGISFeatureLayer"}
            ],
            "pad": "x" * (1024 * 1024),
        }
    ).encode()
    ids = [f"{n:032x}" for n in range(40)]
    rows = [
        {
            "id": i,
            "type": "Web Map",
            "title": i,
            "owner": USER,
            "typeKeywords": [],
            "access": "org",
        }
        for i in ids
    ]
    routes = portal_routes(
        {
            "search": {
                "total": 40,
                "start": 1,
                "num": 100,
                "nextStart": -1,
                "results": rows,
            }
        }
    )
    routes.update({item_data_path(i): (200, payload) for i in ids})
    client = inventory.PortalClient(
        PORTAL,
        opener=FakePortal(routes),
        redact=inventory.Redactor(),
        token=TOKEN,
        sleep=lambda seconds: None,
    )
    tracemalloc.start()
    try:
        inv = inventory.run_inventory(
            client, auth_mode="token", scope="org", max_items=100, concurrency=1
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(inv.dependencies) == 40
    assert peak < 12 * 1024 * 1024


def test_dashboard_chart_datasets_are_data_source_dependencies(run):
    """A dashboard whose only reference is a chart's dataset records that layer."""
    chart_only = {
        "widgets": [
            {
                "type": "serialChartWidget",
                "id": "w3",
                "datasets": [
                    {
                        "type": "serviceDataset",
                        "dataSource": {
                            "type": "featureServiceDataSource",
                            "itemId": A1,
                            "layerId": 0,
                        },
                    }
                ],
            }
        ]
    }
    result, _ = run(
        FakePortal(portal_routes({item_data_path(C3): chart_only})), "--scope", "org"
    )
    assert result.exit_code == 0, result.output
    report = _report(result)
    deps = [d for d in report["dependencies"] if d["from_id"] == C3]
    assert [(d["role"], d["to_id"], d["layer_id"], d["resolved"]) for d in deps] == [
        ("app_data_source", A1, "0", True)
    ]
    assert _rows(report)[C3]["dependencies_status"] == "parsed"


@pytest.mark.parametrize("blank_start", ["1", "9"])
@pytest.mark.parametrize(
    ("body", "reason"), [(b"", "empty body"), (b"{}", "no 'results' list")]
)
def test_blank_listing_page_is_a_partial_failure(run, blank_start, body, reason):
    """A blank or itemless search page stops the run non-zero instead of ending the listing as complete."""

    def search(seen):
        if seen.params["start"] == blank_start:
            return (200, body)
        return load(
            "search_page1.json" if seen.params["start"] == "1" else "search_page2.json"
        )

    result, _ = run(FakePortal(portal_routes({"search": search})), "--scope", "org")
    assert result.exit_code == 1
    report = _report(result)
    assert report["complete"] is False
    assert report["counts"]["total"] == (0 if blank_start == "1" else 8)
    assert reason in report["abort_reason"]


class _TricklingResponse:
    """A body that yields one byte every 3 s; read(n) blocks until n bytes, like a buffered reader."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.headers = http.client.HTTPMessage()

    def _byte(self) -> bytes:
        self.clock.now += 3.0
        return b" "

    def read(self, size: int = -1) -> bytes:
        return b"".join(self._byte() for _ in range(size))

    def read1(self, size: int = -1) -> bytes:
        return self._byte()

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_trickling_response_is_cut_off_at_the_deadline(monkeypatch):
    """A server trickling bytes under the socket timeout still hits the request deadline."""
    monkeypatch.setattr(inventory, "GET_ATTEMPTS", 1)
    clock = FakeClock()

    class Opener:
        def open(self, request, timeout=None):
            return _TricklingResponse(clock)

    client = inventory.PortalClient(
        PORTAL,
        opener=Opener(),
        redact=inventory.Redactor(),
        sleep=clock.sleep,
        clock=clock,
    )
    began = clock.now
    with pytest.raises(inventory.PortalError, match="took longer") as caught:
        client.get_json("portals/self")
    assert caught.value.kind == "network"
    assert clock.now - began <= inventory.REQUEST_DEADLINE + 3.0


class _StallingPortal(http.server.BaseHTTPRequestHandler):
    release = threading.Event()

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", "100")
        self.end_headers()
        self.wfile.write(b"{")
        self.wfile.flush()
        type(self).release.wait(10)

    def log_message(self, *args: object) -> None:
        return None


def test_stalled_body_read_is_bounded_by_the_remaining_deadline(monkeypatch):
    """A body that stops arriving times out at the deadline, not the longer socket timeout."""
    monkeypatch.setattr(inventory, "GET_ATTEMPTS", 1)
    monkeypatch.setattr(inventory, "REQUEST_DEADLINE", 0.5)
    monkeypatch.setattr(inventory, "SOCKET_TIMEOUT", 5.0)
    monkeypatch.setenv("NO_PROXY", "*")
    _StallingPortal.release = threading.Event()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StallingPortal)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = inventory.PortalClient(
            f"http://127.0.0.1:{server.server_address[1]}/portal",
            opener=inventory.build_opener(),
            redact=inventory.Redactor(),
            sleep=lambda seconds: None,
        )
        began = time.monotonic()
        with pytest.raises(inventory.PortalError):
            client.get_json("portals/self")
        assert time.monotonic() - began < 2.5
    finally:
        _StallingPortal.release.set()
        server.shutdown()
        server.server_close()


def test_token_ignored_by_the_portal_fails_instead_of_listing_public_items(run):
    """A portal that answers anonymously despite a token fails auth and writes no report."""
    anonymous_self = {k: v for k, v in load("portal_self.json").items() if k != "user"}
    portal = FakePortal(portal_routes({"portals/self": anonymous_self}))
    result, _ = run(portal, "--scope", "org")
    assert result.exit_code == 3
    assert result.stdout.strip() == ""
    assert "without a signed-in user" in result.stderr
    assert portal.requests_to("search") == []
    assert [s.method for s in portal.requests_to("portals/self")] == ["GET", "POST"]


def test_token_ignored_in_the_header_but_read_from_the_form_proceeds(run):
    """An anonymous answer to the header gets one form-field retry, which can sign in."""

    def self_info(seen):
        info = load("portal_self.json")
        if seen.method == "GET":
            info.pop("user")
        return info

    portal = FakePortal(portal_routes({"portals/self": self_info}))
    result, _ = run(portal, "--scope", "org")
    assert result.exit_code == 0, result.output
    assert _report(result)["auth"] == {"mode": "token", "user": USER}
    assert all(s.method == "POST" for s in portal.seen[1:])


def test_http_498_during_item_data_stops_the_run(run):
    """A 498 transport status on item data is a rejected token, not an item error."""
    routes = portal_routes({item_data_path(B1): (498, load("error_498.json"))})
    result, _ = run(FakePortal(routes), "--scope", "org")
    assert result.exit_code == 3
    report = _report(result)
    assert report["complete"] is False
    assert "HTTP 498" in report["abort_reason"]
    assert report["errors"] == []


def test_http_499_during_search_tries_the_form_field_then_fails(run):
    """A 499 transport status gets the form-field fallback once, then fails auth."""
    portal = FakePortal(portal_routes({"search": (499, {"error": {"code": 499}})}))
    result, _ = run(portal, "--scope", "org")
    assert result.exit_code == 3
    report = _report(result)
    assert report["complete"] is False
    assert "HTTP 499" in report["abort_reason"]
    assert [s.method for s in portal.requests_to("search")] == ["GET", "POST"]


def test_empty_web_map_body_is_an_item_error(run):
    """An empty web map configuration is a failed read: an error row, and --strict fails."""
    routes = portal_routes(
        {
            item_data_path(B1): (200, b""),
            item_data_path(B2): load("item_web_map_data.json"),
        }
    )
    result, _ = run(FakePortal(routes), "--scope", "org", "--strict")
    assert result.exit_code == 1
    report = _report(result)
    assert report["complete"] is True
    assert report["counts"]["total"] == 15
    errors = {e["item_id"]: e["message"] for e in report["errors"]}
    assert list(errors) == [B1]
    assert "empty body" in errors[B1]
    assert _rows(report)[B1]["dependencies_status"] == "error"
    assert not [d for d in report["dependencies"] if d["from_id"] == B1]
    assert _rows(report)[C1]["dependencies_status"] == "parsed"


def test_web_map_without_layer_keys_is_an_item_error(run):
    """A JSON object with no web map structure is not recorded as a map without dependencies."""
    routes = portal_routes({item_data_path(B1): {"version": "2.31"}})
    result, _ = run(FakePortal(routes), "--scope", "org")
    report = _report(result)
    errors = {e["item_id"]: e["message"] for e in report["errors"]}
    assert "not a web map configuration" in errors[B1]
    assert _rows(report)[B1]["dependencies_status"] == "error"


def test_valid_web_map_without_layers_is_parsed(run):
    """A well-formed web map with no layers is parsed with no dependencies, not an error."""
    empty_map = {"operationalLayers": [], "baseMap": {"baseMapLayers": []}}
    routes = portal_routes({item_data_path(B1): empty_map})
    result, _ = run(FakePortal(routes), "--scope", "org", "--strict")
    report = _report(result)
    assert B1 not in {e["item_id"] for e in report["errors"]}
    assert _rows(report)[B1]["dependencies_status"] == "parsed"
    assert not [d for d in report["dependencies"] if d["from_id"] == B1]


def test_web_map_without_basemap_is_an_item_error_and_fails_strict(run):
    """A map with operational layers but no baseMap is an invalid item; --strict fails."""
    routes = portal_routes({item_data_path(B1): {"operationalLayers": []}})
    result, _ = run(FakePortal(routes), "--scope", "org", "--strict")
    report = _report(result)
    assert result.exit_code != 0
    errors = {e["item_id"]: e["message"] for e in report["errors"]}
    assert "not a web map configuration" in errors[B1]
    assert _rows(report)[B1]["dependencies_status"] == "error"
    assert _rows(report)[C1]["dependencies_status"] == "parsed"


def test_app_without_data_stays_unparsed(run):
    """An app registered only by URL has an empty data body; that is not an error."""
    routes = portal_routes({item_data_path(C2): (200, b"")})
    result, _ = run(FakePortal(routes), "--scope", "org")
    report = _report(result)
    assert C2 not in {e["item_id"] for e in report["errors"]}
    assert _rows(report)[C2]["dependencies_status"] == "unparsed"


@pytest.mark.parametrize(
    ("layer", "expected"),
    [
        (
            {
                "templateUrl": "https://{subDomain}.tiles.example.com/{level}/{col}/{row}.png?key=k"
            },
            "https://{subDomain}.tiles.example.com/{level}/{col}/{row}.png",
        ),
        (
            {
                "wmtsInfo": {
                    "url": "https://wmts.example.com/wmts?token=t",
                    "layerIdentifier": "base",
                }
            },
            "https://wmts.example.com/wmts",
        ),
    ],
)
def test_tiled_basemap_urls_are_recorded(run, layer, expected):
    """WebTiledLayer basemaps keep their template or WMTS URL, without its query."""
    web_map = {
        "operationalLayers": [],
        "baseMap": {
            "baseMapLayers": [{"id": "tiles", "layerType": "WebTiledLayer", **layer}]
        },
    }
    result, _ = run(
        FakePortal(portal_routes({item_data_path(B1): web_map})), "--scope", "org"
    )
    assert result.exit_code == 0, result.output
    deps = [d for d in _report(result)["dependencies"] if d["from_id"] == B1]
    assert [(d["role"], d["to_id"], d["to_url"]) for d in deps] == [
        ("basemap", None, expected)
    ]


class _TricklingPortal(http.server.BaseHTTPRequestHandler):
    """Sends ``prefix``, then one byte every 0.1 s for 5 s; the line never ends."""

    prefix = b""
    release = threading.Event()

    def do_GET(self) -> None:  # noqa: N802
        try:
            self.wfile.write(self.prefix)
            self.wfile.flush()
            for _ in range(50):
                if type(self).release.wait(0.1):
                    return
                self.wfile.write(b"0")
                self.wfile.flush()
        except OSError:
            return

    def log_message(self, *args: object) -> None:
        return None


@pytest.fixture(scope="module")
def loopback_tls(tmp_path_factory):
    """A throwaway self-signed certificate for 127.0.0.1, made with the openssl CLI."""
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("the openssl CLI is needed to make a test certificate")
    folder = tmp_path_factory.mktemp("tls")
    cert, key = folder / "cert.pem", folder / "key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:prime256v1",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    server_side = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_side.load_cert_chain(cert, key)
    return server_side, ssl.create_default_context(cafile=str(cert))


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize(
    "prefix",
    [
        pytest.param(b"HTTP/1.1 200 OK\r\nX-Slow: ", id="headers"),
        pytest.param(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n", id="chunk-framing"
        ),
    ],
)
def test_trickled_headers_and_chunk_framing_stop_at_the_deadline(
    monkeypatch, request, prefix, scheme
):
    """A response trickled anywhere, over HTTP or TLS, gives up at the request deadline."""
    monkeypatch.setattr(inventory, "GET_ATTEMPTS", 1)
    monkeypatch.setattr(inventory, "REQUEST_DEADLINE", 0.5)
    monkeypatch.setattr(inventory, "SOCKET_TIMEOUT", 5.0)
    monkeypatch.setenv("NO_PROXY", "*")
    handler = type(
        "Handler", (_TricklingPortal,), {"prefix": prefix, "release": threading.Event()}
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    client_context = None
    if scheme == "https":
        server_context, client_context = request.getfixturevalue("loopback_tls")
        server.socket = server_context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = inventory.PortalClient(
            f"{scheme}://127.0.0.1:{server.server_address[1]}/portal",
            opener=inventory.build_opener(context=client_context),
            redact=inventory.Redactor(),
            sleep=lambda seconds: None,
        )
        began = time.monotonic()
        with pytest.raises(inventory.PortalError, match="took longer than 0.5 s"):
            client.get_json("portals/self")
        assert time.monotonic() - began < 1.5
    finally:
        handler.release.set()
        server.shutdown()
        server.server_close()


def test_url_only_data_sources_are_recorded(run):
    """An Experience Builder source named only by URL is a dependency, deduplicated by URL."""
    roads = "https://gis.example.gov/arcgis/rest/services/Roads/FeatureServer/0"
    config = {
        "dataSources": {
            "ds1": {"type": "FEATURE_LAYER", "url": f"{roads}?token=stored"},
            "ds2": {"type": "FEATURE_LAYER", "url": roads},
            "ds3": {"type": "FEATURE_LAYER", "url": roads.replace("/0", "/1")},
        }
    }
    result, _ = run(
        FakePortal(portal_routes({item_data_path(C1): config})), "--scope", "org"
    )
    assert result.exit_code == 0, result.output
    deps = [d for d in _report(result)["dependencies"] if d["from_id"] == C1]
    assert [(d["role"], d["to_id"], d["to_url"], d["resolved"]) for d in deps] == [
        ("app_data_source", None, roads, False),
        ("app_data_source", None, roads.replace("/0", "/1"), False),
    ]


def test_transient_error_envelope_is_retried(run):
    """A 503 error envelope inside an HTTP 200 is retried like the HTTP status."""
    busy = {"error": {"code": 503, "message": "Service busy"}}
    portal = FakePortal(
        portal_routes({item_data_path(B1): [busy, load("item_web_map_data.json")]})
    )
    result, sleeps = run(portal, "--scope", "org")
    assert result.exit_code == 0, result.output
    report = _report(result)
    assert B1 not in {e["item_id"] for e in report["errors"]}
    assert _rows(report)[B1]["dependencies_status"] == "parsed"
    assert len(portal.requests_to(item_data_path(B1))) == 2
    assert 0.5 in sleeps


def _http_date(seconds_from_now: float) -> str:
    when = datetime.now(tz=UTC) + timedelta(seconds=seconds_from_now)
    return email.utils.format_datetime(when, usegmt=True)


def test_retry_after_http_date_is_honoured_and_clamped(run):
    """A Retry-After HTTP-date an hour away waits the 60 s maximum."""
    routes = portal_routes(
        {
            "portals/self": [
                (429, {}, {"Retry-After": _http_date(3600)}),
                load("portal_self.json"),
            ]
        }
    )
    result, sleeps = run(FakePortal(routes))
    assert result.exit_code == 0, result.output
    assert inventory.MAX_RETRY_AFTER in sleeps


@pytest.mark.parametrize(("offset", "expected"), [(10, 10.0), (-30, 0.0)])
def test_retry_after_http_date_gives_the_time_until_that_date(offset, expected):
    """An HTTP-date Retry-After becomes the seconds until that date, never negative."""
    wait = inventory._retry_after({"Retry-After": _http_date(offset)})
    assert wait == pytest.approx(expected, abs=1.5)


@pytest.mark.parametrize("bad_type", [[], {}])
def test_malformed_app_config_is_an_item_error_not_a_lost_report(run, bad_type):
    """A data source with a non-string type fails that item only; the report survives."""
    routes = portal_routes(
        {
            item_data_path(C3): {
                "dataSources": {"ds": {"type": bad_type, "itemId": A1}}
            },
            item_data_path(B2): load("item_web_map_data.json"),
        }
    )
    result, _ = run(FakePortal(routes), "--scope", "org", "--strict")
    assert result.exit_code == 1
    report = _report(result)
    assert report["complete"] is True
    assert report["counts"]["total"] == 15
    errors = {e["item_id"]: e["message"] for e in report["errors"]}
    assert list(errors) == [C3]
    assert "malformed configuration" in errors[C3]
    assert _rows(report)[C3]["dependencies_status"] == "error"
    assert _rows(report)[B1]["dependencies_status"] == "parsed"
    assert _rows(report)[C1]["dependencies_status"] == "parsed"


def test_tiled_service_sublayer_query_services_are_recorded(run):
    """A tiled map service keeps its own row, plus one per sublayer query service."""
    tiles = "https://tiles1.arcgis.com/tiles/ExAmPlEoRg0123/arcgis/rest/services/Parcels/MapServer"
    query = "https://services1.arcgis.com/ExAmPlEoRg0123/arcgis/rest/services/Parcels/FeatureServer/0"
    web_map = {
        "baseMap": {"baseMapLayers": []},
        "operationalLayers": [
            {
                "id": "parcel_tiles",
                "layerType": "ArcGISTiledMapServiceLayer",
                "itemId": A4,
                "url": tiles,
                "layers": [
                    {
                        "id": 0,
                        "name": "Parcels",
                        "layerItemId": A1,
                        "layerUrl": f"{query}?token=stored",
                    },
                    {"id": 1, "name": "Labels"},
                ],
            }
        ],
    }
    result, _ = run(
        FakePortal(portal_routes({item_data_path(B1): web_map})), "--scope", "org"
    )
    assert result.exit_code == 0, result.output
    deps = [d for d in _report(result)["dependencies"] if d["from_id"] == B1]
    assert [
        (d["role"], d["to_id"], d["to_url"], d["layer_id"], d["resolved"]) for d in deps
    ] == [
        ("operational_layer", A4, tiles, "parcel_tiles", True),
        ("operational_layer", A1, query, "parcel_tiles/0", True),
    ]


def test_basemap_map_service_sublayer_url_is_recorded(run):
    """A map service sublayer named only by layerUrl is recorded, in a basemap too."""
    zoning = "https://gis.example.gov/arcgis/rest/services/Zoning/MapServer"
    web_map = {
        "baseMap": {
            "baseMapLayers": [
                {
                    "id": "zoning",
                    "layerType": "ArcGISMapServiceLayer",
                    "url": zoning,
                    "layers": [
                        {
                            "id": 3,
                            "layerUrl": f"{zoning.replace('MapServer', 'FeatureServer')}/3",
                        }
                    ],
                }
            ]
        }
    }
    result, _ = run(
        FakePortal(portal_routes({item_data_path(B1): web_map})), "--scope", "org"
    )
    deps = [d for d in _report(result)["dependencies"] if d["from_id"] == B1]
    assert [(d["role"], d["to_id"], d["to_url"], d["layer_id"]) for d in deps] == [
        ("basemap", None, zoning, "zoning"),
        (
            "basemap",
            None,
            f"{zoning.replace('MapServer', 'FeatureServer')}/3",
            "zoning/3",
        ),
    ]


@pytest.mark.parametrize(
    ("kind", "url", "expected"),
    [
        (
            "online",
            "https://services-eu1.arcgis.com/Org/arcgis/rest/services/P/FeatureServer/0",
            True,
        ),
        (
            "online",
            "https://tiles-eu1.arcgis.com/tiles/Org/arcgis/rest/services/T/MapServer",
            True,
        ),
        (
            "online",
            "https://services7.arcgis.com/Org/arcgis/rest/services/P/FeatureServer/0",
            True,
        ),
        (
            "online",
            "https://gis.example.gov/arcgis/rest/services/Roads/MapServer/2",
            False,
        ),
        (
            "enterprise",
            "https://gisserver.example.com/server/rest/services/Roads/MapServer/2",
            None,
        ),
        (
            "enterprise",
            "https://gisserver.example.com/server/rest/services/Hosted/Parcels/FeatureServer/0",
            True,
        ),
    ],
)
def test_hosted_check_by_url(kind, url, expected):
    """Regional Online hosts count as hosted; an Enterprise URL that can't prove it is unknown."""
    portal = {"url": "https://gis.example.com/portal", "kind": kind}
    assert inventory._hosted_by_url(url, portal) is expected


def test_unknown_hosting_renders_as_unknown(run):
    """On an Enterprise portal a non-Hosted service is unknown, and the summary says so."""
    enterprise_self = {**load("portal_self.json"), "isPortal": True}
    portal = FakePortal(portal_routes({"portals/self": enterprise_self}))
    result, _ = run(portal, "--scope", "org")
    report = _report(result)
    roads = next(d for d in report["dependencies"] if d["layer_id"] == "roads_2")
    assert roads["hosted"] is None
    line = next(
        text
        for text in arcgis_report.render_markdown(report).splitlines()
        if "Roads/MapServer/2" in text
    )
    assert "| unknown |" in line


def test_failed_item_reads_do_not_retain_their_responses(monkeypatch):
    """Peak memory stays flat when many items fail with oversized responses."""
    monkeypatch.setattr(inventory, "MAX_RESPONSE_BYTES", 1024 * 1024)
    oversized = b"x" * (2 * 1024 * 1024)
    ids = [f"{n:032x}" for n in range(30)]
    rows = [
        {
            "id": i,
            "type": "Web Map",
            "title": i,
            "owner": USER,
            "typeKeywords": [],
            "access": "org",
        }
        for i in ids
    ]
    routes = portal_routes(
        {
            "search": {
                "total": 30,
                "start": 1,
                "num": 100,
                "nextStart": -1,
                "results": rows,
            }
        }
    )
    routes.update({item_data_path(i): (200, oversized) for i in ids})
    for row in rows:
        routes[f"content/items/{row['id']}"] = row
        routes[f"content/items/{row['id']}/groups"] = EMPTY_GROUPS
    client = inventory.PortalClient(
        PORTAL,
        opener=FakePortal(routes),
        redact=inventory.Redactor(),
        token=TOKEN,
        sleep=lambda seconds: None,
    )
    tracemalloc.start()
    try:
        inv = inventory.run_inventory(
            client, auth_mode="token", scope="org", max_items=100, concurrency=1
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(inv.errors) == 30
    assert peak < 12 * 1024 * 1024


def test_registered_group_layer_keeps_its_own_reference(run):
    """A group layer with its own itemId gets a row before its children's rows."""
    group_item = "e7" * 16
    web_map = {
        "baseMap": {"baseMapLayers": []},
        "operationalLayers": [
            {
                "id": "parcels_group",
                "layerType": "GroupLayer",
                "itemId": group_item,
                "layers": [
                    {"id": "parcels_0", "layerType": "ArcGISFeatureLayer", "itemId": A1}
                ],
            },
            {
                "id": "plain_group",
                "layerType": "GroupLayer",
                "layers": [{"id": "view_0", "itemId": A2}],
            },
        ],
    }
    result, _ = run(
        FakePortal(portal_routes({item_data_path(B1): web_map})), "--scope", "org"
    )
    assert result.exit_code == 0, result.output
    deps = [d for d in _report(result)["dependencies"] if d["from_id"] == B1]
    assert [(d["to_id"], d["layer_type"], d["layer_id"], d["order"]) for d in deps] == [
        (group_item, "GroupLayer", "parcels_group", 0),
        (A1, "ArcGISFeatureLayer", "parcels_0", 1),
        (A2, None, "view_0", 2),
    ]
