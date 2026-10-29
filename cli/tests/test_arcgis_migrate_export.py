"""`geolens arcgis migrate`: the export bundle for items GeoLens can't host."""

from __future__ import annotations

import json
import secrets
import shutil
import stat
from pathlib import Path

import httpx
import pytest

from geolens_cli import arcgis_migrate as migrate
from geolens_cli import arcgis_migrate_export as export_module
from geolens_cli.arcgis_migrate_state import MigrationState
from geolens_cli.arcgis_portal import redact_json

from . import test_arcgis_migrate_layers as layers
from .arcgis_fake import C1, C2, C3, D1, FakePortal, portal_routes
from .test_arcgis_migrate_layers import _migrate, _state, _write_plan

geolens = layers.geolens
quick = layers.quick

STORY_FIXTURE = Path(__file__).parent / "fixtures" / "arcgis_story"
TOKEN = secrets.token_urlsafe(16)
WEB_MAP = "b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1"


def _resources(*names: str) -> dict:
    return {
        "total": len(names),
        "start": 1,
        "num": len(names),
        "nextStart": -1,
        "resources": [{"resource": n, "size": 3} for n in names],
    }


def _routes(overrides: dict | None = None) -> dict:
    return portal_routes(overrides)


@pytest.fixture
def install(monkeypatch):
    def install(overrides: dict | None = None) -> FakePortal:
        portal = FakePortal(_routes(overrides))
        monkeypatch.setattr(migrate, "build_opener", lambda: portal)
        return portal

    return install


def _plan(tmp_path: Path, rows: dict | None = None) -> Path:
    """A plan whose export items depend on nothing, so they run alone."""
    path = _write_plan(tmp_path, rows=rows)
    plan = json.loads(path.read_text())
    for item in plan["items"]:
        if item["action"] == "export_only":
            item["depends_on"] = []
    path.write_text(json.dumps(plan))
    return path


def _export(plan_file: Path, *parts: str) -> Path:
    return plan_file.parent.joinpath("export", *parts)


def test_a_dashboard_is_saved_with_its_data_and_resources(
    runner, tmp_path, geolens, install
):
    token = secrets.token_urlsafe(16)
    portal = install(
        {
            f"content/items/{C3}/resources": _resources("logo.png", "notes/info.json"),
            f"content/items/{C3}/resources/logo.png": b"PNG",
            f"content/items/{C3}/resources/notes/info.json": {"apiKey": "k", "ok": 1},
        }
    )
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", token)

    assert result.exit_code == 0, result.output
    folder = _export(plan_file, "dashboard", C3)
    assert set(json.loads((folder / "item.json").read_text())) == {"inventory", "item"}
    assert json.loads((folder / "data.json").read_text())
    assert (folder / "resources" / "logo.png").read_bytes() == b"PNG"
    info = json.loads((folder / "resources" / "notes" / "info.json").read_text())
    assert info == {"apiKey": "[REDACTED]", "ok": 1}
    index = _export(plan_file, "INDEX.md").read_text()
    assert "Parcel dashboard" in index and "Maps carry over" in index
    entry = _state(plan_file)["items"][C3]
    assert entry["status"] == "done" and entry["export"]["partial"] is False
    assert entry["owner_id"] is None
    assert {r.headers.get("x-esri-authorization") for r in portal.seen} == {
        f"Bearer {token}"
    }


def test_every_exported_file_and_folder_is_private_and_holds_no_credential(
    runner, tmp_path, geolens, install
):
    token = secrets.token_urlsafe(16)
    install(
        {
            f"content/items/{C3}/data": {"title": "x", "note": f"token={token}"},
            f"content/items/{C3}/resources": _resources("logo.png", "deep/a.bin"),
            f"content/items/{C3}/resources/logo.png": b"PNG",
            f"content/items/{C3}/resources/deep/a.bin": b"BIN",
        }
    )
    plan_file = _plan(tmp_path, rows={C3: {"type": "Form"}})

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", token)

    assert result.exit_code == 0, result.output
    entries = list(_export(plan_file).rglob("*"))
    files = [p for p in entries if p.is_file()]
    assert {p.name for p in files} >= {"logo.png", "a.bin", "item.json", "INDEX.md"}
    for path in entries:
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == (0o600 if path.is_file() else 0o700), path
    for path in files:
        assert token.encode() not in path.read_bytes()


def test_an_item_without_data_saves_only_its_json_and_no_error(
    runner, tmp_path, geolens, install
):
    portal = install(
        {
            f"content/items/{D1}/data": (400, {"error": {"code": 400}}),
            f"content/items/{D1}/resources": _resources(),
        }
    )
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D1, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    folder = _export(plan_file, "image-service", D1)
    assert sorted(p.name for p in folder.iterdir()) == ["item.json"]
    assert portal.requests_to(f"content/items/{D1}/data")
    assert _state(plan_file)["items"][D1]["export"]["errors"] == []


def test_a_service_type_that_stores_data_is_saved(runner, tmp_path, geolens, install):
    install({f"content/items/{D1}/data": b"<kml>uploaded</kml>"})
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D1, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    folder = _export(plan_file, "image-service", D1)
    assert (folder / "data.bin").read_bytes() == b"<kml>uploaded</kml>"


