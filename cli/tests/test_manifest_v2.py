"""Manifest version 2 (preview): schema choice, upload before apply, reporting."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import yaml

from geolens_cli import publish as publish_module
from geolens_cli._sdk_helpers import EXIT_USAGE
from geolens_cli.main import AppState, app
from geolens_cli.manifest import (
    load_manifest,
    manifest_schema,
    minimal_manifest_text,
    validate_manifest,
)

from .test_manifest_apply import FakeResponse, FakeSdk

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_FIXTURE = (
    REPO_ROOT / "backend" / "tests" / "fixtures" / "publish_manifest_v2.schema.json"
)
BUNDLED_V2 = (
    Path(__file__).resolve().parents[1]
    / "geolens_cli"
    / "manifest"
    / "schemas"
    / "geolens-manifest-v2.schema.json"
)

UNUSED_UPLOAD_MESSAGE = (
    "Manifest dataset entry is unchanged: the uploaded file matches the last "
    "apply. Cancel the unused upload."
)
JOB_ID = UUID("11111111-1111-1111-1111-111111111111")
ROADS = b'{"type":"FeatureCollection","features":[]}'
ROADS_SHA = "sha256:" + hashlib.sha256(ROADS).hexdigest()


def _v2_document(**overrides: Any) -> dict[str, Any]:
    document = {
        "manifest_version": "2",
        "client": {"id": "geolens-cli", "version": "1.0.0"},
        "catalog": {"title": "Example"},
        "datasets": [
            {
                "key": "roads",
                "title": "Roads",
                "sources": [{"type": "vector", "uri": "./roads.geojson"}],
                "publication": {"intent": "draft"},
            }
        ],
    }
    document.update(overrides)
    return document


def _write_manifest(tmp_path: Path, document: dict[str, Any]) -> Path:
    (tmp_path / "roads.geojson").write_bytes(ROADS)
    path = tmp_path / "geolens.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def _entry(**extra: Any) -> dict[str, Any]:
    return {
        "dataset_key": "roads",
        "action": "create",
        "job_id": str(JOB_ID),
        "dataset_id": None,
        "message": "Manifest dataset ingest queued.",
        "errors": [],
        **extra,
    }


def _response(**extra: Any) -> dict[str, Any]:
    return {"accepted": True, "dry_run": False, "results": [_entry()], **extra}


@pytest.fixture
def uploads(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    seen: list[Path] = []

    def fake_upload(client: Any, path: Path) -> Any:
        seen.append(path)
        return SimpleNamespace(status_code=201, parsed=SimpleNamespace(job_id=JOB_ID))

    monkeypatch.setattr(publish_module, "upload_file", fake_upload)
    return seen


def _install_sdk(monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]) -> FakeSdk:
    sdk = FakeSdk(FakeResponse(200, body))
    monkeypatch.setattr(AppState, "sdk", lambda _self: sdk)
    return sdk


def test_bundled_v2_schema_equals_the_backend_fixture() -> None:
    if not BACKEND_FIXTURE.is_file():
        pytest.skip("backend fixture is not reachable outside the monorepo")
    assert BUNDLED_V2.read_bytes() == BACKEND_FIXTURE.read_bytes(), (
        "cli/geolens_cli/manifest/schemas/geolens-manifest-v2.schema.json is out "
        "of date: copy backend/tests/fixtures/publish_manifest_v2.schema.json over it."
    )


def test_schema_is_chosen_by_manifest_version() -> None:
    assert manifest_schema("1")["title"] == "GeoLens Manifest v1"
    assert manifest_schema("2")["$id"].endswith("publish_manifest_v2.schema.json")


def test_v2_document_with_a_local_source_validates() -> None:
    assert validate_manifest(_v2_document()) == []


def test_v2_document_with_a_bad_field_is_refused() -> None:
    document = _v2_document()
    document["datasets"][0]["visibility"] = "everyone"

    errors = validate_manifest(document)

    assert [(e.path, e.code) for e in errors] == [("$.datasets[0].visibility", "enum")]


def test_v2_upload_source_without_checksum_is_refused() -> None:
    document = _v2_document()
    document["datasets"][0]["sources"][0]["uri"] = f"upload:{JOB_ID}"

    assert [(e.path, e.code) for e in validate_manifest(document)] == [
        ("$.datasets[0].sources[0].checksum", "required")
    ]


def test_unknown_version_still_reports_the_v1_const_error() -> None:
    document = _v2_document(manifest_version="3")

    assert ("$.manifest_version", "const") in {
        (e.path, e.code) for e in validate_manifest(document)
    }


def test_apply_uploads_a_local_source_then_sends_the_upload_reference(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads
) -> None:
    sdk = _install_sdk(monkeypatch, _response())
    path = _write_manifest(tmp_path, _v2_document())

    result = runner.invoke(app, ["apply", str(path)])

    assert result.exit_code == 0, result.output
    assert uploads == [tmp_path / "roads.geojson"]
    sent = sdk.client.httpx_client.calls[0]["json"]["datasets"][0]["sources"][0]
    assert sent == {"type": "vector", "uri": f"upload:{JOB_ID}", "checksum": ROADS_SHA}
    assert yaml.safe_load(path.read_text())["datasets"][0]["sources"][0]["uri"] == (
        "./roads.geojson"
    )


def test_dry_run_uploads_too(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads
) -> None:
    sdk = _install_sdk(monkeypatch, _response(dry_run=True))
    path = _write_manifest(tmp_path, _v2_document())

    result = runner.invoke(app, ["apply", "--dry-run", str(path)])

    assert result.exit_code == 0, result.output
    assert len(uploads) == 1
    assert sdk.client.httpx_client.calls[0]["json"]["dry_run"] is True


def test_missing_source_file_stops_before_any_upload_or_request(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads
) -> None:
    sdk = _install_sdk(monkeypatch, _response())
    path = _write_manifest(tmp_path, _v2_document())
    (tmp_path / "roads.geojson").unlink()

    result = runner.invoke(app, ["apply", str(path)])

    assert result.exit_code == EXIT_USAGE
    assert "Source file not found" in result.output
    assert uploads == []
    assert sdk.client.httpx_client.calls == []


def test_declared_checksum_that_differs_from_the_file_is_refused(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads
) -> None:
    sdk = _install_sdk(monkeypatch, _response())
    document = _v2_document()
    document["datasets"][0]["sources"][0]["checksum"] = "sha256:" + "a" * 64
    path = _write_manifest(tmp_path, document)

    result = runner.invoke(app, ["apply", str(path)])

    assert result.exit_code == EXIT_USAGE
    assert "does not match the checksum" in result.output
    assert uploads == []
    assert sdk.client.httpx_client.calls == []


def test_invalid_v2_manifest_is_refused_before_any_upload(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads
) -> None:
    document = _v2_document()
    document["datasets"][0]["visibility"] = "everyone"
    path = _write_manifest(tmp_path, document)

    result = runner.invoke(app, ["apply", str(path)])

    assert result.exit_code == EXIT_USAGE
    assert "$.datasets[0].visibility" in result.output
    assert uploads == []


def test_version_1_apply_never_uploads(
    runner, tmp_xdg_home, monkeypatch, uploads
) -> None:
    sdk = _install_sdk(monkeypatch, _response())
    manifest = (
        Path(__file__).resolve().parents[1]
        / "geolens_cli"
        / "manifest"
        / "fixtures"
        / "valid"
        / "vector-relative.yaml"
    )

    result = runner.invoke(app, ["apply", str(manifest)])

    assert result.exit_code == 0, result.output
    assert uploads == []
    assert sdk.client.httpx_client.calls[0]["json"]["manifest_version"] == "1"


MAP_RESULT = {
    "map_key": "overview",
    "action": "update",
    "map_id": "22222222-2222-2222-2222-222222222222",
    "messages": [
        {
            "code": "A070",
            "severity": "info",
            "message": "Kept the map's styling.",
            "fix": "Send styling replace.",
            "layer": "roads-layer",
        }
    ],
    "visibility": "internal",
    "styling": "kept",
    "groups": ["Planning"],
    "links": {
        "viewer": "https://geo.example/maps/2222",
        "share": "https://geo.example/s/abc",
        "embed": "https://geo.example/embed/abc",
    },
    "removed_layers": [
        {
            "key": "old",
            "dataset_id": "33333333-3333-3333-3333-333333333333",
            "link": "https://geo.example/datasets/3333",
        }
    ],
}


def test_apply_reports_maps_links_visibility_and_codes(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads
) -> None:
    body = _response(
        maps=[MAP_RESULT],
        results=[
            _entry(
                visibility="private",
                links={
                    "page": "https://geo.example/datasets/1",
                    "items": "https://geo.example/api/items",
                    "tiles": None,
                },
                messages=[
                    {"code": "A020", "severity": "warning", "message": "Widened."}
                ],
            )
        ],
    )
    _install_sdk(monkeypatch, body)
    path = _write_manifest(tmp_path, _v2_document())

    result = runner.invoke(app, ["apply", str(path)], terminal_width=200)

    assert result.exit_code == 0, result.output
    out = result.output
    for expected in (
        "visibility: private",
        "page: https://geo.example/datasets/1",
        "items: https://geo.example/api/items",
        "warning A020: Widened.",
        "Maps: create=0, update=1, skip=0, error=0",
        "overview",
        "kept",
        "viewer: https://geo.example/maps/2222",
        "share: https://geo.example/s/abc",
        "embed: https://geo.example/embed/abc",
        "groups: Planning",
        "removed layer old (https://geo.example/datasets/3333)",
        "info A070 (layer roads-layer): Kept the map's styling.",
        "Fix: Send styling replace.",
    ):
        assert expected in out, expected
    assert "22222222-2222" in out
    assert "tiles:" not in out


def test_json_report_carries_the_maps_and_a_map_error_fails_the_command(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads
) -> None:
    failed = {**MAP_RESULT, "action": "error", "map_id": None}
    _install_sdk(monkeypatch, _response(maps=[failed]))
    path = _write_manifest(tmp_path, _v2_document())

    result = runner.invoke(app, ["--json", "apply", str(path)])

    assert result.exit_code == 1, result.output
    report = json.loads(result.stdout)
    assert report["maps"] == [failed]
    assert report["map_counts"] == {"create": 0, "update": 0, "skip": 0, "error": 1}
    assert report["ok"] is False


def test_version_1_response_report_has_no_map_keys() -> None:
    from geolens_cli.manifest_apply import apply_report_payload

    report = apply_report_payload(Path("m.yaml"), _response())

    assert "maps" not in report and "map_counts" not in report


def test_init_writes_a_valid_v2_template(runner, tmp_xdg_home, tmp_path) -> None:
    target = tmp_path / "v2.yaml"

    result = runner.invoke(app, ["init", str(target), "--manifest-version", "2"])

    assert result.exit_code == 0, result.output
    document = load_manifest(target)
    assert document["manifest_version"] == "2"
    assert validate_manifest(document) == []
    assert "maps" in document


def test_init_defaults_to_version_1_and_rejects_unknown_versions(
    runner, tmp_xdg_home, tmp_path
) -> None:
    assert minimal_manifest_text().startswith('manifest_version: "1"')

    result = runner.invoke(
        app, ["init", str(tmp_path / "x.yaml"), "--manifest-version", "3"]
    )

    assert result.exit_code != 0
    assert not (tmp_path / "x.yaml").exists()


def test_schema_command_prints_the_requested_version(runner, tmp_xdg_home) -> None:
    result = runner.invoke(app, ["schema", "--manifest-version", "2"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["$id"].endswith(
        "publish_manifest_v2_authoring.schema.json"
    )


# --- round 2 ---


def test_a_document_dry_run_is_kept_and_nothing_is_consumed(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    sdk = _install_sdk(monkeypatch, _response(dry_run=True))
    path = _write_manifest(tmp_path, _v2_document(dry_run=True))

    result = runner.invoke(app, ["apply", str(path)])

    assert result.exit_code == 0, result.output
    assert sdk.client.httpx_client.calls[0]["json"]["dry_run"] is True
    assert cancels == [JOB_ID]
    assert "Cancelled unused upload" in result.output


def test_a_document_dry_run_skips_wait_handling(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    _install_sdk(monkeypatch, _response(dry_run=True))
    waited: list[Any] = []
    monkeypatch.setattr(
        "geolens_cli.manifest_apply.wait_for_apply_jobs",
        lambda *a, **k: waited.append(1),
    )
    path = _write_manifest(tmp_path, _v2_document(dry_run=True))

    result = runner.invoke(app, ["apply", "--wait", str(path)])

    assert result.exit_code == 0, result.output
    assert waited == []


def test_aliased_sources_get_distinct_upload_ids(tmp_path) -> None:
    from geolens_cli.manifest_upload import plan_local_uploads, upload_local_sources

    (tmp_path / "roads.geojson").write_bytes(ROADS)
    manifest = tmp_path / "m.yaml"
    manifest.write_text(
        """
