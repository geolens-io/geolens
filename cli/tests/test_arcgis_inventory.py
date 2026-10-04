"""`geolens arcgis inventory`: listing, classification, dependencies, report."""

from __future__ import annotations

import json
import stat
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
    assert rows[A2]["sharing"] == {"access": "public", "groups": None}
    assert rows[A1]["owner"] == USER
    assert rows[A1]["created"] == "2026-01-01T00:00:00Z"
    assert rows[A1]["modified"] == "2026-01-02T00:00:00Z"


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
    """The JSON report, complete or partial, matches the v1 schema."""
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