def test_a_storymap_gets_story_text_images_and_map_links(
    runner, tmp_path, geolens, install
):
    data = json.loads((STORY_FIXTURE / "storymap_data.json").read_text())
    install(
        {
            f"content/items/{C2}/data": data,
            f"content/items/{C2}/resources": _resources("cover photo.jpg"),
            f"content/items/{C2}/resources/cover%20photo.jpg": b"JPG",
        }
    )
    plan_file = _plan(tmp_path, rows={C2: {"type": "StoryMap"}})

    result, _ = _migrate(runner, plan_file, "--only", C2)

    assert result.exit_code == 0, result.output
    folder = _export(plan_file, "storymap", C2)
    text = (folder / "story.md").read_text()
    assert text.startswith("# Open Space Theme")
    assert "![Preserve, 2025](resources/cover%20photo.jpg)" in text
    # The web map wasn't migrated, so the link points at the ArcGIS item.
    assert f"/home/item.html?id={WEB_MAP}" in text
    assert (folder / "resources" / "cover photo.jpg").read_bytes() == b"JPG"
    assert _state(plan_file)["items"][C2]["export"]["story"] is True


_TILE_CONFIG = "GET /settings/tile-config/"


def _lost_on_the_network(seen):
    raise httpx.ReadTimeout("slow")


@pytest.mark.parametrize(
    ("reply", "origin"),
    [
        ({"public_app_url": "https://maps.example.org/"}, "https://maps.example.org"),
        ({"public_app_url": None}, "https://geolens.example.org"),
        (
            (500, {"detail": "boom", "status": 500, "title": "Error"}),
            "https://geolens.example.org",
        ),
        (_lost_on_the_network, "https://geolens.example.org"),
    ],
)
def test_a_story_links_to_the_geolens_map_made_from_its_web_map(
    runner, tmp_path, geolens, install, reply, origin
):
    geolens.routes[_TILE_CONFIG] = reply
    data = json.loads((STORY_FIXTURE / "storymap_data.json").read_text())
    install({f"content/items/{C2}/data": data})
    plan_file = _plan(tmp_path, rows={C2: {"type": "StoryMap"}})
    state = plan_file.parent / "arcgis-migration-state.json"
    state.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "portal_url": json.loads(plan_file.read_text())["portal"]["url"],
                "geolens_instance": layers.GEOLENS_INSTANCE,
                "items": {WEB_MAP: {"status": "done", "map_id": "m-123"}},
            }
        )
    )

    result, _ = _migrate(runner, plan_file, "--only", C2)

    assert result.exit_code == 0, result.output
    text = (_export(plan_file, "storymap", C2) / "story.md").read_text()
    assert f"({origin}/maps/m-123)" in text
    # Read once, when the story first links to a GeoLens map.
    reads = [s for s in geolens.seen if s.url.endswith("/settings/tile-config/")]
    assert len(reads) == 1


def test_the_web_app_url_is_read_once_for_every_story_link():
    from types import SimpleNamespace

    from geolens_cli import arcgis_migrate_export as export
    from geolens_cli.arcgis_migrate_session import MigrationContext

    calls: list[object] = []

    class GeoLens:
        def call(self, fn):
            calls.append(fn)
            return SimpleNamespace(public_app_url="https://maps.example.org")

    ctx = MigrationContext(
        geolens=GeoLens(),
        inventory={},
        portal=None,
        save=lambda: None,
        items={"a": SimpleNamespace(map_id="m-1"), "b": SimpleNamespace(map_id="m-2")},
        web_origin="https://geolens.example.org",
    )

    assert [export._map_link(ctx, i) for i in ("a", "b")] == [
        "https://maps.example.org/maps/m-1",
        "https://maps.example.org/maps/m-2",
    ]
    assert len(calls) == 1


def test_the_size_cap_stops_the_download_and_marks_the_item_partial(
    runner, tmp_path, geolens, install
):
    install(
        {
            f"content/items/{C3}/resources": _resources("a.bin", "b.bin"),
            f"content/items/{C3}/resources/a.bin": b"x" * 600_000,
            f"content/items/{C3}/resources/b.bin": b"y" * 600_000,
        }
    )
    plan_file = _plan(tmp_path)

    result, _ = _migrate(
        runner, plan_file, "--only", C3, "--token", TOKEN, "--export-cap-mb", "1"
    )

    assert result.exit_code == 0, result.output
    folder = _export(plan_file, "dashboard", C3) / "resources"
    assert (folder / "a.bin").exists() and not (folder / "b.bin").exists()
    entry = _state(plan_file)["items"][C3]
    assert entry["export"]["partial"] is True
    assert "partial" in entry["notes"][1]
    assert "| partial |" in _export(plan_file, "INDEX.md").read_text()


def test_a_refused_resource_list_is_recorded_and_the_item_still_completes(
    runner, tmp_path, geolens, install
):
    install({f"content/items/{C3}/resources": (403, {"error": {"code": 403}})})
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][C3]
    assert entry["status"] == "done"
    assert any("resources" in e for e in entry["export"]["errors"])
    assert "complete, with errors" in _export(plan_file, "INDEX.md").read_text()


def test_an_unsafe_resource_name_is_not_written(runner, tmp_path, geolens, install):
    install({f"content/items/{C3}/resources": _resources("../../escape.txt")})
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "escape.txt").exists()
    assert any(
        "unsafe" in e for e in _state(plan_file)["items"][C3]["export"]["errors"]
    )


def test_a_public_item_is_exported_anonymously(runner, tmp_path, geolens, install):
    portal = install()
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", C1)

    assert result.exit_code == 0, result.output
    assert all("x-esri-authorization" not in r.headers for r in portal.seen)
    assert (_export(plan_file, "web-mapping-application", C1) / "data.json").exists()


