"""`geolens arcgis migrate`: the export bundle for items GeoLens can't host."""

from __future__ import annotations

import json
import secrets
import stat
from pathlib import Path

import pytest

from geolens_cli import arcgis_migrate as migrate

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


def test_a_service_item_saves_only_its_json(runner, tmp_path, geolens, install):
    portal = install()
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D1, "--token", TOKEN)

    assert result.exit_code == 0, result.output
    folder = _export(plan_file, "image-service", D1)
    assert sorted(p.name for p in folder.iterdir()) == ["item.json"]
    assert not portal.requests_to(f"content/items/{D1}/data")


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


def test_a_story_links_to_the_geolens_map_made_from_its_web_map(
    runner, tmp_path, geolens, install
):
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
    assert "https://geolens.example.org/maps/m-123" in text


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
