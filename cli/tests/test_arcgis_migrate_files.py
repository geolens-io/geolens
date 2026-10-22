"""`geolens arcgis migrate`: the import_file action against a fake portal and GeoLens."""

from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from geolens_cli import arcgis_migrate as migrate

from . import test_arcgis_migrate_layers as layers
from .arcgis_fake import D3, PORTAL, FakePortal, item_data_path, portal_routes
from .test_arcgis_migrate_layers import (
    _migrate,
    _problem,
    _state,
    _uuid,
    _write_plan,
    dataset_id,
)

geolens = layers.geolens
quick = layers.quick

PUBLIC = {"sharing": {"access": "public", "groups": []}}
CSV = b"name,lat,lon\nA,1.0,2.0\nB,3.0,4.0\n"
UPLOAD = "POST /ingest/upload"


class FakeFiles:
    """Upload, preview, commit and job routes for file imports."""

    def __init__(self, fake, *, layer_names: list[str] | None = None) -> None:
        self.fake = fake
        self.layer_names = layer_names
        self.uploads: list[bytes] = []
        self.commits: dict[str, dict] = {}
        self.fan_outs: list[dict] = []
        self.upload_refusal: tuple | None = None
        self.helper = layers.FakeImport(fake, [])
        fake.routes[UPLOAD] = self.upload

    def upload(self, seen):
        if self.upload_refusal:
            return self.upload_refusal
        self.uploads.append(seen.body)
        job = _uuid("0f", f"{len(self.uploads):02d}")
        self.fake.routes[f"POST /ingest/preview/{job}"] = lambda s, j=job: self.preview(
            j
        )
        self.fake.routes[f"POST /ingest/commit/{job}"] = lambda s, j=job: self.commit(
            j, s
        )
        self.fake.routes[f"POST /ingest/commit-fan-out/{job}"] = (
            lambda s, j=job: self.fan_out(j, s)
        )
        self.fake.routes[f"GET /jobs/{job}"] = lambda s, j=job: self.job(j)
        return (201, {"job_id": job, "message": "ok", "status": "pending"})

    def preview(self, job: str):
        body = {
            "job_id": job,
            "source_filename": "f",
            "columns": [],
            "crs": 4326,
            "geometry_type": "Point",
            "feature_count": 2,
            "sample_rows": [],
            "layer_name": "f",
        }
        if self.layer_names:
            body["layers"] = [{"name": n} for n in self.layer_names]
        return body

    def commit(self, job: str, seen):
        if job in self.commits:
            return (400, _problem(400, "Job already processed"))
        self.commits[job] = seen.json()
        self.helper._serve_dataset(dataset_id(job))
        return (202, {"job_id": job, "status": "pending", "message": "queued"})

    def fan_out(self, job: str, seen):
        self.fan_outs.append(seen.json())
        results = []
        for layer in seen.json()["layers"]:
            name = layer["layer_name"]
            self.helper._serve_dataset(dataset_id(name))
            results.append(
                {
                    "layer_name": name,
                    "status": "queued",
                    "new_job_id": _uuid("0e", name),
                    "dataset_id": dataset_id(name),
                }
            )
        return (202, {"fan_out_id": job, "results": results})

    def job(self, job: str) -> dict:
        return self.helper.job(job, job, None)


def _limit_settings(megabytes: int) -> dict:
    setting = {
        "key": "upload_max_size_mb",
        "value": megabytes,
        "source": "default",
        "label": "Upload limit",
    }
    return {"env_only": False, "tabs": {"uploads": [setting]}}