manifest_version: "2"
client: {id: c, version: "1"}
catalog: {title: T}
datasets:
  - key: a
    title: A
    sources: &src
      - {type: vector, uri: ./roads.geojson}
    publication: {intent: draft}
  - key: b
    title: B
    sources: *src
    publication: {intent: draft}
""",
        encoding="utf-8",
    )
    document = load_manifest(manifest)
    ids = iter(
        [
            UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        ]
    )
    import geolens_cli.publish as pub

    original = pub.upload_file
    pub.upload_file = lambda client, path: SimpleNamespace(
        status_code=201, parsed=SimpleNamespace(job_id=next(ids))
    )
    try:
        created: list[UUID] = []
        staged = upload_local_sources(
            None, document, plan_local_uploads(document, tmp_path), created=created
        )
    finally:
        pub.upload_file = original

    uris = [d["sources"][0]["uri"] for d in staged["datasets"]]
    assert uris == [
        "upload:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "upload:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    ]
    assert len(created) == 2


@pytest.fixture
def cancels(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    seen: list[UUID] = []

    def fake_cancel(*, client: Any, job_id: UUID) -> Any:
        seen.append(job_id)
        return SimpleNamespace(status_code=200)

    from geolens.api.admin import cancel_job_jobs_job_id_cancel_post as mod

    monkeypatch.setattr(mod, "sync_detailed", fake_cancel)
    return seen


def test_a_skipped_entry_upload_is_cancelled_and_a_queued_one_is_kept(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    skipped = _response(
        results=[
            _entry(
                action="skip",
                job_id="99999999-9999-9999-9999-999999999999",
                message=UNUSED_UPLOAD_MESSAGE,
            )
        ]
    )
    _install_sdk(monkeypatch, skipped)
    path = _write_manifest(tmp_path, _v2_document())

    result = runner.invoke(app, ["--json", "apply", str(path)])

    assert result.exit_code == 0, result.output
    assert cancels == [JOB_ID]
    assert json.loads(result.stdout)["cancelled_uploads"] == [str(JOB_ID)]


def test_a_queued_entry_keeps_its_upload(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    _install_sdk(monkeypatch, _response())
    path = _write_manifest(tmp_path, _v2_document())

    result = runner.invoke(app, ["apply", str(path)])

    assert result.exit_code == 0, result.output
    assert cancels == []


A052_MAP = {
    "map_key": "overview",
    "action": "error",
    "map_id": None,
    "messages": [{"code": "A052", "severity": "error", "message": "Wait for jobs."}],
    "visibility": None,
    "styling": None,
    "groups": [],
    "links": None,
    "removed_layers": [],
}


def _document_with_map() -> dict[str, Any]:
    return _v2_document(
        maps=[
            {
                "key": "overview",
                "name": "Overview",
                "layers": [{"key": "l", "dataset_key": "roads"}],
            }
        ]
    )


def test_wait_resubmits_only_deferred_maps_and_reports_their_final_result(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    first = _response(maps=[A052_MAP])
    final_map = {**MAP_RESULT, "map_key": "overview", "action": "create"}
    bodies = [
        first,
        {"accepted": True, "dry_run": False, "results": [], "maps": [final_map]},
    ]
    sdk = FakeSdk(FakeResponse(200, first))
    posted: list[dict[str, Any]] = []

    def post(**kwargs: Any) -> FakeResponse:
        posted.append(kwargs["json"])
        return FakeResponse(200, bodies[len(posted) - 1])

    sdk.client.httpx_client.post = post
    monkeypatch.setattr(AppState, "sdk", lambda _self: sdk)
    sdk.credential_kind = "token"
    sdk.credential_provenance = None
    monkeypatch.setattr("geolens_cli.main._require_wait_sdk", lambda state: None)
    monkeypatch.setattr(
        "geolens_cli.manifest_apply.wait_for_apply_jobs",
        lambda client, response, **kw: {
            **response,
            "results": [{**r, "final_status": "complete"} for r in response["results"]],
        },
    )
    monkeypatch.setattr(AppState, "active_instance", lambda _self: "https://x")
    path = _write_manifest(tmp_path, _document_with_map())

    result = runner.invoke(app, ["--json", "apply", "--wait", str(path)])

    assert result.exit_code == 0, result.output
    second = posted[1]
    assert second["datasets"] == [] and second["dry_run"] is False
    assert [m["key"] for m in second["maps"]] == ["overview"]
    assert second["client"] == {"id": "geolens-cli", "version": "1.0.0"}
    assert json.loads(result.stdout)["maps"][0]["action"] == "create"
    assert len(uploads) == 1


def test_without_wait_a052_stays_and_says_to_run_again(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    _install_sdk(monkeypatch, _response(maps=[A052_MAP]))
    path = _write_manifest(tmp_path, _document_with_map())

    result = runner.invoke(app, ["apply", str(path)])

    assert result.exit_code == 1
    assert "A052" in result.output
    assert "once the jobs finish" in result.output


def test_printed_v2_schema_accepts_the_cli_template_and_wire_schema_does_not(
    runner, tmp_xdg_home
) -> None:
    from jsonschema import Draft202012Validator

    printed = json.loads(
        runner.invoke(app, ["schema", "--manifest-version", "2"]).stdout
    )
    template = yaml.safe_load(minimal_manifest_text("2"))

    assert list(Draft202012Validator(printed).iter_errors(template)) == []
    assert list(Draft202012Validator(manifest_schema("2")).iter_errors(template))
    assert manifest_schema("2")["$defs"]["source"]["required"] == [
        "type",
        "uri",
        "checksum",
    ]


def test_printed_v2_schema_still_requires_a_checksum_on_upload_sources() -> None:
    from jsonschema import Draft202012Validator

    from geolens_cli.manifest.schema import authoring_schema

    document = _v2_document()
    document["datasets"][0]["sources"][0]["uri"] = f"upload:{JOB_ID}"

    assert list(Draft202012Validator(authoring_schema()).iter_errors(document))


# --- round 3 ---


def _wait_setup(monkeypatch, bodies, *, wait_results=None, on_wait=None, post=None):
    """A fake SDK whose successive POST bodies are `bodies`, with a stubbed wait."""
    sdk = FakeSdk(FakeResponse(200, bodies[0]))
    posted: list[dict[str, Any]] = []

    def default_post(**kwargs: Any) -> FakeResponse:
        posted.append(kwargs["json"])
        return FakeResponse(200, bodies[len(posted) - 1])

    sdk.client.httpx_client.post = post(posted) if post else default_post
    sdk.credential_kind = "token"
    sdk.credential_provenance = None
    monkeypatch.setattr(AppState, "sdk", lambda _self: sdk)
    monkeypatch.setattr(AppState, "active_instance", lambda _self: "https://x")
    monkeypatch.setattr("geolens_cli.main._require_wait_sdk", lambda state: None)

    def fake_wait(client, response, **kw):
        if on_wait:
            on_wait(client, kw)
        done = dict(response)
        done["results"] = [
            {**r, **(wait_results or {"final_status": "complete"})}
            for r in response["results"]
        ]
        return done

    monkeypatch.setattr("geolens_cli.manifest_apply.wait_for_apply_jobs", fake_wait)
    return sdk, posted


FINAL_MAP = {**MAP_RESULT, "map_key": "overview", "action": "create"}
SECOND = {"accepted": True, "dry_run": False, "results": [], "maps": [FINAL_MAP]}


def test_a_map_whose_dataset_failed_is_not_resubmitted(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    _sdk, posted = _wait_setup(
        monkeypatch,
        [_response(maps=[A052_MAP]), SECOND],
        wait_results={"final_status": "failed"},
    )
    path = _write_manifest(tmp_path, _document_with_map())

    result = runner.invoke(app, ["--json", "apply", "--wait", str(path)])

    assert len(posted) == 1
    assert result.exit_code == 1
    maps = json.loads(result.stdout)["maps"]
    assert maps[0]["messages"][0]["code"] == "A052"
    assert "a dataset in this run did not finish" in maps[0]["not_retried"]


def test_one_failed_entry_with_no_dataset_id_holds_back_a_map_naming_it_by_id(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    document = _v2_document(
        maps=[
            {
                "key": "overview",
                "name": "Overview",
                "layers": [
                    {"key": "l", "dataset_id": "44444444-4444-4444-4444-444444444444"}
                ],
            }
        ]
    )
    document["datasets"].append(
        {
            "key": "rivers",
            "title": "Rivers",
            "sources": [{"type": "vector", "uri": "./rivers.geojson"}],
            "publication": {"intent": "draft"},
        }
    )
    ok = _entry(dataset_id="44444444-4444-4444-4444-444444444444")
    failed = _entry(dataset_key="rivers", dataset_id=None, job_id=str(UUID(int=9)))
    body = _response(maps=[A052_MAP], results=[ok, failed])
    sdk = FakeSdk(FakeResponse(200, body))
    posted: list[Any] = []

    def post(**kwargs: Any) -> FakeResponse:
        posted.append(kwargs["json"])
        return FakeResponse(200, body if len(posted) == 1 else SECOND)

    sdk.client.httpx_client.post = post
    sdk.credential_kind = "token"
    sdk.credential_provenance = None
    monkeypatch.setattr(AppState, "sdk", lambda _self: sdk)
    monkeypatch.setattr(AppState, "active_instance", lambda _self: "https://x")
    monkeypatch.setattr("geolens_cli.main._require_wait_sdk", lambda state: None)
    monkeypatch.setattr(
        "geolens_cli.manifest_apply.wait_for_apply_jobs",
        lambda client, response, **kw: {
            **response,
            "results": [
                {**ok, "final_status": "complete"},
                {**failed, "final_status": "failed"},
            ],
        },
    )
    path = _write_manifest(tmp_path, document)
    (tmp_path / "rivers.geojson").write_bytes(ROADS + b" ")

    result = runner.invoke(app, ["--json", "apply", "--wait", str(path)])

    assert len(posted) == 1
    assert json.loads(result.stdout)["maps"][0]["messages"][0]["code"] == "A052"


def test_the_deferred_request_carries_public_fallback(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    document = _document_with_map()
    document["public_fallback"] = "internal"
    _sdk, posted = _wait_setup(monkeypatch, [_response(maps=[A052_MAP]), SECOND])
    path = _write_manifest(tmp_path, document)

    result = runner.invoke(app, ["--json", "apply", "--wait", str(path)])

    assert result.exit_code == 0, result.output
    assert posted[1]["public_fallback"] == "internal"


def test_the_refreshed_client_is_used_for_the_retry_and_the_cleanup(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads
) -> None:
    fresh = FakeSdk(FakeResponse(200, SECOND)).client
    used: list[Any] = []

    def fake_cancel(*, client: Any, job_id: UUID) -> Any:
        used.append(("cancel", client))
        return SimpleNamespace(status_code=200)

    from geolens.api.admin import cancel_job_jobs_job_id_cancel_post as mod

    monkeypatch.setattr(mod, "sync_detailed", fake_cancel)
    body = _response(
        maps=[A052_MAP],
        results=[
            _entry(
                action="skip", job_id=str(UUID(int=7)), message=UNUSED_UPLOAD_MESSAGE
            )
        ],
    )
    sdk, posted = _wait_setup(
        monkeypatch,
        [body],
        on_wait=lambda client, kw: kw["on_client_replaced"](fresh),
    )
    path = _write_manifest(tmp_path, _document_with_map())

    result = runner.invoke(app, ["--json", "apply", "--wait", str(path)])

    assert result.exit_code == 0, result.output
    assert len(posted) == 1  # the old client sent only the first request
    assert len(fresh.httpx_client.calls) == 1
    assert fresh.httpx_client.calls[0]["json"]["datasets"] == []
    assert used == [("cancel", fresh)]


def test_wait_for_apply_jobs_reports_a_refreshed_client(monkeypatch) -> None:
    from geolens_cli import manifest_apply, refresh

    replacement = object()

    def fake_run(client, dataset_id, run, **kw):
        kw["on_reauthenticated"](replacement)
        return SimpleNamespace(
            succeeded=True, status="complete", run_id=None, error_message=None
        )

    monkeypatch.setattr(refresh, "wait_for_refresh_run", fake_run)
    seen: list[Any] = []
    response = _response(
        results=[_entry(dataset_id="44444444-4444-4444-4444-444444444444")]
    )

    manifest_apply.wait_for_apply_jobs(
        object(),
        response,
        instance="x",
        credential_kind="token",
        credential_provenance=None,
        on_client_replaced=seen.append,
    )

    assert seen == [replacement]


def test_a_failed_retry_keeps_the_first_results_cleans_up_and_exits_with_its_code(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    import typer

    def post(posted):
        def _post(**kwargs: Any) -> FakeResponse:
            posted.append(kwargs["json"])
            if len(posted) == 1:
                return FakeResponse(200, _response(maps=[A052_MAP]))
            raise typer.Exit(4)

        return _post

    _sdk, posted = _wait_setup(monkeypatch, [None], post=post)
    path = _write_manifest(tmp_path, _document_with_map())

    result = runner.invoke(app, ["--json", "apply", "--wait", str(path)])

    assert result.exit_code == 4
    report = json.loads(result.stdout)
    assert report["results"][0]["dataset_key"] == "roads"
    assert report["maps"][0]["not_retried"].startswith("retry failed")


def test_a_later_upload_failure_cancels_the_earlier_uploads(
    runner, tmp_xdg_home, tmp_path, monkeypatch, cancels
) -> None:

    calls: list[Path] = []

    def flaky(client: Any, path: Path) -> Any:
        calls.append(path)
        if len(calls) == 2:
            return SimpleNamespace(status_code=413, parsed=None)
        return SimpleNamespace(status_code=201, parsed=SimpleNamespace(job_id=JOB_ID))

    monkeypatch.setattr(publish_module, "upload_file", flaky)
    sdk = _install_sdk(monkeypatch, _response())
    document = _v2_document()
    document["datasets"].append(
        {
            "key": "rivers",
            "title": "Rivers",
            "sources": [{"type": "vector", "uri": "./rivers.geojson"}],
            "publication": {"intent": "draft"},
        }
    )
    path = _write_manifest(tmp_path, document)
    (tmp_path / "rivers.geojson").write_bytes(ROADS + b" ")

    result = runner.invoke(app, ["apply", str(path)])

    assert result.exit_code == 1
    assert cancels == [JOB_ID]
    assert sdk.client.httpx_client.calls == []
    assert "Cancelled unused upload" in result.output


def test_a_server_error_on_apply_keeps_the_uploads(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    sdk = FakeSdk(FakeResponse(500, None, text="boom"))
    monkeypatch.setattr(AppState, "sdk", lambda _self: sdk)
    path = _write_manifest(tmp_path, _v2_document())

    result = runner.invoke(app, ["apply", str(path)])

    assert result.exit_code != 0
    assert cancels == []


def test_a_refused_apply_cancels_the_uploads(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    sdk = FakeSdk(FakeResponse(422, {"detail": "no"}))
    monkeypatch.setattr(AppState, "sdk", lambda _self: sdk)
    path = _write_manifest(tmp_path, _v2_document())

    result = runner.invoke(app, ["apply", str(path)])

    assert result.exit_code == EXIT_USAGE
    assert cancels == [JOB_ID]


# --- round 4 ---


@pytest.mark.parametrize(
    "uri", ["https://example.org/bad path.geojson", "https://example.org/" + "a" * 2000]
)
def test_a_bad_source_uri_is_refused_by_validation(uri: str) -> None:
    document = _v2_document()
    document["datasets"][0]["sources"][0]["uri"] = uri

    assert ("$.datasets[0].sources[0].uri", "pattern") in {
        (e.path, e.code) for e in validate_manifest(document)
    }


def test_an_os_error_on_a_later_upload_cancels_the_earlier_ones(
    runner, tmp_xdg_home, tmp_path, monkeypatch, cancels
) -> None:
    calls: list[Path] = []

    def flaky(client: Any, path: Path) -> Any:
        calls.append(path)
        if len(calls) == 2:
            raise FileNotFoundError(str(path))
        return SimpleNamespace(status_code=201, parsed=SimpleNamespace(job_id=JOB_ID))

    monkeypatch.setattr(publish_module, "upload_file", flaky)
    sdk = _install_sdk(monkeypatch, _response())
    document = _v2_document()
    document["datasets"].append(
        {
            "key": "rivers",
            "title": "Rivers",
            "sources": [{"type": "vector", "uri": "./rivers.geojson"}],
            "publication": {"intent": "draft"},
        }
    )
    path = _write_manifest(tmp_path, document)
    (tmp_path / "rivers.geojson").write_bytes(ROADS + b" ")

    result = runner.invoke(app, ["apply", str(path)])

    assert result.exit_code == EXIT_USAGE
    assert cancels == [JOB_ID]
    assert sdk.client.httpx_client.calls == []


def test_an_error_answer_keeps_the_upload_and_lists_it(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    lost_ack = _response(results=[_entry(action="error", message="queue failed")])
    _install_sdk(monkeypatch, lost_ack)
    path = _write_manifest(tmp_path, _v2_document())

    result = runner.invoke(app, ["--json", "apply", str(path)])

    assert cancels == []
    report = json.loads(result.stdout)
    assert report["kept_uploads"] == [str(JOB_ID)]
    assert report["cancelled_uploads"] == []


def test_a_skip_without_the_unused_upload_message_is_kept(
    runner, tmp_xdg_home, tmp_path, monkeypatch, uploads, cancels
) -> None:
    _install_sdk(monkeypatch, _response(results=[_entry(action="skip")]))
    path = _write_manifest(tmp_path, _v2_document())

    runner.invoke(app, ["--json", "apply", str(path)])

    assert cancels == []
