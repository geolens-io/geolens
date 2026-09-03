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
    EXIT_NETWORK,
    EXIT_SERVER,
    EXIT_USAGE,
)
from geolens_cli.main import AppState, app
from geolens_cli.manifest.schema import load_manifest
from geolens_cli.manifest_apply import (
    APPLY_ENDPOINT,
    ManifestApplyRequestError,
    build_apply_payload,
    find_local_source_uris,
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
        # fix(#1778 review round 5): long_request_timeout() reads/restores this,
        # matching real httpx.Client's `.timeout` attribute.
        self.timeout = 30.0

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


def _remote_manifest_path() -> Path:
    # GAP-020: `apply` rejects manifests with LOCAL source URIs (use `publish`
    # for those). Command-level apply tests therefore use a remote-URI manifest
    # so the POST path is exercised end-to-end.
    return FIXTURE_ROOT / "valid" / "vector-url.yaml"


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


def test_post_manifest_apply_raises_the_bound_for_the_manifests_own_entry_count() -> None:
    """fix(#1778 review round 5): the backend validates and applies the
    manifest before responding, which can outlast AppState.sdk()'s plain
    30s bound for a manifest with many datasets. post_manifest_apply()
    must raise the bound for the POST itself and restore it afterward.

    fix(#1778 review round 18): the bound is no longer the fixed
    EXTENDED_REQUEST_TIMEOUT_SECONDS -- it's batch-aware
    (compute_manifest_apply_timeout), scaled to how many dataset
    entries THIS manifest actually has. The vector-relative.yaml
    fixture has exactly 1 dataset, so the expected bound is
    compute_manifest_apply_timeout(1); see
    TestComputeManifestApplyTimeout for the formula itself pinned
    against 1/10/100-entry counts directly."""
    from geolens_cli.manifest_apply import compute_manifest_apply_timeout

    response = FakeResponse(200, _apply_response())
    client = FakeSdkClient(response)
    httpx_client = client.httpx_client

    seen_timeout_during_post: list[float] = []
    original_post = httpx_client.post

    def spying_post(**kwargs):
        seen_timeout_during_post.append(httpx_client.timeout)
        return original_post(**kwargs)

    httpx_client.post = spying_post

    payload = build_apply_payload(load_manifest(_manifest_path()), dry_run=False)
    assert len(payload["datasets"]) == 1
    post_manifest_apply(client, payload)

    expected_budget = compute_manifest_apply_timeout(1)
    assert seen_timeout_during_post == [expected_budget]
    assert seen_timeout_during_post[0] != 30.0
    assert httpx_client.timeout == 30.0


class TestComputeManifestApplyTimeout:
    """fix(#1778 review round 18) part (a): the shared 600s
    long-request bound can expire during a legitimately still-
    succeeding apply -- ManifestApplyRequest allows 100 datasets,
    apply_manifest() processes them sequentially, and each entry's
    dominant synchronous cost is its own 60s HTTP source download.
    Pinned against 1/10/100-entry manifests -- the 100-entry case
    (ManifestApplyRequest's own hard maximum) also pins the documented
    ceiling actually binding."""

    def test_one_entry(self) -> None:
        from geolens_cli.manifest_apply import (
            MANIFEST_APPLY_BASE_TIMEOUT_SECONDS,
            MANIFEST_ENTRY_PROCESSING_MARGIN_SECONDS,
            MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS,
            compute_manifest_apply_timeout,
        )

        per_entry = (
            MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS
            + MANIFEST_ENTRY_PROCESSING_MARGIN_SECONDS
        )
        assert compute_manifest_apply_timeout(1) == (
            MANIFEST_APPLY_BASE_TIMEOUT_SECONDS + 1 * per_entry
        )
        assert compute_manifest_apply_timeout(1) == 670.0

    def test_ten_entries(self) -> None:
        from geolens_cli.manifest_apply import compute_manifest_apply_timeout

        assert compute_manifest_apply_timeout(10) == 1300.0

    def test_a_hundred_entries_hits_the_documented_ceiling(self) -> None:
        from geolens_cli.manifest_apply import (
            MANIFEST_APPLY_TIMEOUT_CEILING_SECONDS,
            compute_manifest_apply_timeout,
        )

        # Uncapped this would be 600 + 100*70 = 7600.0 -- the ceiling
        # must actually bind at ManifestApplyRequest's own maximum
        # (datasets: max_length=100), the worst case this formula has
        # to budget for.
        assert (
            compute_manifest_apply_timeout(100)
            == MANIFEST_APPLY_TIMEOUT_CEILING_SECONDS
        )
        assert compute_manifest_apply_timeout(100) == 3600.0

    def test_less_than_one_is_coerced_to_one(self) -> None:
        from geolens_cli.manifest_apply import compute_manifest_apply_timeout

        assert compute_manifest_apply_timeout(0) == compute_manifest_apply_timeout(1)
        assert compute_manifest_apply_timeout(-5) == compute_manifest_apply_timeout(1)


class TestManifestApplyTimeoutReporting:
    """fix(#1778 review round 18) parts (b)/(c), corrected by round 19:
    the timeout path must be unambiguous -- the server keeps applying
    after the CLI gives up, and an entry it has already queued or
    completed is skipped on a later re-apply. Round 18 additionally
    claimed re-running the SAME command was therefore always safe
    immediately; round 19 removes that claim, because it is false: an
    entry whose source was still downloading when the timeout hit has
    no job row yet (_classify_dataset()'s in-flight check runs before
    _create_job_and_queue()'s download, and the IngestJob row is only
    inserted after it -- manifest_service.py), so re-applying right
    away can queue that entry twice. A dry-run follow-up on the SAME
    endpoint (no new status/job-listing endpoint -- out of scope, no
    async job mode), bounded by a short fixed timeout regardless of
    entry count (round 19 P2), reports which entries the server had
    already reached, best-effort."""

    def _timing_out_client(self) -> FakeSdkClient:
        client = FakeSdkClient(FakeResponse(200, _apply_response()))

        def raising_post(**kwargs: Any) -> Any:
            import httpx

            raise httpx.TimeoutException("stalled")

        client.httpx_client.post = raising_post
        return client

    def test_post_manifest_apply_raises_manifest_apply_timeout_with_the_batch_budget(
        self,
    ) -> None:
        from geolens_cli._sdk_helpers import EXIT_NETWORK
        from geolens_cli.manifest_apply import (
            ManifestApplyTimeout,
            compute_manifest_apply_timeout,
        )

        client = self._timing_out_client()
        payload = build_apply_payload(load_manifest(_manifest_path()), dry_run=False)

        with pytest.raises(ManifestApplyTimeout) as exc_info:
            post_manifest_apply(client, payload)

        exc = exc_info.value
        assert exc.entry_count == 1
        assert exc.budget == compute_manifest_apply_timeout(1)
        assert exc.exit_code == EXIT_NETWORK

    def test_timeout_message_explains_the_in_flight_download_window_not_blanket_safety(
        self,
    ) -> None:
        """fix(#1778 review round 19): round 18's message claimed
        re-running immediately was always safe -- untrue, since an
        entry whose source was still downloading when the timeout hit
        has no job row yet and can be queued twice by an immediate
        re-apply. The message must explain THAT risk and give
        actionable advice (check the catalog, or dry-run first), and
        must NOT claim blanket idempotency/safety any more."""
        from geolens_cli.manifest_apply import (
            ManifestApplyTimeout,
            build_apply_timeout_message,
        )

        exc = ManifestApplyTimeout(entry_count=3, budget=810.0)
        message = build_apply_timeout_message(exc)

        assert "810s" in message
        assert "3 dataset" in message
        assert "does not stop" in message.lower()
        assert "downloading" in message.lower()
        assert "twice" in message.lower()
        assert "dry-run" in message.lower()
        assert "re-running" in message.lower()
        # The round-18 overclaim must not have crept back in.
        assert "idempotent" not in message.lower()
        assert "is safe" not in message.lower()
        assert "safely" not in message.lower()

    def test_report_apply_timeout_prints_and_returns_the_status_when_the_follow_up_succeeds(
        self,
    ) -> None:
        from geolens_cli.manifest_apply import (
            ManifestApplyTimeout,
            report_apply_timeout,
        )

        errors: list[str] = []
        warnings: list[str] = []

        class FakeOutput:
            def error(self, message: str) -> None:
                errors.append(message)

            def warn(self, message: str) -> None:
                warnings.append(message)

        status_response = _apply_response(
            results=[
                {"dataset_key": "roads", "action": "skip", "message": "skip_complete"}
            ]
        )
        client = FakeSdkClient(FakeResponse(200, status_response))
        payload = build_apply_payload(load_manifest(_manifest_path()), dry_run=False)
        exc = ManifestApplyTimeout(entry_count=1, budget=670.0)

        result = report_apply_timeout(client, payload, exc, FakeOutput())

        assert result == status_response
        assert errors and "670s" in errors[0]
        assert warnings == []
        # The follow-up must actually have asked for a dry run, not a
        # second real apply.
        assert client.httpx_client.calls[-1]["json"]["dry_run"] is True

    def test_status_check_follow_up_uses_the_short_fixed_timeout_regardless_of_entry_count(
        self,
    ) -> None:
        """fix(#1778 review round 19) P2: the dry-run follow-up must be
        bounded by MANIFEST_APPLY_STATUS_CHECK_TIMEOUT_SECONDS (a
        short, fixed 30s), NOT the entry-scaled budget the real apply
        needed -- dry_run does no download/queue work, so its cost
        does not grow with entry count. Pinned against a manifest with
        a LARGE entry count (100, the backend's own maximum) to prove
        this isn't accidentally still scaling."""
        from geolens_cli.manifest_apply import (
            MANIFEST_APPLY_STATUS_CHECK_TIMEOUT_SECONDS,
            ManifestApplyTimeout,
            compute_manifest_apply_timeout,
            report_apply_timeout,
        )

        status_response = _apply_response(results=[])
        client = FakeSdkClient(FakeResponse(200, status_response))
        httpx_client = client.httpx_client

        seen_timeout_during_status_check: list[float] = []
        original_post = httpx_client.post

        def spying_post(**kwargs):
            seen_timeout_during_status_check.append(httpx_client.timeout)
            return original_post(**kwargs)

        httpx_client.post = spying_post
        # A distinct sentinel (not 30.0, coincidentally also the
        # status-check bound) so "restored afterward" is a real check,
        # not an accident of both values matching.
        httpx_client.timeout = 999.0

        # 100 synthetic dataset entries -- large enough that the
        # entry-scaled budget (compute_manifest_apply_timeout(100))
        # would be the 3600s ceiling, nowhere near the fixed 30s this
        # follow-up must actually use.
        payload = {
            "manifest_version": "1",
            "dry_run": False,
            "datasets": [{"key": f"entry-{i}"} for i in range(100)],
        }
        exc = ManifestApplyTimeout(entry_count=100, budget=compute_manifest_apply_timeout(100))

        class FakeOutput:
            def error(self, message: str) -> None:
                pass

            def warn(self, message: str) -> None:
                pass

        report_apply_timeout(client, payload, exc, FakeOutput())

        assert seen_timeout_during_status_check == [
            MANIFEST_APPLY_STATUS_CHECK_TIMEOUT_SECONDS
        ]
        assert seen_timeout_during_status_check[0] == 30.0
        assert seen_timeout_during_status_check[0] != compute_manifest_apply_timeout(100)
        # Restored to whatever it was before the follow-up ran.
        assert httpx_client.timeout == 999.0

    def test_report_apply_timeout_warns_when_the_follow_up_also_fails(self) -> None:
        from geolens_cli.manifest_apply import (
            ManifestApplyTimeout,
            report_apply_timeout,
        )

        errors: list[str] = []
        warnings: list[str] = []

        class FakeOutput:
            def error(self, message: str) -> None:
                errors.append(message)

            def warn(self, message: str) -> None:
                warnings.append(message)

        client = self._timing_out_client()
        payload = build_apply_payload(load_manifest(_manifest_path()), dry_run=False)
        exc = ManifestApplyTimeout(entry_count=1, budget=670.0)

        result = report_apply_timeout(client, payload, exc, FakeOutput())

        assert result is None
        assert errors
        assert warnings and "could not" in warnings[0].lower()
        # fix(#1778 review round 19): must not fall back to claiming
        # safety just because the status check itself failed.
        assert "is safe" not in warnings[0].lower()
        assert "safely" not in warnings[0].lower()


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

    result = runner.invoke(app, ["apply", str(_remote_manifest_path())])

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

    result = runner.invoke(app, ["apply", "--dry-run", str(_remote_manifest_path())])

    assert result.exit_code == 0, result.output
    assert sdk.client.httpx_client.calls[0]["json"]["dry_run"] is True
    assert "Dry run" in result.output


def _flaky_then_ok_sdk(monkeypatch: pytest.MonkeyPatch, status_response: dict) -> FakeSdk:
    """A FakeSdk whose FIRST POST times out and every one after succeeds
    with ``status_response`` -- the round-18 apply-timeout-then-dry-run-
    follow-up shape."""
    sdk = FakeSdk(FakeResponse(200, status_response))
    monkeypatch.setattr(AppState, "sdk", lambda _self: sdk)

    calls = {"n": 0}
    original_post = sdk.client.httpx_client.post

    def flaky_post(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            import httpx

            raise httpx.TimeoutException("stalled")
        return original_post(**kwargs)

    sdk.client.httpx_client.post = flaky_post
    sdk.client.httpx_client.calls_made = calls
    return sdk


def test_apply_command_reports_timeout_with_truthful_guidance_and_status_check(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fix(#1778 review round 18) end-to-end, corrected by round 19: the
    `apply` command's own timeout handling (not just
    post_manifest_apply()) prints the in-flight-download-window
    guidance and renders the dry-run follow-up's status, rather than
    the old bare "Request timed out" -- and no longer claims an
    immediate re-run is unconditionally safe/idempotent (round 18 did;
    it wasn't true)."""
    status_response = _apply_response(
        results=[
            {"dataset_key": "roads", "action": "skip", "message": "skip_complete"}
        ]
    )
    sdk = _flaky_then_ok_sdk(monkeypatch, status_response)

    result = runner.invoke(app, ["apply", str(_remote_manifest_path())])

    assert result.exit_code == EXIT_NETWORK, result.output
    assert "skip_complete" in result.output
    assert "downloading" in result.output.lower()
    assert "twice" in result.output.lower()
    assert "dry-run" in result.output.lower()
    assert "idempotent" not in result.output.lower()
    assert sdk.client.httpx_client.calls_made["n"] == 2, (
        "the original POST, then the dry-run status follow-up"
    )
    assert sdk.client.httpx_client.calls[-1]["json"]["dry_run"] is True


def test_apply_json_output_reports_timeout_as_one_structured_payload(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fix(#1778 review round 18): --json mode must emit exactly ONE
    JSON object for a timeout, not report_apply_timeout's human-mode
    output.error()/warn() writes bleeding in ahead of it.

    fix(#1778 review round 19): the "resumable": True field claimed an
    immediate re-run was always safe -- not true, and removed. The
    payload now carries a "guidance" string with the same accurate,
    non-blanket explanation a human running the same command sees."""
    status_response = _apply_response(
        results=[
            {"dataset_key": "roads", "action": "skip", "message": "skip_complete"}
        ]
    )
    _flaky_then_ok_sdk(monkeypatch, status_response)

    result = runner.invoke(app, ["--json", "apply", str(_remote_manifest_path())])

    assert result.exit_code == EXIT_NETWORK, result.output
    lines = [line for line in result.output.strip().splitlines() if line.strip()]
    assert len(lines) == 1, f"expected exactly one JSON object, got: {lines}"
    payload = json.loads(lines[0])
    assert payload["ok"] is False
    assert "resumable" not in payload
    assert "downloading" in payload["guidance"].lower()
    assert "twice" in payload["guidance"].lower()
    assert "idempotent" not in payload["guidance"].lower()
    assert payload["status_check"]["counts"]["skip"] == 1


def test_apply_json_output_is_deterministic(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(200, _apply_response(dry_run=True))
    _install_fake_sdk(monkeypatch, response)

    result = runner.invoke(app, ["--json", "apply", "--dry-run", str(_remote_manifest_path())])

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
        "path": str(_remote_manifest_path()),
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

    result = runner.invoke(app, ["apply", str(_remote_manifest_path())])

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

    result = runner.invoke(app, ["apply", str(_remote_manifest_path())])

    assert result.exit_code == EXIT_GENERIC
    assert "accepted=false" in result.output


# ---------------------------------------------------------------------------
# GAP-020 — apply detects local source files and points the user to publish
# ---------------------------------------------------------------------------


def test_find_local_source_uris_detects_relative_paths() -> None:
    document = load_manifest(_manifest_path())  # vector-relative.yaml
    assert find_local_source_uris(document) == ["./data/roads.geojson"]


def test_find_local_source_uris_ignores_remote_uris() -> None:
    document = load_manifest(_remote_manifest_path())  # vector-url.yaml (https)
    assert find_local_source_uris(document) == []


def test_find_local_source_uris_mixed_manifest() -> None:
    document = {
        "datasets": [
            {"sources": [{"type": "vector", "uri": "./local.geojson"}]},
            {"sources": [{"type": "vector", "uri": "https://x/remote.gpkg"}]},
            {"sources": [{"type": "raster_cog", "uri": "s3://bucket/key.tif"}]},
            {"sources": [{"type": "raster_cog", "uri": "data/nested/file.tif"}]},
        ]
    }
    assert find_local_source_uris(document) == ["./local.geojson", "data/nested/file.tif"]


def test_apply_local_source_warns_but_posts(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GAP-020: a manifest with scheme-less (local) sources WARNS in human mode but
    still POSTs — the server resolves those paths from its own staging dir (the
    documented apply round-trip), so apply must not block them."""
    response = FakeResponse(200, _apply_response(dry_run=False))
    sdk = _install_fake_sdk(monkeypatch, response)

    # vector-relative.yaml references ./data/roads.geojson (local). Human mode.
    result = runner.invoke(app, ["apply", str(_manifest_path())])

    assert result.exit_code == 0, result.output
    assert sdk.client.httpx_client.calls[0]["url"] == APPLY_ENDPOINT
    assert "Warning" in result.output
    assert "publish" in result.output
    assert "./data/roads.geojson" in result.output


def test_apply_local_source_json_mode_is_silent_and_posts(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GAP-020: in --json mode the local-source warning is suppressed so stdout
    stays valid JSON, and apply still POSTs (mirrors the server-staging round-trip
    contract in backend/tests/test_cli_round_trip.py)."""
    response = FakeResponse(200, _apply_response(dry_run=False))
    sdk = _install_fake_sdk(monkeypatch, response)

    result = runner.invoke(app, ["--json", "apply", str(_manifest_path())])

    assert result.exit_code == 0, result.output
    assert sdk.client.httpx_client.calls[0]["url"] == APPLY_ENDPOINT
    assert "Warning" not in result.output
    json.loads(result.output)  # stdout must be parseable JSON


def test_apply_remote_source_still_posts(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity: a remote-URI manifest is unaffected by the GAP-020 guard."""
    response = FakeResponse(200, _apply_response(dry_run=False))
    sdk = _install_fake_sdk(monkeypatch, response)

    result = runner.invoke(app, ["apply", str(_remote_manifest_path())])

    assert result.exit_code == 0, result.output
    assert sdk.client.httpx_client.calls[0]["url"] == APPLY_ENDPOINT