def test_a_rejected_token_stops_the_run(runner, tmp_path, geolens, install):
    token = secrets.token_urlsafe(16)
    install({f"content/items/{C3}": (498, {"error": {"code": 498}})})
    plan_file = _plan(tmp_path)

    result, payload = _migrate(runner, plan_file, "--only", C3, "--token", token)

    assert result.exit_code == 1
    assert "fresh token" in payload["stopped"]
    assert token not in result.output


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "a/../../escape.txt",
        "..\\escape.txt",
        "a/..\\b",
        "C:\\temp\\x",
        "C:/temp/x",
        "\\\\host\\share\\x",
        "/etc/passwd",
        "//host/share/x",
        "a//b",
        "./x",
        "a/./b",
        "line\nbreak",
        "",
    ],
)
def test_resource_names_that_could_leave_the_folder_on_any_platform_are_refused(name):
    from geolens_cli.arcgis_migrate_export import _safe_relative

    assert _safe_relative(name) is None


@pytest.mark.parametrize(
    "name", ["logo.png", "deep/a.bin", "notes/info.json", "a b#c.png"]
)
def test_ordinary_resource_names_are_accepted(name):
    from geolens_cli.arcgis_migrate_export import _safe_relative

    assert _safe_relative(name) is not None


def test_a_backslash_name_is_refused_end_to_end(runner, tmp_path, geolens, install):
    install({f"content/items/{C3}/resources": _resources("..\\..\\escape.txt")})
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    assert not list(tmp_path.rglob("escape.txt"))
    assert any(
        "unsafe" in e for e in _state(plan_file)["items"][C3]["export"]["errors"]
    )


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("big.json", b'{"apiKey": "SECRETKEYVALUE", "pad": "' + b"x" * 200 + b'"}'),
        ("broken.json", b'{"apiKey": "SECRETKEYVALUE", '),
        ("nb.ipynb", b'{"cells": [{"source": "token=SECRETKEYVALUE"'),
    ],
)
def test_json_that_cannot_be_redacted_is_never_saved(
    runner, tmp_path, geolens, install, monkeypatch, name, body
):
    monkeypatch.setattr("geolens_cli.arcgis_migrate_export.JSON_LIMIT", 100)
    install(
        {
            f"content/items/{C3}/resources": _resources(name),
            f"content/items/{C3}/resources/{name}": body,
        }
    )
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    assert not (_export(plan_file, "dashboard", C3) / "resources" / name).exists()
    for path in _export(plan_file).rglob("*"):
        if path.is_file():
            assert b"SECRETKEYVALUE" not in path.read_bytes()
    entry = _state(plan_file)["items"][C3]
    assert entry["export"]["partial"] is True
    assert any("can't be redacted" in e for e in entry["export"]["errors"])


def test_oversized_json_data_is_not_kept_raw(
    runner, tmp_path, geolens, install, monkeypatch
):
    monkeypatch.setattr("geolens_cli.arcgis_migrate_export.JSON_LIMIT", 100)
    install(
        {
            f"content/items/{C3}/data": b'{"apiKey": "SECRETKEYVALUE", "pad": "'
            + b"x" * 200
            + b'"}'
        }
    )
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    folder = _export(plan_file, "dashboard", C3)
    assert not (folder / "data.json").exists() and not (folder / "data.bin").exists()
    assert _state(plan_file)["items"][C3]["export"]["partial"] is True


def test_generated_files_count_against_the_cap(runner, tmp_path, geolens, install):
    install({f"content/items/{C3}/data": {"rows": ["x" * 100] * 4000}})
    plan_file = _plan(tmp_path)

    result, _ = _migrate(
        runner, plan_file, "--only", C3, "--token", TOKEN, "--export-cap-mb", "1"
    )

    assert result.exit_code == 0, result.output
    folder = _export(plan_file, "dashboard", C3)
    total = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
    assert total <= 1024 * 1024
    assert _state(plan_file)["items"][C3]["export"]["bytes"] == total


def test_a_story_over_the_cap_is_not_saved(
    runner, tmp_path, geolens, install, monkeypatch
):
    data = json.loads((STORY_FIXTURE / "storymap_data.json").read_text())
    install({f"content/items/{C2}/data": data})
    monkeypatch.setattr(
        "geolens_cli.arcgis_migrate_export.render_storymap",
        lambda *args, **kwargs: "x" * (2 * 1024 * 1024),
    )
    plan_file = _plan(tmp_path, rows={C2: {"type": "StoryMap"}})

    result, _ = _migrate(
        runner, plan_file, "--only", C2, "--token", TOKEN, "--export-cap-mb", "1"
    )

    assert result.exit_code == 0, result.output
    assert not (_export(plan_file, "storymap", C2) / "story.md").exists()
    entry = _state(plan_file)["items"][C2]
    assert entry["export"]["partial"] is True and entry["export"]["story"] is False


