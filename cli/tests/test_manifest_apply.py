"""CLI tests for networked `geolens apply`."""

from __future__ import annotations

import copy
import json
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from typing import Any

import httpx
import pytest
import typer

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
    Pinned against 1/10/100-entry manifests.

    fix(#1778 review round 20): round 18 ALSO capped the formula at
    MANIFEST_APPLY_TIMEOUT_CEILING_SECONDS (3600s) -- smaller than the
    formula's own maximum (600 + 100*70 == 7600s), so the cap started
    truncating the budget at ~43 entries, well inside the API's
    permitted 100. A valid, maximum-sized manifest of slow sources
    could still time out with earlier entries already queued. The cap
    is removed: the formula is now LINEAR in entry_count with no
    plateau, bounded only by the backend's own 100-entry schema cap.
    Pinned at the 43/44-entry boundary where the old cap used to bite,
    and at the full 100-entry maximum (7600s, not 3600s)."""

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

    def test_a_hundred_entries_is_linear_not_capped(self) -> None:
        """fix(#1778 review round 20): the API's own 100-dataset
        maximum is the only bound -- 600 + 100*70 == 7600.0, NOT the
        old 3600.0 ceiling."""
        from geolens_cli.manifest_apply import compute_manifest_apply_timeout

        assert compute_manifest_apply_timeout(100) == 7600.0

    def test_the_formula_stays_linear_past_where_the_old_ceiling_used_to_bite(
        self,
    ) -> None:
        """fix(#1778 review round 20): round 18's 3600s ceiling started
        truncating at entry 43 (600 + 43*70 == 3610, already past
        3600). Pinned at the 43/44 boundary to prove there is no
        plateau there any more -- each additional entry still adds
        exactly one per-entry allowance (70s)."""
        from geolens_cli.manifest_apply import compute_manifest_apply_timeout

        assert compute_manifest_apply_timeout(43) == 3610.0
        assert compute_manifest_apply_timeout(44) == 3680.0
        assert compute_manifest_apply_timeout(60) == 4800.0

    def test_less_than_one_is_coerced_to_one(self) -> None:
        from geolens_cli.manifest_apply import compute_manifest_apply_timeout

        assert compute_manifest_apply_timeout(0) == compute_manifest_apply_timeout(1)
        assert compute_manifest_apply_timeout(-5) == compute_manifest_apply_timeout(1)


class TestResolveApplyTimeout:
    """fix(#1778 review round 21) P1: the computed formula is only ever
    a heuristic lower bound -- MANIFEST_SOURCE_DOWNLOAD_TIMEOUT_SECONDS
    (60s) is the backend's per-chunk INACTIVITY timeout on a source
    download, not a total download deadline, so a large source served
    slowly but steadily can legitimately outlast it while the apply is
    still succeeding. resolve_apply_timeout() translates the already-
    parsed --timeout/GEOLENS_MANIFEST_APPLY_TIMEOUT value (click's own
    flag > envvar > default precedence already resolved which source
    won) into post_manifest_apply()'s timeout= kwarg shape."""

    def test_nothing_given_falls_back_to_the_formula(self) -> None:
        from geolens_cli.manifest_apply import _UNSET, resolve_apply_timeout

        assert resolve_apply_timeout(None) is _UNSET

    def test_zero_means_no_client_side_read_timeout(self) -> None:
        from geolens_cli.manifest_apply import resolve_apply_timeout

        assert resolve_apply_timeout(0.0) is None

    def test_a_positive_value_overrides_the_formula_outright(self) -> None:
        from geolens_cli.manifest_apply import resolve_apply_timeout

        assert resolve_apply_timeout(120.0) == 120.0

    def test_a_negative_value_is_rejected(self) -> None:
        from geolens_cli.manifest_apply import (
            ManifestApplyTimeoutValueError,
            resolve_apply_timeout,
        )

        with pytest.raises(ManifestApplyTimeoutValueError):
            resolve_apply_timeout(-1.0)

    def test_a_large_finite_value_is_accepted(self) -> None:
        from geolens_cli.manifest_apply import resolve_apply_timeout

        assert resolve_apply_timeout(7600.0) == 7600.0

    @pytest.mark.parametrize(
        "raw", [float("nan"), float("inf"), float("-inf"), float("1e309")]
    )
    def test_a_non_finite_value_is_rejected(self, raw: float) -> None:
        """fix(#1778 review round 24): float("nan") < 0 is False (every
        NaN comparison is False), and float("inf")/float("1e309")
        (which rounds to inf) are both non-negative -- the pre-round-24
        checks let all three all the way through to
        long_request_timeout() as a real, silently-unbounded timeout
        that never went through the documented --timeout 0 path."""
        from geolens_cli.manifest_apply import (
            ManifestApplyTimeoutValueError,
            resolve_apply_timeout,
        )

        with pytest.raises(ManifestApplyTimeoutValueError):
            resolve_apply_timeout(raw)


class TestManifestApplyTimeoutReporting:
    """fix(#1814): the timeout report must be accurate about what a re-apply
    does. The server keeps applying after the CLI gives up, and reserves each
    entry before downloading, so a re-apply attaches rather than queueing twice."""

    def _timing_out_client(self) -> FakeSdkClient:
        client = FakeSdkClient(FakeResponse(200, _apply_response()))

        def raising_post(**kwargs: Any) -> Any:
            import httpx

            # fix(#1778 review round 22): specifically ReadTimeout, not
            # the bare TimeoutException base class -- the request was
            # sent and this waited on the response, the only shape
            # ManifestApplyTimeout's "server may have already accepted
            # this" guidance is true for. See
            # TestManifestApplyTimeoutDistinguishesReadTimeout for the
            # other subtypes.
            raise httpx.ReadTimeout("stalled")

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

    def test_timeout_message_explains_what_a_re_apply_does_not_blanket_safety(
        self,
    ) -> None:
        """fix(#1814): the message must say a re-run attaches to an entry still
        being staged, give actionable advice (dry-run first), and make no
        blanket idempotency claim, which is the round-18 overclaim."""
        from geolens_cli.manifest_apply import (
            ManifestApplyTimeout,
            build_apply_timeout_message,
        )

        exc = ManifestApplyTimeout(entry_count=3, budget=810.0)
        message = build_apply_timeout_message(exc)

        assert "810s" in message
        assert "3 dataset" in message
        assert "does not stop" in message.lower()
        assert "before its source is downloaded" in message.lower()
        assert "attaches" in message.lower()
        assert "dry-run" in message.lower()
        assert "re-running" in message.lower()
        # The stale warning, and the round-18 overclaim, must both stay out.
        assert "twice" not in message.lower()
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

        # 100 synthetic dataset entries -- the entry-scaled budget
        # (compute_manifest_apply_timeout(100) == 7600.0) is nowhere
        # near the fixed 30s this follow-up must actually use.
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

    def test_status_check_absorbs_a_plain_network_failure_not_just_timeout(
        self,
    ) -> None:
        """fix(#1778 review round 21) P2: attempt_apply_timeout_status_
        check() only caught ManifestApplyTimeout/ManifestApplyRequestError
        -- a plain connection failure never raises either. call_sdk()
        maps httpx.NetworkError straight to typer.Exit(EXIT_NETWORK) on
        its own, which propagated uncaught and could blow up the
        --json branch in main.py before it ever emitted the promised
        structured payload. Must degrade to None like every other
        follow-up failure."""
        import httpx

        from geolens_cli.manifest_apply import attempt_apply_timeout_status_check

        client = FakeSdkClient(FakeResponse(200, _apply_response()))

        def refusing_post(**kwargs: Any) -> Any:
            raise httpx.NetworkError("connection refused")

        client.httpx_client.post = refusing_post

        payload = build_apply_payload(load_manifest(_manifest_path()), dry_run=False)

        result = attempt_apply_timeout_status_check(client, payload)

        assert result is None

    def test_report_apply_timeout_warns_when_the_follow_up_hits_a_network_failure(
        self,
    ) -> None:
        """fix(#1778 review round 21) P2, at the report_apply_timeout()
        level: the original timeout's explanation must still print even
        though the best-effort follow-up hit an unrelated network
        failure, not just a second timeout."""
        import httpx

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

        client = FakeSdkClient(FakeResponse(200, _apply_response()))

        def refusing_post(**kwargs: Any) -> Any:
            raise httpx.NetworkError("connection refused")

        client.httpx_client.post = refusing_post

        payload = build_apply_payload(load_manifest(_manifest_path()), dry_run=False)
        exc = ManifestApplyTimeout(entry_count=1, budget=670.0)

        result = report_apply_timeout(client, payload, exc, FakeOutput())

        assert result is None
        assert errors and "670s" in errors[0]
        assert warnings and "could not" in warnings[0].lower()


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


class TestManifestApplyTimeoutDistinguishesReadTimeout:
    """fix(#1778 review round 22) P2: the on_timeout hook fired for
    EVERY httpx.TimeoutException, but ConnectTimeout, PoolTimeout, and
    WriteTimeout all happen BEFORE the server could have accepted the
    request -- a hung TCP handshake, a slow local write, or waiting on
    this process's own connection pool say nothing about server-side
    state, so ManifestApplyTimeout's "the server keeps applying, a
    re-apply may duplicate an in-flight entry" guidance is simply wrong
    for them. Only httpx.ReadTimeout (request sent, waiting on the
    response) takes the manifest-continuation path; every other
    subtype goes through the ordinary network-failure path with its
    normal message and exit code, exactly as if on_timeout had never
    been given."""

    def _client_raising(self, exc_factory):
        client = FakeSdkClient(FakeResponse(200, _apply_response()))

        def raising_post(**kwargs: Any) -> Any:
            raise exc_factory()

        client.httpx_client.post = raising_post
        return client

    @pytest.mark.parametrize(
        "exc_factory",
        [
            lambda: httpx.ConnectTimeout("connect stalled"),
            lambda: httpx.PoolTimeout("pool exhausted"),
            lambda: httpx.WriteTimeout("write stalled"),
        ],
        ids=["connect", "pool", "write"],
    )
    def test_call_sdk_does_not_invoke_on_timeout_for_non_read_subtypes(
        self, exc_factory
    ) -> None:
        from geolens_cli._sdk_helpers import call_sdk

        on_timeout_calls: list[bool] = []

        def on_timeout():
            on_timeout_calls.append(True)
            return RuntimeError("should never be raised")

        def raising_fn(**kwargs):
            raise exc_factory()

        with pytest.raises(typer.Exit) as exc_info:
            call_sdk(raising_fn, on_timeout=on_timeout)

        assert on_timeout_calls == [], "on_timeout must not fire for this subtype"
        assert exc_info.value.exit_code == EXIT_NETWORK

    def test_call_sdk_invokes_on_timeout_for_read_timeout(self) -> None:
        from geolens_cli._sdk_helpers import call_sdk

        def on_timeout():
            return RuntimeError("custom exception")

        def raising_fn(**kwargs):
            raise httpx.ReadTimeout("stalled")

        with pytest.raises(RuntimeError, match="custom exception"):
            call_sdk(raising_fn, on_timeout=on_timeout)

    @pytest.mark.parametrize(
        "exc_factory",
        [
            lambda: httpx.ConnectTimeout("connect stalled"),
            lambda: httpx.PoolTimeout("pool exhausted"),
            lambda: httpx.WriteTimeout("write stalled"),
        ],
        ids=["connect", "pool", "write"],
    )
    def test_post_manifest_apply_falls_back_to_plain_network_failure(
        self, exc_factory
    ) -> None:
        """post_manifest_apply() must NOT raise ManifestApplyTimeout for
        a pre-acceptance timeout subtype -- it falls through call_sdk's
        generic path (typer.Exit(EXIT_NETWORK)), same as any other
        command's network failure."""
        client = self._client_raising(exc_factory)
        payload = build_apply_payload(load_manifest(_manifest_path()), dry_run=False)

        with pytest.raises(typer.Exit) as exc_info:
            post_manifest_apply(client, payload)

        assert exc_info.value.exit_code == EXIT_NETWORK

    def test_apply_command_reports_a_plain_network_failure_for_connect_timeout(
        self, runner, tmp_xdg_home, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI end-to-end: a ConnectTimeout during apply gets the
        ORDINARY "Request timed out" message, not the manifest
        continuation/idempotency guidance -- the server never had a
        chance to accept anything."""
        sdk = _install_fake_sdk(
            monkeypatch, FakeResponse(200, _apply_response(dry_run=False))
        )

        def raising_post(**kwargs):
            raise httpx.ConnectTimeout("connect stalled")

        sdk.client.httpx_client.post = raising_post

        result = runner.invoke(app, ["apply", str(_remote_manifest_path())])

        assert result.exit_code == EXIT_NETWORK, result.output
        assert "Request timed out" in result.output
        assert "downloading" not in result.output.lower()
        assert "twice" not in result.output.lower()
        assert "dry-run" not in result.output.lower()

    def test_apply_json_output_has_no_guidance_or_status_check_for_connect_timeout(
        self, runner, tmp_xdg_home, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--json mode for a pre-acceptance timeout gets whatever the
        ordinary (pre-round-18) network-failure path already produces
        for every other command's timeout -- no guidance/status_check
        fields, because post_manifest_apply() never even builds that
        payload for this subtype."""
        sdk = _install_fake_sdk(
            monkeypatch, FakeResponse(200, _apply_response(dry_run=False))
        )

        def raising_post(**kwargs):
            raise httpx.ConnectTimeout("connect stalled")

        sdk.client.httpx_client.post = raising_post

        result = runner.invoke(app, ["--json", "apply", str(_remote_manifest_path())])

        assert result.exit_code == EXIT_NETWORK, result.output
        json_lines = [
            line
            for line in result.output.strip().splitlines()
            if line.strip().startswith("{")
        ]
        assert json_lines == [], (
            "no JSON payload at all -- the ordinary network-failure path "
            f"doesn't build one, got: {json_lines}"
        )


class TestApplyTimeoutFlagAndEnvOverride:
    """fix(#1778 review round 21) P1 end-to-end: --timeout and
    GEOLENS_MANIFEST_APPLY_TIMEOUT override the computed heuristic
    outright, with the flag winning when both are given."""

    def _spying_sdk(self, monkeypatch: pytest.MonkeyPatch) -> tuple[FakeSdk, list]:
        sdk = _install_fake_sdk(
            monkeypatch, FakeResponse(200, _apply_response(dry_run=False))
        )
        httpx_client = sdk.client.httpx_client
        seen: list = []
        original_post = httpx_client.post

        def spying_post(**kwargs):
            seen.append(httpx_client.timeout)
            return original_post(**kwargs)

        httpx_client.post = spying_post
        return sdk, seen

    def test_the_flag_overrides_the_formula(
        self, runner, tmp_xdg_home, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from geolens_cli.manifest_apply import compute_manifest_apply_timeout

        _sdk, seen = self._spying_sdk(monkeypatch)

        result = runner.invoke(
            app, ["apply", "--timeout", "55", str(_remote_manifest_path())]
        )

        assert result.exit_code == 0, result.output
        assert seen == [55.0]
        assert seen[0] != compute_manifest_apply_timeout(1)

    def test_the_env_var_overrides_the_formula(
        self, runner, tmp_xdg_home, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _sdk, seen = self._spying_sdk(monkeypatch)

        result = runner.invoke(
            app,
            ["apply", str(_remote_manifest_path())],
            env={"GEOLENS_MANIFEST_APPLY_TIMEOUT": "77"},
        )

        assert result.exit_code == 0, result.output
        assert seen == [77.0]

    def test_the_flag_wins_over_the_env_var(
        self, runner, tmp_xdg_home, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _sdk, seen = self._spying_sdk(monkeypatch)

        result = runner.invoke(
            app,
            ["apply", "--timeout", "55", str(_remote_manifest_path())],
            env={"GEOLENS_MANIFEST_APPLY_TIMEOUT": "77"},
        )

        assert result.exit_code == 0, result.output
        assert seen == [55.0]

    def test_timeout_zero_produces_a_client_with_no_read_timeout(
        self, runner, tmp_xdg_home, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fix(#1778 review round 21): --timeout 0 removes the
        client-side READ timeout entirely (an httpx.Timeout with
        read/write/pool all None) while keeping the connect phase
        bounded -- not a bare float 0, which httpx would treat as
        "time out immediately"."""
        import httpx

        from geolens_cli._sdk_helpers import DEFAULT_HTTP_TIMEOUT_SECONDS

        _sdk, seen = self._spying_sdk(monkeypatch)

        result = runner.invoke(
            app, ["apply", "--timeout", "0", str(_remote_manifest_path())]
        )

        assert result.exit_code == 0, result.output
        assert len(seen) == 1
        used = seen[0]
        assert isinstance(used, httpx.Timeout)
        assert used.connect == DEFAULT_HTTP_TIMEOUT_SECONDS
        assert used.read is None
        assert used.write is None
        assert used.pool is None

    def test_a_negative_timeout_is_a_usage_error(
        self, runner, tmp_xdg_home, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from geolens_cli._sdk_helpers import EXIT_USAGE

        _sdk, seen = self._spying_sdk(monkeypatch)

        result = runner.invoke(
            app, ["apply", "--timeout", "-5", str(_remote_manifest_path())]
        )

        assert result.exit_code == EXIT_USAGE, result.output
        assert seen == [], "must be rejected before any network call"

    def test_a_non_numeric_timeout_is_a_usage_error(
        self, runner, tmp_xdg_home, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from geolens_cli._sdk_helpers import EXIT_USAGE

        _sdk, seen = self._spying_sdk(monkeypatch)

        result = runner.invoke(
            app, ["apply", "--timeout", "not-a-number", str(_remote_manifest_path())]
        )

        assert result.exit_code == EXIT_USAGE, result.output
        assert seen == [], "must be rejected before any network call"

    def test_a_non_numeric_env_var_is_a_usage_error(
        self, runner, tmp_xdg_home, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from geolens_cli._sdk_helpers import EXIT_USAGE

        _sdk, seen = self._spying_sdk(monkeypatch)

        result = runner.invoke(
            app,
            ["apply", str(_remote_manifest_path())],
            env={"GEOLENS_MANIFEST_APPLY_TIMEOUT": "not-a-number"},
        )

        assert result.exit_code == EXIT_USAGE, result.output
        assert seen == [], "must be rejected before any network call"

    @pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "1e309"])
    def test_a_non_finite_flag_value_is_a_usage_error(
        self, runner, tmp_xdg_home, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        """Pin (P2 round 24): nan/inf/-inf/1e309 -> usage error for
        --timeout, rejected before any network call."""
        from geolens_cli._sdk_helpers import EXIT_USAGE

        _sdk, seen = self._spying_sdk(monkeypatch)

        result = runner.invoke(
            app, ["apply", "--timeout", raw, str(_remote_manifest_path())]
        )

        assert result.exit_code == EXIT_USAGE, result.output
        assert seen == [], "must be rejected before any network call"

    @pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "1e309"])
    def test_a_non_finite_env_var_value_is_a_usage_error(
        self, runner, tmp_xdg_home, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        """Pin (P2 round 24): nan/inf/-inf/1e309 -> usage error for
        GEOLENS_MANIFEST_APPLY_TIMEOUT too, rejected before any network
        call."""
        from geolens_cli._sdk_helpers import EXIT_USAGE

        _sdk, seen = self._spying_sdk(monkeypatch)

        result = runner.invoke(
            app,
            ["apply", str(_remote_manifest_path())],
            env={"GEOLENS_MANIFEST_APPLY_TIMEOUT": raw},
        )

        assert result.exit_code == EXIT_USAGE, result.output
        assert seen == [], "must be rejected before any network call"

    def test_zero_and_a_large_finite_value_are_still_accepted(
        self, runner, tmp_xdg_home, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pin (P2 round 24): 0 and 7600 still accepted -- the
        non-finite guard must not overreach onto ordinary values."""
        _sdk, seen = self._spying_sdk(monkeypatch)

        result = runner.invoke(
            app, ["apply", "--timeout", "7600", str(_remote_manifest_path())]
        )
        assert result.exit_code == 0, result.output
        assert seen == [7600.0]

        _sdk2, seen2 = self._spying_sdk(monkeypatch)
        result2 = runner.invoke(
            app, ["apply", "--timeout", "0", str(_remote_manifest_path())]
        )
        assert result2.exit_code == 0, result2.output
        assert len(seen2) == 1


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

            # fix(#1778 review round 22): ReadTimeout specifically -- see
            # _timing_out_client's comment above.
            raise httpx.ReadTimeout("stalled")
        return original_post(**kwargs)

    sdk.client.httpx_client.post = flaky_post
    sdk.client.httpx_client.calls_made = calls
    return sdk


def test_apply_command_reports_timeout_with_truthful_guidance_and_status_check(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fix(#1814): end to end, the `apply` command prints the guidance and
    renders the dry-run follow-up's status, and that guidance says a re-run
    attaches to an entry still being staged."""
    status_response = _apply_response(
        results=[
            {"dataset_key": "roads", "action": "skip", "message": "skip_complete"}
        ]
    )
    sdk = _flaky_then_ok_sdk(monkeypatch, status_response)

    result = runner.invoke(app, ["apply", str(_remote_manifest_path())])

    assert result.exit_code == EXIT_NETWORK, result.output
    assert "skip_complete" in result.output
    assert "attaches" in result.output.lower()
    assert "dry-run" in result.output.lower()
    assert "twice" not in result.output.lower()
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
    assert "before its source is downloaded" in payload["guidance"].lower()
    assert "attaches" in payload["guidance"].lower()
    assert "twice" not in payload["guidance"].lower()
    assert "idempotent" not in payload["guidance"].lower()
    assert payload["status_check"]["counts"]["skip"] == 1


def test_apply_json_output_survives_a_network_failure_in_the_status_check(
    runner,
    tmp_xdg_home,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fix(#1778 review round 21) P2 end-to-end: the ORIGINAL apply
    times out, and the best-effort dry-run follow-up hits a plain
    network failure (not a second timeout) -- --json mode must still
    emit exactly the one promised structured payload, with
    status_check: null, instead of blowing up on the follow-up's
    uncaught typer.Exit before reaching state.output.json() at all."""
    import httpx

    sdk = FakeSdk(FakeResponse(200, _apply_response()))
    monkeypatch.setattr(AppState, "sdk", lambda _self: sdk)

    calls = {"n": 0}

    def flaky_then_refusing_post(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            # fix(#1778 review round 22): ReadTimeout specifically -- see
            # _timing_out_client's comment above.
            raise httpx.ReadTimeout("stalled")
        raise httpx.NetworkError("connection refused")

    sdk.client.httpx_client.post = flaky_then_refusing_post

    result = runner.invoke(app, ["--json", "apply", str(_remote_manifest_path())])

    assert result.exit_code == EXIT_NETWORK, result.output
    # The absorbed NetworkError's own call_sdk() diagnostic
    # ("Network error: ...") goes to STDERR regardless of --json (that
    # side effect is unrelated to this fix and pre-dates it); CliRunner
    # merges stdout+stderr into .output, so filter for the JSON-shaped
    # line specifically rather than asserting the merged stream has
    # exactly one line -- a real --json consumer only reads stdout,
    # where there IS exactly one line.
    json_lines = [
        line
        for line in result.output.strip().splitlines()
        if line.strip().startswith("{")
    ]
    assert len(json_lines) == 1, f"expected exactly one JSON object, got: {json_lines}"
    payload = json.loads(json_lines[0])
    assert payload["ok"] is False
    assert payload["status_check"] is None
    assert "670s" in payload["error"]
    assert calls["n"] == 2, "the original POST, then the failed follow-up"


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


class TestApplyWait:
    """`geolens apply --wait` follows each queued job and exits by precedence."""

    DATASETS = {
        "roads": "00000000-0000-0000-0000-0000000000a1",
        "parks": "00000000-0000-0000-0000-0000000000a2",
    }

    def _setup(self, monkeypatch, outcomes: dict[str, str], extra=()):
        from types import SimpleNamespace

        from geolens_cli import refresh as _refresh

        results = [
            {
                "dataset_key": key,
                "action": "update",
                "job_id": f"00000000-0000-0000-0000-0000000000b{i}",
                "dataset_id": dataset_id,
                "message": "queued",
                "errors": [],
            }
            for i, (key, dataset_id) in enumerate(self.DATASETS.items(), start=1)
        ] + list(extra)
        sdk = _install_fake_sdk(
            monkeypatch,
            FakeResponse(200, _apply_response(results=results)),
        )
        sdk.client.credential_kind = "bearer"
        sdk.credential_kind = "bearer"
        sdk.credential_provenance = None
        monkeypatch.setattr(AppState, "active_instance", lambda _self: "https://x.example.com")

        def fake_wait(client, dataset_id, run_id, *, ingest_job_id, **_kw):
            key = next(k for k, v in self.DATASETS.items() if v == str(dataset_id))
            return _refresh.RefreshPollResult(
                status=outcomes[key],
                run_id=f"run-{key}",
                verification={"review_reasons": ["srid_changed"]},
            )

        monkeypatch.setattr("geolens_cli.refresh.wait_for_refresh_run", fake_wait)
        return SimpleNamespace(sdk=sdk)

    @pytest.mark.parametrize(
        ("outcomes", "extra_error", "expected"),
        [
            ({"roads": "succeeded", "parks": "succeeded"}, False, 0),
            ({"roads": "succeeded", "parks": "blocked"}, False, 6),
            ({"roads": "failed", "parks": "blocked"}, False, 1),
            ({"roads": "cancelled", "parks": "blocked"}, False, 1),
            ({"roads": "succeeded", "parks": "blocked"}, True, 1),
        ],
    )
    def test_exit_precedence(
        self, runner, monkeypatch, outcomes, extra_error, expected
    ) -> None:
        extra = (
            [{"dataset_key": "bad", "action": "error", "errors": ["nope"], "message": "x"}]
            if extra_error
            else []
        )
        self._setup(monkeypatch, outcomes, extra)

        result = runner.invoke(app, ["apply", "--wait", str(_remote_manifest_path())])

        assert result.exit_code == expected, result.output

    def test_json_carries_final_status_and_run_id(self, runner, monkeypatch) -> None:
        self._setup(monkeypatch, {"roads": "succeeded", "parks": "blocked"})

        result = runner.invoke(
            app, ["--json", "apply", "--wait", str(_remote_manifest_path())]
        )

        assert result.exit_code == 6
        by_key = {r["dataset_key"]: r for r in json.loads(result.output)["results"]}
        assert by_key["roads"]["final_status"] == "complete"
        assert by_key["parks"]["final_status"] == "blocked"
        assert by_key["parks"]["run_id"] == "run-parks"

    def test_table_has_a_status_column_and_the_accept_hint(
        self, runner, monkeypatch
    ) -> None:
        self._setup(monkeypatch, {"roads": "succeeded", "parks": "blocked"})

        result = runner.invoke(app, ["apply", "--wait", str(_remote_manifest_path())])

        assert "STATUS" in result.output
        assert (
            f"Accept with: geolens refresh {self.DATASETS['parks']} "
            "--accept-blocked-run run-parks"
        ) in result.output.replace("\n", " ").replace("  ", " ")

    def test_blocked_entry_lists_its_reasons_before_the_accept_line(
        self, runner, monkeypatch
    ) -> None:
        from geolens_cli import refresh as _refresh

        self._setup(monkeypatch, {"roads": "succeeded", "parks": "blocked"})

        def blocked(client, dataset_id, run_id, *, ingest_job_id, **_kw):
            return _refresh.RefreshPollResult(
                status="blocked",
                run_id="run-x",
                verification={
                    "review_reasons": ["destructive_schema_change", "empty_result"]
                },
            )

        monkeypatch.setattr("geolens_cli.refresh.wait_for_refresh_run", blocked)

        result = runner.invoke(app, ["apply", "--wait", str(_remote_manifest_path())])

        out = result.output
        accept = out.index("Accept with:")
        for sentence in (
            "Columns would be removed or change type.",
            "The replacement has no rows but the dataset does.",
        ):
            assert 0 <= out.index(sentence) < accept

    def test_without_wait_nothing_is_polled(self, runner, monkeypatch) -> None:
        self._setup(monkeypatch, {"roads": "blocked", "parks": "blocked"})

        def must_not_poll(*a, **k):  # pragma: no cover - guard
            raise AssertionError("apply without --wait must not poll")

        monkeypatch.setattr("geolens_cli.refresh.wait_for_refresh_run", must_not_poll)

        result = runner.invoke(app, ["apply", str(_remote_manifest_path())])

        assert result.exit_code == 0, result.output
        assert "STATUS" not in result.output

    @pytest.mark.parametrize(("outcome", "expected"), [("failed", 1), ("blocked", 6)])
    def test_a_skip_that_names_a_job_is_followed(
        self, runner, monkeypatch, outcome, expected
    ) -> None:
        self._setup(
            monkeypatch,
            {"roads": "succeeded", "parks": outcome},
        )
        # parks was an idempotent retry: the server answered skip with the job.
        sdk_response = FakeResponse(
            200,
            _apply_response(
                results=[
                    {
                        "dataset_key": "parks",
                        "action": "skip",
                        "job_id": "00000000-0000-0000-0000-0000000000b2",
                        "dataset_id": self.DATASETS["parks"],
                        "message": "already queued",
                        "errors": [],
                    }
                ]
            ),
        )
        sdk = _install_fake_sdk(monkeypatch, sdk_response)
        sdk.client.credential_kind = "bearer"
        sdk.credential_kind = "bearer"
        sdk.credential_provenance = None

        result = runner.invoke(app, ["apply", "--wait", str(_remote_manifest_path())])

        assert result.exit_code == expected, result.output

    def test_a_skip_without_a_job_is_unchanged(self, runner, monkeypatch) -> None:
        self._setup(monkeypatch, {"roads": "blocked", "parks": "blocked"})
        sdk = _install_fake_sdk(
            monkeypatch,
            FakeResponse(
                200,
                _apply_response(
                    results=[
                        {
                            "dataset_key": "roads",
                            "action": "skip",
                            "job_id": None,
                            "dataset_id": self.DATASETS["roads"],
                            "message": "unchanged",
                            "errors": [],
                        }
                    ]
                ),
            ),
        )
        sdk.credential_kind = "bearer"
        sdk.credential_provenance = None

        result = runner.invoke(app, ["apply", "--wait", str(_remote_manifest_path())])

        assert result.exit_code == 0, result.output

    def test_a_skip_whose_run_appears_after_the_job_ended_is_blocked(
        self, runner, monkeypatch
    ) -> None:
        from geolens_cli import refresh as _refresh

        sdk = _install_fake_sdk(
            monkeypatch,
            FakeResponse(
                200,
                _apply_response(
                    results=[
                        {
                            "dataset_key": "parks",
                            "action": "skip",
                            "job_id": "00000000-0000-0000-0000-0000000000b2",
                            "dataset_id": self.DATASETS["parks"],
                            "message": "already queued",
                            "errors": [],
                        }
                    ]
                ),
            ),
        )
        sdk.credential_kind = "bearer"
        sdk.credential_provenance = None
        monkeypatch.setattr(AppState, "active_instance", lambda _self: "https://x.example.com")
        lookups = []

        def run_appears_late(client, dataset_id, run_id, **_kw):
            lookups.append(1)
            if len(lookups) == 1:
                raise _refresh.RefreshRequestError("run not found")
            return _refresh.RefreshPollResult(
                status="blocked",
                run_id="run-parks",
                verification={"review_reasons": ["srid_changed"]},
            )

        monkeypatch.setattr("geolens_cli.refresh.wait_for_refresh_run", run_appears_late)
        monkeypatch.setattr(
            "geolens_cli.refresh.wait_for_refresh",
            lambda client, job_id, **_kw: _refresh.RefreshPollResult(status="failed"),
        )

        result = runner.invoke(app, ["--json", "apply", "--wait", str(_remote_manifest_path())])

        assert result.exit_code == 6, result.output
        row = json.loads(result.output)["results"][0]
        assert row["final_status"] == "blocked"
        assert row["run_id"] == "run-parks"
        assert row["review_reasons"] == ["srid_changed"]


class TestApplyWaitKeepsRefreshedCredentials:
    DATASET = "00000000-0000-0000-0000-0000000000a1"

    def _install(self, monkeypatch, results):
        sdk = _install_fake_sdk(
            monkeypatch, FakeResponse(200, _apply_response(results=results))
        )
        sdk.credential_kind = "bearer"
        sdk.credential_provenance = "stored-bearer"
        monkeypatch.setattr(AppState, "active_instance", lambda _self: "https://x.example.com")
        return sdk

    @staticmethod
    def _result(key, action, job, dataset_id):
        return {
            "dataset_key": key,
            "action": action,
            "job_id": job,
            "dataset_id": dataset_id,
            "message": "queued",
            "errors": [],
        }

    def _fake_reauth(self, monkeypatch, sdk, expire_on):
        """Expire the bearer on the first call of kind ``expire_on``."""
        replacement = object()
        calls: list[tuple[str, object]] = []
        expired = []

        def fake(fn, **kwargs):
            kind = "job" if "job_id" in kwargs else "runs"
            calls.append((kind, kwargs["client"]))
            if kind == expire_on and not expired:
                expired.append(True)
                kwargs["on_reauthenticated"](replacement)
            if kind == "job":
                parsed = SimpleNamespace(status="complete", error_message=None)
            else:
                parsed = SimpleNamespace(
                    runs=[
                        SimpleNamespace(
                            id=UUID(int=9),
                            ingest_job_id=UUID("00000000-0000-0000-0000-0000000000b1"),
                            status="succeeded",
                            error_message=None,
                            verification=None,
                        )
                    ]
                )
            return SimpleNamespace(status_code=HTTPStatus.OK, parsed=parsed)

        monkeypatch.setattr("geolens_cli.refresh.call_sdk_with_reauth", fake)
        return replacement, calls

    def test_a_later_job_uses_the_client_refreshed_during_an_earlier_run(
        self, runner, monkeypatch
    ) -> None:
        sdk = self._install(
            monkeypatch,
            [
                self._result("roads", "update", "00000000-0000-0000-0000-0000000000b1", self.DATASET),
                self._result("parks", "create", "00000000-0000-0000-0000-0000000000b2", None),
            ],
        )
        replacement, calls = self._fake_reauth(monkeypatch, sdk, expire_on="runs")

        result = runner.invoke(app, ["apply", "--wait", str(_remote_manifest_path())])

        assert result.exit_code == 0, result.output
        assert ("job", replacement) in calls
        assert all(client is replacement for kind, client in calls if kind == "job")

    def test_a_token_expiring_during_a_first_import_wait_reauthenticates(
        self, runner, monkeypatch
    ) -> None:
        sdk = self._install(
            monkeypatch,
            [self._result("parks", "create", "00000000-0000-0000-0000-0000000000b2", None)],
        )
        self._fake_reauth(monkeypatch, sdk, expire_on="job")

        result = runner.invoke(
            app, ["--json", "apply", "--wait", str(_remote_manifest_path())]
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["results"][0]["final_status"] == "complete"



def _drop_run_history_endpoint(monkeypatch) -> None:
    """Make the installed SDK look like one without the refresh-history endpoint."""
    import sys

    import geolens.api.datasets as datasets_pkg

    name = "list_dataset_refresh_runs_datasets_dataset_id_refresh_runs_get"
    monkeypatch.delattr(datasets_pkg, name, raising=False)
    monkeypatch.setitem(sys.modules, f"geolens.api.datasets.{name}", None)


class TestApplyWaitSdkAndMarkup:
    def test_an_sdk_without_run_history_refuses_before_the_request(
        self, runner, monkeypatch
    ) -> None:
        sdk = _install_fake_sdk(monkeypatch, FakeResponse(200, _apply_response()))
        _drop_run_history_endpoint(monkeypatch)

        result = runner.invoke(app, ["apply", "--wait", str(_remote_manifest_path())])

        assert result.exit_code == 1, result.output
        assert "Upgrade" in result.output
        assert sdk.client.httpx_client.calls == []

    def test_bracketed_names_render_literally_in_the_table(
        self, runner, monkeypatch
    ) -> None:
        _install_fake_sdk(
            monkeypatch,
            FakeResponse(
                200,
                _apply_response(
                    results=[
                        {
                            "dataset_key": "[bold]x[/unit]",
                            "action": "skip",
                            "job_id": None,
                            "dataset_id": None,
                            "message": "see [/unit]",
                            "errors": [],
                        }
                    ]
                ),
            ),
        )

        result = runner.invoke(app, ["apply", str(_remote_manifest_path())])

        assert result.exit_code == 0, result.output
        assert "[bold]x[/unit]" in result.output
        assert "see [/unit]" in result.output