@pytest.fixture(autouse=True)
def private_tempdir(tmp_path, monkeypatch):
    """Downloads go to a directory of this test, which must be empty at the end."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    yield scratch
    assert list(scratch.iterdir()) == []


@pytest.fixture
def portal(monkeypatch) -> FakePortal:
    portal = FakePortal(portal_routes({item_data_path(D3): CSV}))
    monkeypatch.setattr(migrate, "build_opener", lambda: portal)
    return portal


def _plan(tmp_path: Path, *, public: bool = True, **row: object) -> Path:
    rows = {D3: {**(PUBLIC if public else {}), **row}}
    return _write_plan(tmp_path, rows=rows)


def test_a_public_csv_is_downloaded_uploaded_and_committed(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert files.uploads and CSV in files.uploads[0]
    [job] = files.commits
    assert files.commits[job]["title"] == "Inspections"
    entry = _state(plan_file)["items"][D3]
    assert entry["status"] == "done"
    assert entry["dataset_ids"] == [dataset_id(job)]
    assert entry["layer_jobs"] == {}
    # A public file is downloaded without a credential, from the portal only.
    [request] = portal.requests_to(item_data_path(D3))
    assert "x-esri-authorization" not in request.headers
    assert {urlsplit(s.url).hostname for s in portal.seen} == {
        urlsplit(PORTAL).hostname
    }


def test_a_private_file_is_downloaded_with_the_token(runner, tmp_path, geolens, portal):
    FakeFiles(geolens)
    plan_file = _plan(tmp_path, public=False)
    token = secrets.token_urlsafe(16)

    result, _ = _migrate(runner, plan_file, "--only", D3, "--token", token)

    assert result.exit_code == 0, result.output
    [request] = portal.requests_to(item_data_path(D3))
    assert request.headers["x-esri-authorization"] == f"Bearer {token}"
    assert token not in result.output


def test_a_csv_without_a_geometry_column_is_noted_as_a_table(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens)
    preview = files.preview
    files.preview = lambda job: {**preview(job), "geometry_type": None}
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert "imported as a table" in _state(plan_file)["items"][D3]["notes"][0]


def test_detected_coordinate_columns_ride_the_commit(runner, tmp_path, geolens, portal):
    files = FakeFiles(geolens)
    preview = files.preview
    files.preview = lambda job: {
        **preview(job),
        "geometry_type": None,
        "detected_geometry_columns": {"x_column": "lon", "y_column": "lat"},
    }
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    [body] = files.commits.values()
    assert body["x_column"] == "lon" and body["y_column"] == "lat"


def test_a_file_over_the_instance_limit_is_skipped_with_its_size(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens)
    geolens.routes["GET /settings/all/"] = _limit_settings(1)
    plan_file = _plan(tmp_path, size_bytes=5 * 1024 * 1024)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][D3]
    assert entry["status"] == "skipped"
    assert "5.0 MB" in entry["notes"][0] and "1.0 MB" in entry["notes"][0]
    assert not files.uploads and not portal.requests_to(item_data_path(D3))


def test_a_download_over_the_limit_is_skipped(runner, tmp_path, geolens, portal):
    files = FakeFiles(geolens)
    geolens.routes["GET /settings/all/"] = _limit_settings(1)
    portal.routes[item_data_path(D3)] = b"x" * (2 * 1024 * 1024)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][D3]
    assert entry["status"] == "skipped" and "upload limit" in entry["notes"][0]
    assert not files.uploads


def test_a_quota_refusal_fails_the_item_with_the_quota(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens)
    files.upload_refusal = (
        413,
        _problem(413, "Storage quota exceeded: used 9 of 10 bytes (adding 5 bytes)"),
    )
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    entry = _state(plan_file)["items"][D3]
    assert entry["status"] == "failed" and "Storage quota exceeded" in entry["error"]


def test_a_multi_layer_file_becomes_one_dataset_per_layer(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens, layer_names=["Roads", "Parcels"])
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    [request] = files.fan_outs
    assert [layer["layer_name"] for layer in request["layers"]] == ["Roads", "Parcels"]
    assert not files.commits
    entry = _state(plan_file)["items"][D3]
    assert entry["dataset_ids"] == [dataset_id("Roads"), dataset_id("Parcels")]


def test_a_rerun_after_a_lost_commit_answer_does_not_upload_again(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens)
    commit = files.commit
    broken = {"on": True}

    def flaky(job, seen):
        reply = commit(job, seen)
        return (500, _problem(500, "gateway lost")) if broken["on"] else reply

    files.commit = flaky
    plan_file = _plan(tmp_path)
    result, _ = _migrate(runner, plan_file, "--only", D3)
    assert result.exit_code == 1
    assert _state(plan_file)["items"][D3]["layer_jobs"]

    broken["on"] = False
    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert len(files.uploads) == 1
    assert _state(plan_file)["items"][D3]["status"] == "done"


def test_a_feature_collection_is_skipped_with_a_note(runner, tmp_path, geolens, portal):
    files = FakeFiles(geolens)
    plan_file = _plan(tmp_path, type="Feature Collection")
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == D3:
            item["type"] = "Feature Collection"
    plan_file.write_text(json.dumps(plan))

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][D3]
    assert entry["status"] == "skipped" and "ArcGIS JSON" in entry["notes"][0]
    assert not files.uploads


def test_a_portal_error_envelope_in_a_200_body_fails_the_item(
    runner, tmp_path, geolens, portal
):
    FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = {
        "error": {"code": 403, "message": "You do not have permission"}
    }
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert "permission" in _state(plan_file)["items"][D3]["error"]


def test_a_rejected_token_stops_the_run_and_is_redacted(
    runner, tmp_path, geolens, portal
):
    FakeFiles(geolens)
    token = secrets.token_urlsafe(16)
    portal.routes[item_data_path(D3)] = (498, {"error": {"code": 498}})
    plan_file = _plan(tmp_path, public=False)

    result, payload = _migrate(runner, plan_file, "--only", D3, "--token", token)

    assert result.exit_code == 1
    assert "fresh token" in payload["stopped"]
    raw = (plan_file.parent / "arcgis-migration-state.json").read_text()
    assert token not in raw and token not in result.output


def test_the_temporary_download_directory_is_removed(
    runner, tmp_path, geolens, portal, monkeypatch
):
    FakeFiles(geolens)
    seen: list[Path] = []
    real = migrate_files_upload()

    def spy(ctx, path, title):
        seen.append(path)
        return real(ctx, path, title)

    monkeypatch.setattr("geolens_cli.arcgis_migrate_files._upload", spy)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert seen and not seen[0].exists() and not seen[0].parent.exists()


def migrate_files_upload():
    from geolens_cli import arcgis_migrate_files

    return arcgis_migrate_files._upload


def test_a_portal_ignoring_the_token_header_gets_it_as_a_form_field(
    runner, tmp_path, geolens, portal
):
    FakeFiles(geolens)
    token = secrets.token_urlsafe(16)
    portal.routes[item_data_path(D3)] = [(499, {"error": {"code": 499}}), CSV]
    plan_file = _plan(tmp_path, public=False)

    result, _ = _migrate(runner, plan_file, "--only", D3, "--token", token)

    assert result.exit_code == 0, result.output
    first, second = portal.requests_to(item_data_path(D3))
    assert first.method == "GET" and second.method == "POST"
    assert second.params["token"] == token
    assert "x-esri-authorization" not in second.headers


def test_a_password_token_is_renewed_when_the_download_is_rejected(
    runner, tmp_path, geolens, portal
):
    FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = [(498, {"error": {"code": 498}}), CSV]
    plan_file = _plan(tmp_path, public=False)

    result, _ = _migrate(
        runner,
        plan_file,
        "--only",
        D3,
        "--username",
        "gis_admin",
        env={"ARCGIS_PASSWORD": secrets.token_urlsafe(8)},
    )

    assert result.exit_code == 0, result.output
    assert len(portal.requests_to("generateToken")) == 2
    assert len(portal.requests_to(item_data_path(D3))) == 2


def test_a_redirect_from_the_portal_fails_the_item(runner, tmp_path, geolens, portal):
    files = FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = (302, b"", {"Location": "https://evil.example"})
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert "redirect" in _state(plan_file)["items"][D3]["error"]
    assert not files.uploads
    assert {urlsplit(s.url).hostname for s in portal.seen} == {
        urlsplit(PORTAL).hostname
    }


def test_the_temporary_directory_is_removed_after_a_failed_upload(
    runner, tmp_path, geolens, portal, monkeypatch
):
    files = FakeFiles(geolens)
    files.upload_refusal = (413, _problem(413, "Storage quota exceeded"))
    seen: list[Path] = []
    real = migrate_files_upload()

    def spy(ctx, path, title):
        seen.append(path)
        return real(ctx, path, title)

    monkeypatch.setattr("geolens_cli.arcgis_migrate_files._upload", spy)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert seen and not seen[0].parent.exists()


def test_a_layer_geolens_cannot_queue_is_noted_and_the_rest_import(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens, layer_names=["Roads", "Parcels"])
    fan_out = files.fan_out

    def partial(job, seen):
        status, body = fan_out(job, seen)
        body["results"][1].update(status="failed", dataset_id=None, error="bad layer")
        return status, body

    files.fan_out = partial
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][D3]
    assert entry["dataset_ids"] == [dataset_id("Roads")]
    assert "Parcels: bad layer" in entry["notes"][-1]