def _with_preexisting(plan_file: Path, *parts: str) -> Path:
    path = _export(plan_file, *parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("old")
    path.chmod(0o644)
    return path


def test_files_that_already_exist_end_up_private(runner, tmp_path, geolens, install):
    install(
        {
            f"content/items/{C3}/resources": _resources("logo.png"),
            f"content/items/{C3}/resources/logo.png": b"PNG",
        }
    )
    plan_file = _plan(tmp_path)
    folder = ("dashboard", C3)
    old = [
        _with_preexisting(plan_file, *folder, "item.json"),
        _with_preexisting(plan_file, *folder, "data.json"),
        _with_preexisting(plan_file, *folder, "resources", "logo.png"),
        _with_preexisting(plan_file, "INDEX.md"),
    ]

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    for path in old:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path
        assert path.read_text() != "old" or path.read_bytes() != b"old"


def test_a_crash_between_download_and_redaction_leaves_no_file(
    runner, tmp_path, geolens, install, monkeypatch
):
    install(
        {
            f"content/items/{C3}/data": {"apiKey": "SECRETKEYVALUE", "ok": 1},
            f"content/items/{C3}/resources": _resources("notes.json"),
            f"content/items/{C3}/resources/notes.json": {"apiKey": "SECRETKEYVALUE"},
        }
    )
    calls = {"n": 0}
    real = redact_json

    def crash_on_data(value, redactor):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("crash")
        return real(value, redactor)

    monkeypatch.setattr("geolens_cli.arcgis_migrate_export.redact_json", crash_on_data)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 1
    for path in _export(plan_file).rglob("*"):
        if path.is_file():
            assert b"SECRETKEYVALUE" not in path.read_bytes(), path
        assert not path.name.startswith("."), f"temporary file left: {path}"
    assert not (_export(plan_file, "dashboard", C3) / "data.json").exists()


def test_the_download_stage_is_removed_after_a_crash(
    runner, tmp_path, geolens, install, monkeypatch
):
    import tempfile

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    install({f"content/items/{C3}/data": {"ok": 1}})
    monkeypatch.setattr(
        "geolens_cli.arcgis_migrate_export.redact_json",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash")),
    )
    plan_file = _plan(tmp_path)

    _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert list(scratch.iterdir()) == []


def test_the_export_module_writes_files_only_through_the_private_writers():
    import ast

    from geolens_cli import arcgis_migrate_export as module

    tree = ast.parse(Path(module.__file__).read_text())
    forbidden = {"write_text", "write_bytes", "copy", "copyfile", "copy2", "move"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        assert name not in forbidden, f"line {node.lineno}: {name}"
        if name in ("open", "fdopen"):
            mode = next(
                (a.value for a in node.args[1:2] if isinstance(a, ast.Constant)), "r"
            )
            assert not set(str(mode)) & set("wax+"), f"line {node.lineno}: open {mode}"


_SECRET_JSON = '{"apiKey": "SECRETKEYVALUE", "pad": "' + "x" * 200 + '"}'


@pytest.mark.parametrize(
    "body",
    [
        b"\xef\xbb\xbf" + _SECRET_JSON.encode(),
        b" " * 5000 + _SECRET_JSON.encode(),
        _SECRET_JSON.encode("utf-16"),
        _SECRET_JSON.encode("utf-16-le"),
        _SECRET_JSON.encode("utf-32"),
        b"\n\t " * 40 + _SECRET_JSON.encode(),
    ],
    ids=["utf8-bom", "long-whitespace", "utf16-bom", "utf16-le", "utf32", "mixed"],
)
def test_json_in_any_encoding_is_not_copied_raw(
    runner, tmp_path, geolens, install, monkeypatch, body
):
    monkeypatch.setattr("geolens_cli.arcgis_migrate_export.JSON_LIMIT", 100)
    install(
        {
            f"content/items/{C3}/resources": _resources("blob"),
            f"content/items/{C3}/resources/blob": body,
        }
    )
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    assert not (_export(plan_file, "dashboard", C3) / "resources" / "blob").exists()
    assert _state(plan_file)["items"][C3]["export"]["partial"] is True


def test_story_index_and_errors_are_fully_scrubbed(runner, tmp_path, geolens, install):
    data = json.loads((STORY_FIXTURE / "storymap_data.json").read_text())
    data["nodes"]["n-intro"]["data"]["text"] = (
        'See <a href="https://x.example/api?apiKey=SECRETKEYVALUE">the api</a>.'
    )
    install(
        {
            f"content/items/{C2}/data": data,
            f"content/items/{C2}/resources": _resources("a?apiKey=SECRETKEYVALUE.png"),
        }
    )
    plan_file = _plan(tmp_path, rows={C2: {"type": "StoryMap"}})

    result, _ = _migrate(runner, plan_file, "--only", C2, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    for path in _export(plan_file).rglob("*"):
        if path.is_file():
            assert b"SECRETKEYVALUE" not in path.read_bytes(), path
    state = (plan_file.parent / "arcgis-migration-state.json").read_text()
    assert "SECRETKEYVALUE" not in state


def test_a_transient_failure_leaves_the_item_failed_and_a_rerun_completes_it(
    runner, tmp_path, geolens, install
):
    portal = install({f"content/items/{C3}/data": (503, {"error": {"code": 503}})})
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)
    assert result.exit_code == 1
    entry = _state(plan_file)["items"][C3]
    assert entry["status"] == "failed" and "rerun to retry" in entry["error"]

    portal.routes[f"content/items/{C3}/data"] = {"title": "x"}
    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    assert _state(plan_file)["items"][C3]["status"] == "done"
    assert (_export(plan_file, "dashboard", C3) / "data.json").exists()


def test_item_json_over_the_cap_is_not_written(runner, tmp_path, geolens, install):
    install(
        {
            f"content/items/{C3}": {
                **json.loads(json.dumps(portal_routes()[f"content/items/{C3}"])),
                "description": "x" * (2 * 1024 * 1024),
            }
        }
    )
    plan_file = _plan(tmp_path)

    result, _ = _migrate(
        runner, plan_file, "--only", C3, "--token", TOKEN, "--export-cap-mb", "1"
    )

    assert result.exit_code == 0, result.output
    assert not (_export(plan_file, "dashboard", C3) / "item.json").exists()
    export = _state(plan_file)["items"][C3]["export"]
    assert export["partial"] is True and export["bytes"] <= 1024 * 1024


def test_a_retried_export_drops_files_the_new_attempt_does_not_make(
    runner, tmp_path, geolens, install
):
    install({f"content/items/{C3}/resources": _resources()})
    plan_file = _plan(tmp_path)
    stale = _export(plan_file, "dashboard", C3, "resources", "old.bin")
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    assert not stale.exists()
    folder = _export(plan_file, "dashboard", C3)
    total = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
    assert _state(plan_file)["items"][C3]["export"]["bytes"] == total


@pytest.mark.parametrize(
    "name",
    [
        "CON",
        "con.txt",
        "NUL",
        "Com1",
        "lpt9.log",
        "a/aux/b",
        "trailing.",
        "trailing ",
        "dir./file",
        "a<b",
        "a|b",
        'a"b',
        "a*b",
        "a?b.png",
    ],
)
def test_names_windows_cannot_store_are_refused(name):
    from geolens_cli.arcgis_migrate_export import _safe_relative

    assert _safe_relative(name) is None


@pytest.mark.parametrize("name", ["console.png", "communal.txt", "a.b.c", "x/y z.png"])
def test_names_that_only_resemble_reserved_ones_are_accepted(name):
    from geolens_cli.arcgis_migrate_export import _safe_relative

    assert _safe_relative(name) is not None


def test_a_resource_name_carrying_a_credential_never_reaches_a_file_or_a_note(
    runner, tmp_path, geolens, install
):
    token = secrets.token_urlsafe(16)
    names = [f"a.png?token={token}", f"logo-{token}.png", "b.png?apiKey=SECRETKEYVALUE"]
    install(
        {
            f"content/items/{C3}/resources": _resources(*names),
            **{f"content/items/{C3}/resources/{n}": b"PNG" for n in names},
        }
    )
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", token)

    assert result.exit_code == 0, result.output
    for needle in (token, "SECRETKEYVALUE"):
        for path in _export(plan_file).rglob("*"):
            assert needle not in path.name, path
            if path.is_file():
                assert needle.encode() not in path.read_bytes(), path
        state = (plan_file.parent / "arcgis-migration-state.json").read_text()
        assert needle not in state and needle not in result.output
    errors = _state(plan_file)["items"][C3]["export"]["errors"]
    assert len([e for e in errors if "unsafe name" in e]) == 3


def _tree(folder: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(folder)): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def test_a_failed_retry_leaves_the_earlier_bundle_untouched(
    runner, tmp_path, geolens, install
):
    portal = install(
        {
            f"content/items/{C3}/resources": _resources("logo.png"),
            f"content/items/{C3}/resources/logo.png": b"PNG",
        }
    )
    plan_file = _plan(tmp_path)
    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)
    assert result.exit_code == 0, result.output
    folder = _export(plan_file, "dashboard", C3)
    before = _tree(folder)
    assert "resources/logo.png" in before

    state = _state(plan_file)
    state["items"][C3]["status"] = "failed"
    (plan_file.parent / "arcgis-migration-state.json").write_text(json.dumps(state))
    portal.routes[f"content/items/{C3}/data"] = (503, {"error": {"code": 503}})
    portal.routes[f"content/items/{C3}/resources"] = _resources()
    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 1
    assert _tree(folder) == before
    assert not [p for p in folder.parent.iterdir() if p.name.startswith(".")]

    portal.routes[f"content/items/{C3}/data"] = {"title": "new"}
    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)
    assert result.exit_code == 0, result.output
    assert "resources/logo.png" not in _tree(folder)


