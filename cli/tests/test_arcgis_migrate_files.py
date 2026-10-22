"""`geolens arcgis migrate`: the import_file action against a fake portal and GeoLens."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from geolens_cli import arcgis_migrate as migrate

from . import arcgis_fake
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
            child = _uuid("0e", name)
            # The dataset appears when the queued job runs, as on the server.
            self.fake.routes[f"GET /jobs/{child}"] = (
                lambda s, c=child, n=name: self.helper.job(c, n, None)
            )
            results.append(
                {
                    "layer_name": name,
                    "status": "queued",
                    "new_job_id": child,
                    "dataset_id": None,
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
        body["results"][1].update(status="failed", new_job_id=None, error="bad layer")
        return status, body

    files.fan_out = partial
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][D3]
    assert entry["dataset_ids"] == [dataset_id("Roads")]
    assert "Parcels: bad layer" in entry["notes"][-1]


def test_a_private_feature_collection_needs_no_portal_credential(
    runner, tmp_path, geolens, portal
):
    FakeFiles(geolens)
    plan_file = _plan(tmp_path, public=False)
    plan = json.loads(plan_file.read_text())
    for item in plan["items"]:
        if item["id"] == D3:
            item["type"] = "Feature Collection"
    plan_file.write_text(json.dumps(plan))

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert _state(plan_file)["items"][D3]["status"] == "skipped"


def test_a_geojson_that_starts_like_an_error_envelope_is_saved_whole(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens)
    body = (
        b'{"error": "kept", "type": "FeatureCollection", "features": []}' + b" " * 70000
    )
    portal.routes[item_data_path(D3)] = body
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert body in files.uploads[0]


def test_a_fan_out_interrupted_while_waiting_does_not_upload_again(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens, layer_names=["Roads", "Parcels"])
    plan_file = _plan(tmp_path)
    child = _uuid("0e", "Parcels")
    _migrate(runner, plan_file, "--only", D3)
    state = _state(plan_file)
    entry = state["items"][D3]
    entry.update(
        status="failed", layer_datasets={}, layer_jobs={"layer:Parcels": child}
    )
    (plan_file.parent / "arcgis-migration-state.json").write_text(json.dumps(state))

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert len(files.uploads) == 1
    assert _state(plan_file)["items"][D3]["dataset_ids"] == [dataset_id("Parcels")]


def test_a_public_file_is_downloaded_with_a_supplied_token(
    runner, tmp_path, geolens, portal
):
    FakeFiles(geolens)
    token = secrets.token_urlsafe(16)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3, "--token", token)

    assert result.exit_code == 0, result.output
    [request] = portal.requests_to(item_data_path(D3))
    assert request.headers["x-esri-authorization"] == f"Bearer {token}"


def test_a_file_with_more_layers_than_one_fan_out_takes_is_skipped(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens, layer_names=[f"L{n}" for n in range(51)])
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][D3]
    assert entry["status"] == "skipped" and "51 layers" in entry["notes"][0]
    assert not files.fan_outs


def test_a_resumed_partial_fan_out_keeps_its_layer_notes(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens, layer_names=["Roads", "Parcels"])
    fan_out = files.fan_out

    def partial(job, seen):
        status, body = fan_out(job, seen)
        body["results"][1].update(status="failed", new_job_id=None, error="bad layer")
        return status, body

    files.fan_out = partial
    plan_file = _plan(tmp_path)
    _migrate(runner, plan_file, "--only", D3)
    state = _state(plan_file)
    state["items"][D3]["status"] = "failed"
    (plan_file.parent / "arcgis-migration-state.json").write_text(json.dumps(state))

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert len(files.uploads) == 1
    assert "Parcels: bad layer" in _state(plan_file)["items"][D3]["notes"][-1]


def test_a_retry_keeps_the_layer_title_and_note_after_a_failed_target_update(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens, layer_names=["Roads", "Parcels"])
    fan_out = files.fan_out
    roads = f"PATCH /datasets/{dataset_id('Roads')}"
    failing = {"on": True}

    def partial(job, seen):
        status, body = fan_out(job, seen)
        body["results"][1].update(status="failed", new_job_id=None, error="bad layer")
        served = geolens.routes[roads]
        geolens.routes[roads] = lambda s: (
            (500, _problem(500, "database unavailable")) if failing["on"] else served(s)
        )
        return status, body

    files.fan_out = partial
    plan_file = _plan(tmp_path)
    result, _ = _migrate(runner, plan_file, "--only", D3)
    assert result.exit_code == 1

    failing["on"] = False
    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][D3]
    assert "Parcels: bad layer" in entry["notes"][-1]
    titles = [
        s.json()["title"]
        for s in geolens.seen
        if s.method == "PATCH"
        and s.url.endswith(dataset_id("Roads"))
        and "title" in s.json()
    ]
    assert titles[-1] == "Inspections - Roads"


def test_a_child_job_that_fails_while_resuming_is_noted(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens, layer_names=["Roads", "Parcels"])
    plan_file = _plan(tmp_path)
    _migrate(runner, plan_file, "--only", D3)
    state = _state(plan_file)
    entry = state["items"][D3]
    parcels = _uuid("0e", "Parcels")
    roads = _uuid("0e", "Roads")
    entry.update(
        status="failed",
        layer_datasets={},
        layer_jobs={"layer:Roads": roads, "layer:Parcels": parcels},
        notes=[],
    )
    (plan_file.parent / "arcgis-migration-state.json").write_text(json.dumps(state))
    geolens.routes[f"GET /jobs/{parcels}"] = files.helper.job(
        parcels, "Parcels", "boom"
    )

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][D3]
    assert entry["dataset_ids"] == [dataset_id("Roads")]
    assert "boom" in entry["notes"][-1]


def test_a_failed_target_update_on_resume_does_not_lose_the_dataset(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens)
    commit = files.commit
    lost = {"on": True}

    def flaky(job, seen):
        reply = commit(job, seen)
        return (500, _problem(500, "gateway lost")) if lost["on"] else reply

    files.commit = flaky
    plan_file = _plan(tmp_path)
    _migrate(runner, plan_file, "--only", D3)
    lost["on"] = False
    [job] = files.commits
    patch = f"PATCH /datasets/{dataset_id(job)}"
    served = geolens.routes[patch]
    geolens.routes[patch] = (500, _problem(500, "database unavailable"))
    result, _ = _migrate(runner, plan_file, "--only", D3)
    assert result.exit_code == 1
    assert _state(plan_file)["items"][D3]["dataset_ids"] == [dataset_id(job)]

    geolens.routes[patch] = served
    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert len(files.uploads) == 1


def test_an_error_envelope_arriving_in_small_reads_is_still_detected(
    runner, tmp_path, geolens, portal, monkeypatch
):
    files = FakeFiles(geolens)
    monkeypatch.setattr(
        arcgis_fake._Response, "read1", lambda self, size=-1: self._buffer.read1(3)
    )
    portal.routes[item_data_path(D3)] = {
        "error": {"code": 403, "message": "You do not have permission"}
    }
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert "permission" in _state(plan_file)["items"][D3]["error"]
    assert not files.uploads


SIGNED = "X-Amz-Security-Token=SIGNEDSECRET123&X-Amz-Signature=SIGSECRET456&k=PLAINQUERYSECRET"
STORAGE_PATH = "/itemdata/org/file.csv"


def _redirect(location: str) -> tuple:
    return (302, b"", {"Location": location})


def _storage(host: str = "www.arcgis.com", scheme: str = "https") -> str:
    return f"{scheme}://{host}{STORAGE_PATH}?{SIGNED}"


def _assert_no_query_anywhere(plan_file: Path, result) -> None:
    for secret in ("SIGNEDSECRET123", "SIGSECRET456", "PLAINQUERYSECRET"):
        assert secret not in result.output
        for path in plan_file.parent.rglob("arcgis-migration-state.json"):
            assert secret not in path.read_text()


def test_a_download_follows_one_redirect_to_arcgis_storage_without_credentials(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens)
    token = secrets.token_urlsafe(16)
    portal.routes[item_data_path(D3)] = _redirect(_storage())
    portal.routes[STORAGE_PATH] = CSV
    plan_file = _plan(tmp_path, public=False)

    result, _ = _migrate(runner, plan_file, "--only", D3, "--token", token)

    assert result.exit_code == 0, result.output
    assert CSV in files.uploads[0]
    [first] = portal.requests_to(item_data_path(D3))
    [second] = portal.requests_to(STORAGE_PATH)
    assert first.headers["x-esri-authorization"] == f"Bearer {token}"
    assert second.method == "GET" and second.body == ""
    assert not {"x-esri-authorization", "authorization", "cookie", "referer"} & set(
        second.headers
    )
    assert urlsplit(second.url).hostname == "www.arcgis.com"
    _assert_no_query_anywhere(plan_file, result)


@pytest.mark.parametrize("host", ["org.maps.arcgis.com", urlsplit(PORTAL).hostname])
def test_arcgis_subdomains_and_the_portal_host_are_allowed_targets(
    runner, tmp_path, geolens, portal, host
):
    FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = _redirect(_storage(host))
    portal.routes[STORAGE_PATH] = CSV
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "target",
    [
        _storage("evil.example"),
        _storage("evilarcgis.com"),
        _storage("arcgis.com.evil.example"),
        _storage("www.arcgis.com", scheme="http"),
        _storage("user@www.arcgis.com"),
        _storage("www.arcgis.com:8443"),
    ],
)
def test_other_redirect_targets_are_refused_without_naming_the_query(
    runner, tmp_path, geolens, portal, target
):
    files = FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = _redirect(target)
    portal.routes[STORAGE_PATH] = CSV
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert "redirect" in _state(plan_file)["items"][D3]["error"]
    assert not files.uploads
    assert not portal.requests_to(STORAGE_PATH)
    _assert_no_query_anywhere(plan_file, result)


def test_a_second_redirect_is_refused(runner, tmp_path, geolens, portal):
    files = FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = _redirect(_storage())
    portal.routes[STORAGE_PATH] = _redirect(_storage("www.arcgis.com"))
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert len(portal.requests_to(STORAGE_PATH)) == 1
    assert not files.uploads
    _assert_no_query_anywhere(plan_file, result)


def test_a_failure_on_the_storage_hop_does_not_leak_its_query(
    runner, tmp_path, geolens, portal
):
    FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = _redirect(_storage())
    portal.routes[STORAGE_PATH] = (403, b"denied")
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    error = _state(plan_file)["items"][D3]["error"]
    assert error.endswith(f"from www.arcgis.com{STORAGE_PATH}")
    _assert_no_query_anywhere(plan_file, result)


def test_the_size_limit_applies_to_a_redirected_body(runner, tmp_path, geolens, portal):
    files = FakeFiles(geolens)
    geolens.routes["GET /settings/all/"] = _limit_settings(1)
    portal.routes[item_data_path(D3)] = _redirect(_storage())
    portal.routes[STORAGE_PATH] = b"x" * (2 * 1024 * 1024)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert _state(plan_file)["items"][D3]["status"] == "skipped"
    assert not files.uploads


def test_a_layer_named_like_the_single_file_marker_is_still_imported(
    runner, tmp_path, geolens, portal
):
    FakeFiles(geolens, layer_names=["file", "Parcels"])
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    entry = _state(plan_file)["items"][D3]
    assert entry["dataset_ids"] == [dataset_id("file"), dataset_id("Parcels")]
    assert entry["layer_jobs"] == {}


def _truncated(body: bytes, declared: int) -> tuple:
    return (200, body, {"Content-Length": str(declared)})


def test_a_download_that_ends_early_is_retried_and_never_imported(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = _truncated(CSV[:10], len(CSV))
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert "ended after 10 of" in _state(plan_file)["items"][D3]["error"]
    assert len(portal.requests_to(item_data_path(D3))) == 3
    assert not files.uploads


def test_a_download_cut_short_once_succeeds_on_the_retry(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = [
        _truncated(CSV[:10], len(CSV)),
        _truncated(CSV, len(CSV)),
    ]
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert CSV in files.uploads[0]


def test_a_redirected_download_that_ends_early_is_never_imported(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = _redirect(_storage())
    portal.routes[STORAGE_PATH] = _truncated(CSV[:10], len(CSV))
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert not files.uploads
    _assert_no_query_anywhere(plan_file, result)


def test_a_resumed_csv_commit_still_carries_its_coordinate_columns(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens)
    preview = files.preview
    files.preview = lambda job: {
        **preview(job),
        "geometry_type": None,
        "detected_geometry_columns": {"x_column": "lon", "y_column": "lat"},
    }
    commit = files.commit
    lost = {"on": True}

    def flaky(job, seen):
        if lost["on"]:
            return (500, _problem(500, "gateway lost before the commit landed"))
        return commit(job, seen)

    files.commit = flaky
    plan_file = _plan(tmp_path)
    result, _ = _migrate(runner, plan_file, "--only", D3)
    assert result.exit_code == 1
    assert _state(plan_file)["items"][D3]["file_columns"] == {
        "x_column": "lon",
        "y_column": "lat",
    }

    lost["on"] = False
    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output
    assert len(files.uploads) == 1
    [body] = files.commits.values()
    assert body["x_column"] == "lon" and body["y_column"] == "lat"


def test_a_same_host_redirect_to_the_portals_own_port_is_followed(
    runner, tmp_path, geolens, portal, monkeypatch
):
    FakeFiles(geolens)
    plan_file = _plan(tmp_path)
    plan = json.loads(plan_file.read_text())
    plan["portal"]["url"] = "https://portal.example.org:7443/portal"
    plan_file.write_text(json.dumps(plan))
    inventory = plan_file.parent / "arcgis-inventory.json"
    report = json.loads(inventory.read_text())
    report["portal"]["url"] = plan["portal"]["url"]
    inventory.write_text(json.dumps(report))
    portal.routes[item_data_path(D3)] = _redirect(
        f"https://portal.example.org:7443{STORAGE_PATH}?{SIGNED}"
    )
    portal.routes[STORAGE_PATH] = CSV

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "location", ["https://[::1/x?" + SIGNED, "https://www.arcgis.com:notaport/x"]
)
def test_a_malformed_redirect_target_fails_only_the_item(
    runner, tmp_path, geolens, portal, location
):
    files = FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = _redirect(location)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert "redirect" in _state(plan_file)["items"][D3]["error"]
    assert not files.uploads
    _assert_no_query_anywhere(plan_file, result)


def test_a_redirect_target_with_a_space_is_refused_without_naming_its_query(
    runner, tmp_path, geolens, portal
):
    files = FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = _redirect(
        f"https://www.arcgis.com{STORAGE_PATH}?k=PLAINQUERYSECRET x"
    )
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert not files.uploads
    assert not portal.requests_to(STORAGE_PATH)
    _assert_no_query_anywhere(plan_file, result)


def test_a_connection_error_on_the_storage_hop_does_not_name_its_url(
    runner, tmp_path, geolens, portal
):
    import http.client

    files = FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = _redirect(_storage())
    portal.routes[STORAGE_PATH] = http.client.InvalidURL(
        f"URL can't contain control characters: {_storage()!r}"
    )
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert not files.uploads
    _assert_no_query_anywhere(plan_file, result)


def test_a_disk_error_is_reported_once_and_not_retried(
    runner, tmp_path, geolens, portal, monkeypatch
):
    files = FakeFiles(geolens)
    real_open = os.open

    def failing(path, flags, mode=0o777, **kwargs):
        if str(path).endswith(".csv"):
            raise OSError(28, "No space left on device")
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr("geolens_cli.arcgis_portal.os.open", failing)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert "No space left" in _state(plan_file)["items"][D3]["error"]
    assert len(portal.requests_to(item_data_path(D3))) == 1
    assert not files.uploads


def test_retries_share_one_download_deadline(
    runner, tmp_path, geolens, portal, monkeypatch
):
    files = FakeFiles(geolens)
    portal.routes[item_data_path(D3)] = _truncated(CSV[:10], len(CSV))
    seen = []
    real = migrate.PortalClient._download_once

    def spy(self, request, path, dest, max_bytes, **kwargs):
        seen.append(self._download_end)
        return real(self, request, path, dest, max_bytes, **kwargs)

    monkeypatch.setattr(migrate.PortalClient, "_download_once", spy)
    plan_file = _plan(tmp_path)

    result, _ = _migrate(runner, plan_file, "--only", D3)

    assert result.exit_code == 1
    assert len(seen) == 3 and len(set(seen)) == 1
    assert not files.uploads


def test_a_download_over_an_existing_world_readable_file_ends_private(tmp_path):
    import stat

    from geolens_cli.arcgis_portal import PortalClient, Redactor

    portal_fake = FakePortal({"content/items/x/data": CSV})
    client = PortalClient(
        PORTAL, opener=portal_fake, redact=Redactor(), sleep=lambda seconds: None
    )
    dest = tmp_path / "data.csv"
    dest.write_text("old")
    dest.chmod(0o644)

    client.download("content/items/x/data", dest, None)

    assert dest.read_bytes() == CSV
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600
