"""CLI tests for networked `geolens apply`."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from geolens_cli._sdk_helpers import (
    EXIT_AUTH,
    EXIT_GENERIC,
    EXIT_SERVER,
    EXIT_USAGE,
)
from geolens_cli.main import AppState, app
from geolens_cli.manifest.schema import load_manifest
from geolens_cli.manifest_apply import (
    APPLY_ENDPOINT,
    ManifestApplyRequestError,
    build_apply_payload,
    has_apply_errors,
    post_manifest_apply,
    summarize_results,
)


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "geolens_cli" / "manifest" / "fixtures"
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any] | None = None,
        *,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = text.encode("utf-8") if text else b"{}"

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeHttpxClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        return self.response


class FakeSdkClient:
    def __init__(self, response: FakeResponse) -> None:
        self.httpx_client = FakeHttpxClient(response)

    def get_httpx_client(self) -> FakeHttpxClient:
        return self.httpx_client


class FakeSdk:
    def __init__(self, response: FakeResponse) -> None:
        self.client = FakeSdkClient(response)


def _manifest_path() -> Path:
    return FIXTURE_ROOT / "valid" / "vector-relative.yaml"


def _invalid_manifest_path() -> Path:
    return FIXTURE_ROOT / "invalid" / "missing-dataset-key.yaml"


def _apply_response(
    *,
    accepted: bool = True,
    dry_run: bool = False,
    results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "accepted": accepted,
        "dry_run": dry_run,
        "results": results
        if results is not None
        else [
            {
                "dataset_key": "roads",
                "action": "create",
                "job_id": "00000000-0000-0000-0000-000000000001",
                "dataset_id": None,
                "message": "Manifest dataset ingest queued.",
                "errors": [],
            }
        ],
    }


def _install_fake_sdk(
    monkeypatch: pytest.MonkeyPatch,
    response: FakeResponse,
) -> FakeSdk:
    sdk = FakeSdk(response)
    monkeypatch.setattr(AppState, "sdk", lambda _self: sdk)
    return sdk


def test_build_apply_payload_adds_dry_run_without_mutating_manifest() -> None:
    document = load_manifest(_manifest_path())
    original = copy.deepcopy(document)

    payload = build_apply_payload(document, dry_run=True)

    assert payload["dry_run"] is True
    assert payload["datasets"] == document["datasets"]
    assert document == original


def test_post_manifest_apply_uses_sdk_owned_transport() -> None:
    response = FakeResponse(200, _apply_response())
    client = FakeSdkClient(response)

    payload = build_apply_payload(load_manifest(_manifest_path()), dry_run=False)
    post_manifest_apply(client, payload)

    assert client.httpx_client.calls == [
        {
            "url": APPLY_ENDPOINT,
            "json": payload,
        }
    ]


@pytest.mark.parametrize(
    ("status_code", "expected_exit"),
    [
        (401, EXIT_AUTH),
        (403, EXIT_AUTH),
        (422, EXIT_USAGE),
        (500, EXIT_SERVER),
        (418, EXIT_GENERIC),
    ],
)
def test_post_manifest_apply_maps_http_failures(
    status_code: int,
    expected_exit: int,
) -> None:
    client = FakeSdkClient(
        FakeResponse(status_code, {"detail": "backend detail"}, text="backend text")
    )

    with pytest.raises(ManifestApplyRequestError) as exc:
        post_manifest_apply(client, {"manifest_version": "1", "dry_run": False})

    assert exc.value.exit_code == expected_exit
    assert "backend detail" in exc.value.message


def test_summarize_results_counts_known_actions() -> None:
    response = _apply_response(
        results=[
            {"dataset_key": "a", "action": "create"},
            {"dataset_key": "b", "action": "update"},
            {"dataset_key": "c", "action": "skip"},
            {"dataset_key": "d", "action": "error"},
        ]
    )

    assert summarize_results(response) == {
        "create": 1,
        "error": 1,
        "skip": 1,
        "update": 1,
    }
    assert has_apply_errors(response) is True


def test_apply_default_sends_write_payload(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(200, _apply_response(dry_run=False))
    sdk = _install_fake_sdk(monkeypatch, response)

    result = runner.invoke(app, ["apply", str(_manifest_path())])

    assert result.exit_code == 0, result.output
    assert sdk.client.httpx_client.calls[0]["url"] == APPLY_ENDPOINT
    assert sdk.client.httpx_client.calls[0]["json"]["dry_run"] is False
    assert "roads" in result.output
    assert "create" in result.output


def test_apply_dry_run_sends_dry_run_payload(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(200, _apply_response(dry_run=True))
    sdk = _install_fake_sdk(monkeypatch, response)

    result = runner.invoke(app, ["apply", "--dry-run", str(_manifest_path())])

    assert result.exit_code == 0, result.output
    assert sdk.client.httpx_client.calls[0]["json"]["dry_run"] is True
    assert "Dry run" in result.output


def test_apply_json_output_is_deterministic(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(200, _apply_response(dry_run=True))
    _install_fake_sdk(monkeypatch, response)

    result = runner.invoke(app, ["--json", "apply", "--dry-run", str(_manifest_path())])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "accepted": True,
        "counts": {
            "create": 1,
            "error": 0,
            "skip": 0,
            "update": 0,
        },
        "dry_run": True,
        "ok": True,
        "path": str(_manifest_path()),
        "results": _apply_response(dry_run=True)["results"],
    }


def test_apply_human_output_includes_all_result_actions(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(
        200,
        _apply_response(
            results=[
                {"dataset_key": "parks", "action": "create", "message": "created"},
                {"dataset_key": "roads", "action": "update", "message": "updated"},
                {"dataset_key": "lakes", "action": "skip", "message": "unchanged"},
                {"dataset_key": "zoning", "action": "error", "message": "invalid"},
            ],
        ),
    )
    _install_fake_sdk(monkeypatch, response)

    result = runner.invoke(app, ["apply", str(_manifest_path())])

    assert result.exit_code == 1
    for expected in ("parks", "roads", "lakes", "zoning"):
        assert expected in result.output
    for expected in ("create", "update", "skip", "error"):
        assert expected in result.output


def test_apply_invalid_manifest_exits_two_before_sdk(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode_sdk(self):
        raise AssertionError("invalid manifests must not construct SDK clients")

    monkeypatch.setattr(AppState, "sdk", explode_sdk)

    result = runner.invoke(app, ["apply", str(_invalid_manifest_path())])

    assert result.exit_code == EXIT_USAGE
    assert "$.datasets[0].key" in result.output
    assert "Remediation" in result.output


def test_apply_rejected_response_exits_one(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(200, _apply_response(accepted=False))
    _install_fake_sdk(monkeypatch, response)

    result = runner.invoke(app, ["apply", str(_manifest_path())])

    assert result.exit_code == EXIT_GENERIC
    assert "accepted=false" in result.output