def test_a_swap_a_killed_run_left_half_done_is_recovered(
    runner, tmp_path, geolens, install
):
    install()
    plan_file = _plan(tmp_path)
    parent = _export(plan_file, "dashboard")
    parent.mkdir(parents=True)
    old = parent / f".{C3}.old-1"
    old.mkdir()
    (old / "item.json").write_text("{}")
    leftover = parent / f".{C3}.new-x"
    leftover.mkdir()
    (leftover / "junk").write_text("x")
    from geolens_cli.arcgis_migrate_export import _recover_leftovers

    _recover_leftovers(parent / C3)

    assert (parent / C3 / "item.json").read_text() == "{}"
    assert not leftover.exists() and not old.exists()


def test_a_local_write_error_fails_only_that_item(
    runner, tmp_path, geolens, install, monkeypatch
):
    install()

    def full_disk(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(
        "geolens_cli.arcgis_migrate_export.shutil.rmtree", lambda *a, **k: None
    )
    monkeypatch.setattr("geolens_cli.arcgis_migrate_export._redacted_text", full_disk)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 1
    entry = _state(plan_file)["items"][C3]
    assert entry["status"] == "failed" and "No space left" in entry["error"]


def test_a_resource_over_the_remaining_budget_does_not_stop_the_smaller_ones(
    runner, tmp_path, geolens, install
):
    install(
        {
            f"content/items/{C3}/resources": _resources("big.bin", "small.bin"),
            f"content/items/{C3}/resources/big.bin": b"x" * (2 * 1024 * 1024),
            f"content/items/{C3}/resources/small.bin": b"ok",
        }
    )
    plan_file = _plan(tmp_path)

    result, _ = _migrate(
        runner, plan_file, "--only", C3, "--token", TOKEN, "--export-cap-mb", "1"
    )

    assert result.exit_code == 0, result.output
    folder = _export(plan_file, "dashboard", C3) / "resources"
    assert not (folder / "big.bin").exists()
    assert (folder / "small.bin").read_bytes() == b"ok"
    assert _state(plan_file)["items"][C3]["export"]["partial"] is True


@pytest.mark.parametrize("step", ["_private_dirs", "_recover_leftovers", "_swap_in"])
def test_a_local_error_in_setup_or_the_swap_fails_only_that_item(
    runner, tmp_path, geolens, install, monkeypatch, step
):
    install()

    def broken(*args, **kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(f"geolens_cli.arcgis_migrate_export.{step}", broken)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 1
    entry = _state(plan_file)["items"][C3]
    assert entry["status"] == "failed" and "Permission denied" in entry["error"]
    assert not [p for p in _export(plan_file).rglob(f".{C3}.new-*") if p.exists()]


def test_a_failed_retry_keeps_the_earlier_exports_metadata(
    runner, tmp_path, geolens, install
):
    portal = install(
        {
            f"content/items/{C3}/resources": _resources("logo.png"),
            f"content/items/{C3}/resources/logo.png": b"PNG",
        }
    )
    plan_file = _plan(tmp_path)
    _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)
    before = _state(plan_file)["items"][C3]["export"]
    state = _state(plan_file)
    state["items"][C3]["status"] = "failed"
    (plan_file.parent / "arcgis-migration-state.json").write_text(json.dumps(state))
    portal.routes[f"content/items/{C3}/data"] = (503, {"error": {"code": 503}})
    portal.routes[f"content/items/{C3}/resources"] = _resources()

    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 1
    assert _state(plan_file)["items"][C3]["export"] == before


def test_a_failed_swap_puts_the_kept_bundle_back(tmp_path, monkeypatch):
    from geolens_cli.arcgis_migrate_export import _swap_in

    folder = tmp_path / "item"
    folder.mkdir()
    (folder / "item.json").write_text("old")
    build = tmp_path / ".item.new-1"
    build.mkdir()
    real = Path.rename

    def failing(self, target):
        if self == build:
            raise OSError(13, "Permission denied")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", failing)

    with pytest.raises(OSError):
        _swap_in(build, folder)

    assert (folder / "item.json").read_text() == "old"
    assert not [p for p in tmp_path.iterdir() if ".old-" in p.name]


def test_story_links_only_images_that_were_saved(runner, tmp_path, geolens, install):
    data = json.loads((STORY_FIXTURE / "storymap_data.json").read_text())
    install(
        {
            f"content/items/{C2}/data": data,
            f"content/items/{C2}/resources": _resources("cover photo.jpg?token=abc"),
        }
    )
    plan_file = _plan(tmp_path, rows={C2: {"type": "StoryMap"}})

    result, _ = _migrate(runner, plan_file, "--only", C2, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    text = (_export(plan_file, "storymap", C2) / "story.md").read_text()
    assert "![" not in text and "image not saved in the export" in text


def test_fallback_item_links_start_from_the_portal_root(
    runner, tmp_path, geolens, install
):
    data = json.loads((STORY_FIXTURE / "storymap_data.json").read_text())
    install({f"content/items/{C2}/data": data})
    plan_file = _plan(tmp_path, rows={C2: {"type": "StoryMap"}})
    plan = json.loads(plan_file.read_text())
    plan["portal"]["url"] += "/home"
    plan_file.write_text(json.dumps(plan))
    inventory = plan_file.parent / "arcgis-inventory.json"
    report = json.loads(inventory.read_text())
    report["portal"]["url"] = plan["portal"]["url"]
    inventory.write_text(json.dumps(report))

    result, _ = _migrate(runner, plan_file, "--only", C2)

    assert result.exit_code == 0, result.output
    text = (_export(plan_file, "storymap", C2) / "story.md").read_text()
    assert "/home/home/" not in text and "/home/item.html?id=" in text


def test_a_swap_whose_restore_also_fails_keeps_both_errors_and_the_backup(
    tmp_path, monkeypatch
):
    from geolens_cli.arcgis_migrate_export import _swap_in

    folder = tmp_path / "item"
    folder.mkdir()
    (folder / "item.json").write_text("old")
    build = tmp_path / ".item.new-1"
    build.mkdir()
    real = Path.rename
    state = {"moved": False}

    def failing(self, target):
        if self == folder and not state["moved"]:
            state["moved"] = True
            return real(self, target)
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(Path, "rename", failing)

    with pytest.raises(OSError) as raised:
        _swap_in(build, folder)

    message = str(raised.value)
    assert "Permission denied" in message and "could not be moved back" in message
    backup = next(p for p in tmp_path.iterdir() if ".old-" in p.name)
    assert str(backup) in message and (backup / "item.json").read_text() == "old"


def test_recovery_never_deletes_the_only_copy_of_a_bundle(tmp_path):
    from geolens_cli.arcgis_migrate_export import _recover_leftovers

    folder = tmp_path / C3
    folder.mkdir()
    backup = tmp_path / f".{C3}.old-1"
    backup.mkdir()
    (backup / "item.json").write_text("only copy")
    trash = tmp_path / f".{C3}.trash-1"
    trash.mkdir()

    _recover_leftovers(folder)

    assert (backup / "item.json").read_text() == "only copy"
    assert not trash.exists()


def _exported_c3(runner, tmp_path, install, **routes):
    portal = install({f"content/items/{C3}/resources": _resources(), **routes})
    plan_file = _plan(tmp_path)
    result, _ = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)
    assert result.exit_code == 0, result.output
    return portal, plan_file


def _change_in_portal(portal, **fields) -> None:
    item = portal.routes[f"content/items/{C3}"]
    portal.routes[f"content/items/{C3}"] = {
        **item,
        "modified": item["modified"] + 60_000,
        **fields,
    }


def test_a_rerun_leaves_an_unchanged_bundle_alone(runner, tmp_path, geolens, install):
    portal, plan_file = _exported_c3(runner, tmp_path, install)
    assert (
        _state(plan_file)["items"][C3]["export"]["modified"]
        == (portal.routes[f"content/items/{C3}"]["modified"])
    )
    downloads = len(portal.requests_to(f"content/items/{C3}/data"))

    result, payload = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    assert payload["refreshed"] == [C3] and payload["not_up_to_date"] == {}
    assert len(portal.requests_to(f"content/items/{C3}/data")) == downloads


@pytest.mark.parametrize("old_state", [False, True])
def test_a_bundle_the_portal_changed_since_is_exported_again(
    runner, tmp_path, geolens, install, old_state
):
    portal, plan_file = _exported_c3(runner, tmp_path, install)
    portal.routes[f"content/items/{C3}/data"] = {"title": "new"}
    if old_state:
        # A state file from before the change time was recorded.
        state = _state(plan_file)
        del state["items"][C3]["export"]["modified"]
        (plan_file.parent / "arcgis-migration-state.json").write_text(json.dumps(state))
    else:
        _change_in_portal(portal)

    result, payload = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    assert payload["not_up_to_date"] == {}
    folder = _export(plan_file, "dashboard", C3)
    assert json.loads((folder / "data.json").read_text()) == {"title": "new"}
    recorded = _state(plan_file)["items"][C3]["export"]["modified"]
    assert recorded == portal.routes[f"content/items/{C3}"]["modified"]


def test_a_failed_export_of_a_changed_item_keeps_the_bundle_and_blocks_cutover(
    runner, tmp_path, geolens, install
):
    portal, plan_file = _exported_c3(runner, tmp_path, install)
    folder = _export(plan_file, "dashboard", C3)
    before = _tree(folder)
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] != C3:
            item["action"] = "skip"
    plan_file.write_text(json.dumps(plan))
    _change_in_portal(portal)
    portal.routes[f"content/items/{C3}/data"] = (503, {"error": {"code": 503}})

    result, payload = _migrate(runner, plan_file, "--token", TOKEN, "--cutover")

    assert result.exit_code == 1
    [reason] = payload["not_up_to_date"][C3]
    assert "exporting it again failed" in reason
    assert _tree(folder) == before
    assert payload["cutover"]["refused"] == ["unfinished-items"]


@pytest.mark.parametrize(
    "answer", [(500, {"error": {"code": 500}}), {"id": C3, "title": "no date"}]
)
def test_a_bundle_whose_item_change_time_cant_be_read_is_reported(
    runner, tmp_path, geolens, install, answer
):
    portal, plan_file = _exported_c3(runner, tmp_path, install)
    portal.routes[f"content/items/{C3}"] = answer

    result, payload = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 1
    assert payload["not_up_to_date"][C3]


@pytest.mark.parametrize("left", ["old", "nothing"])
def test_a_bundle_missing_from_its_path_is_put_back_or_exported_again(
    runner, tmp_path, geolens, install, left
):
    portal, plan_file = _exported_c3(runner, tmp_path, install)
    folder = _export(plan_file, "dashboard", C3)
    before = _tree(folder)
    if left == "old":
        # A run killed inside the swap, after the old bundle moved aside.
        folder.rename(folder.with_name(f".{C3}.old-4242"))
    else:
        shutil.rmtree(folder)

    result, payload = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    assert payload["not_up_to_date"] == {}
    assert _tree(folder) == before


def test_a_missing_bundle_that_cant_be_exported_again_blocks_cutover(
    runner, tmp_path, geolens, install
):
    portal, plan_file = _exported_c3(runner, tmp_path, install)
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] != C3:
            item["action"] = "skip"
    plan_file.write_text(json.dumps(plan))
    shutil.rmtree(_export(plan_file, "dashboard", C3))
    portal.routes[f"content/items/{C3}/data"] = (503, {"error": {"code": 503}})

    result, payload = _migrate(runner, plan_file, "--token", TOKEN, "--cutover")

    assert result.exit_code == 1
    [reason] = payload["not_up_to_date"][C3]
    assert reason.startswith("its bundle is missing")
    assert payload["cutover"]["refused"] == ["unfinished-items"]


def test_a_partial_export_bundle_blocks_cutover(runner, tmp_path, geolens, install):
    install(
        {
            f"content/items/{C3}/resources": _resources("a.bin", "b.bin"),
            f"content/items/{C3}/resources/a.bin": b"x" * 600_000,
            f"content/items/{C3}/resources/b.bin": b"y" * 600_000,
        }
    )
    plan_file = _plan(tmp_path)
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] != C3:
            item["action"] = "skip"
    plan_file.write_text(json.dumps(plan))
    args = ("--token", TOKEN, "--export-cap-mb", "1")
    _migrate(runner, plan_file, *args)
    assert _state(plan_file)["items"][C3]["export"]["partial"] is True

    result, payload = _migrate(runner, plan_file, *args, "--cutover")

    assert result.exit_code == 1
    assert payload["cutover"]["refused"] == ["unfinished-items"]
    [check] = payload["cutover"]["checks"]
    [found] = check["items"]
    assert found["item"] == C3
    assert found["reason"].startswith("its export bundle is missing files: ")


def test_an_export_with_no_portal_connection_is_reported():
    from types import SimpleNamespace

    from geolens_cli.arcgis_migrate_export import refresh_export
    from geolens_cli.arcgis_migrate_state import ItemState

    ctx = SimpleNamespace(portal=None)
    item = {"id": C3, "type": "Dashboard"}

    assert refresh_export(ctx, item, ItemState(status="done")) == [
        "the run can't read this item from the portal to check it for changes"
    ]


def test_an_export_whose_change_time_cant_be_read_blocks_cutover(
    runner, tmp_path, geolens, install
):
    portal, plan_file = _exported_c3(runner, tmp_path, install)
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] != C3:
            item["action"] = "skip"
    plan_file.write_text(json.dumps(plan))
    portal.routes[f"content/items/{C3}"] = {"id": C3, "title": "no date"}

    result, payload = _migrate(runner, plan_file, "--token", TOKEN, "--cutover")

    assert result.exit_code == 1
    [reason] = payload["not_up_to_date"][C3]
    assert "doesn't say when the item last changed" in reason
    assert payload["cutover"]["refused"] == ["unfinished-items"]


@pytest.mark.parametrize(
    "damage", ["deleted", "truncated", "same_length", "no_file_list", "sizes_only"]
)
def test_a_bundle_missing_a_file_it_recorded_is_exported_again(
    runner, tmp_path, geolens, install, damage
):
    portal, plan_file = _exported_c3(runner, tmp_path, install)
    folder = _export(plan_file, "dashboard", C3)
    before = _tree(folder)
    if damage == "deleted":
        (folder / "item.json").unlink()
    elif damage == "truncated":
        (folder / "data.json").write_text("{}")
    elif damage == "same_length":
        data = (folder / "data.json").read_bytes()
        (folder / "data.json").write_bytes(b"X" * len(data))
    elif damage == "sizes_only":
        # A record from before the digests were kept.
        state = _state(plan_file)
        recorded = state["items"][C3]["export"]["files"]
        state["items"][C3]["export"]["files"] = {
            name: entry["size"] for name, entry in recorded.items()
        }
        (plan_file.parent / "arcgis-migration-state.json").write_text(json.dumps(state))
    else:
        # A record from before the file list was kept.
        state = _state(plan_file)
        del state["items"][C3]["export"]["files"]
        (plan_file.parent / "arcgis-migration-state.json").write_text(json.dumps(state))
    downloads = len(portal.requests_to(f"content/items/{C3}/data"))

    result, payload = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    assert payload["not_up_to_date"] == {}
    assert len(portal.requests_to(f"content/items/{C3}/data")) == downloads + 1
    assert _tree(folder) == before
    assert set(_state(plan_file)["items"][C3]["export"]["files"]) == set(before)


def test_a_bundle_missing_a_file_that_cant_be_exported_again_blocks_cutover(
    runner, tmp_path, geolens, install
):
    portal, plan_file = _exported_c3(runner, tmp_path, install)
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] != C3:
            item["action"] = "skip"
    plan_file.write_text(json.dumps(plan))
    (_export(plan_file, "dashboard", C3) / "item.json").unlink()
    portal.routes[f"content/items/{C3}/data"] = (503, {"error": {"code": 503}})

    result, payload = _migrate(runner, plan_file, "--token", TOKEN, "--cutover")

    assert result.exit_code == 1
    [reason] = payload["not_up_to_date"][C3]
    assert reason.startswith("its bundle is missing")
    assert payload["cutover"]["refused"] == ["unfinished-items"]


def test_a_bundle_recorded_with_no_files_is_exported_again(
    runner, tmp_path, geolens, install
):
    portal, plan_file = _exported_c3(runner, tmp_path, install)
    folder = _export(plan_file, "dashboard", C3)
    # An empty folder matches an empty record, but proves nothing was saved.
    shutil.rmtree(folder)
    folder.mkdir()
    state = _state(plan_file)
    state["items"][C3]["export"]["files"] = {}
    (plan_file.parent / "arcgis-migration-state.json").write_text(json.dumps(state))
    downloads = len(portal.requests_to(f"content/items/{C3}/data"))

    result, payload = _migrate(runner, plan_file, "--only", C3, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    assert len(portal.requests_to(f"content/items/{C3}/data")) == downloads + 1
    assert (folder / "item.json").exists()


@pytest.mark.parametrize(
    ("item_type", "name", "expected"),
    [
        ("CSV", None, "data.csv"),
        ("PDF", "Report.PDF", "data.pdf"),
        ("Image Service", None, "data.bin"),
        ("Image", None, "data.bin"),
        ("Microsoft Excel", None, "data.bin"),
        ("CSV", "../../etc/passwd", "data.csv"),
        ("Feature Service", "notes.tar.gz", "data.gz"),
        ("Image Service", "a/b\\evil.sh;rm", "data.bin"),
        ("Image Service", "x.json", "data.bin"),
        ("Image Service", "x.waytoolongext", "data.bin"),
    ],
)
def test_a_raw_file_keeps_its_type_and_never_a_portal_path(item_type, name, expected):
    full = {"name": name} if name is not None else {}

    assert export_module._raw_name({"type": item_type}, full) == expected


@pytest.mark.parametrize(
    ("action", "defaults", "expected"),
    [
        ("export_only", {"action": "export_only"}, "Source file of Layer"),
        ("export_only", None, "Source file of Layer"),
        ("import_file", {"action": "export_only"}, "No equivalent in GeoLens."),
        ("import_file", {"action": "import_file"}, "Source file of Layer"),
    ],
)
def test_the_hosted_layer_note_follows_the_items_current_action(
    tmp_path, action, defaults, expected
):
    state = MigrationState(tmp_path / "s.json", "p", "i", str, persist=False)
    item = {"id": D1, "type": "CSV", "action": action, "superseded_by": C1}
    if defaults is not None:
        item["defaults"] = defaults
    plan = {"items": [item, {"id": C1, "title": "Layer"}]}

    assert export_module.item_replacement(item, plan, state).startswith(
        expected
    )
