"""CLI coverage for dataset refresh dispatch, polling, and source status."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from types import SimpleNamespace
from uuid import UUID

import pytest

DATASET_ID = UUID("00000000-0000-0000-0000-000000000122")
RUN_ID = UUID("00000000-0000-0000-0000-000000000123")
JOB_ID = UUID("00000000-0000-0000-0000-000000000124")
INSTANCE = "https://x.example.com/api"


def _seed_login(mock_keyring: dict) -> None:
    from geolens_cli import config

    mock_keyring[("geolens", INSTANCE)] = "cli-auth-token"
    config.write_default_instance(INSTANCE, username="alice")


def _pair_refresh_fingerprint(
    mock_keyring: dict, bearer: str, instance: str = INSTANCE
) -> None:
    """fix(#1778 round 31): tests that seed a bearer + refresh token
    directly into mock_keyring (bypassing store_refresh_token(), which
    would pair them automatically) must also seed the matching pairing
    fingerprint, or try_refresh() now correctly treats the refresh
    token as unpaired and discards it instead of using it."""
    from geolens_cli import auth as _auth

    mock_keyring[("geolens", f"{instance}:refresh_fp")] = _auth._fingerprint_bearer(bearer)


def _accepted(trigger: str = "api"):
    from geolens.models.dataset_refresh_response import DatasetRefreshResponse

    return SimpleNamespace(
        status_code=HTTPStatus.ACCEPTED,
        parsed=DatasetRefreshResponse(
            run_id=RUN_ID,
            job_id=JOB_ID,
            dataset_id=DATASET_ID,
            origin_kind="service",
            trigger=trigger,
            status="pending",
            message="Refresh queued from the stored source",
        ),
    )


def _problem(status: int, detail: str | dict):
    from geolens.models.problem_detail import ProblemDetail
    from geolens.models.problem_detail_detail_type_1 import ProblemDetailDetailType1

    parsed_detail = (
        ProblemDetailDetailType1.from_dict(detail)
        if isinstance(detail, dict)
        else detail
    )
    return SimpleNamespace(
        status_code=HTTPStatus(status),
        parsed=ProblemDetail(
            title="Refresh refused",
            status=status,
            detail=parsed_detail,
        ),
    )


def _patch_refresh_endpoint(monkeypatch, response, captured: dict | None = None):
    def fake_sync_detailed(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return response

    monkeypatch.setattr(
        "geolens.api.datasets_refresh."
        "refresh_dataset_datasets_dataset_id_refresh_post.sync_detailed",
        fake_sync_detailed,
    )


def _patch_job(monkeypatch, *, status: str, error_message: str | None = None):
    monkeypatch.setattr(
        "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
        lambda **_kwargs: SimpleNamespace(
            status_code=HTTPStatus.OK,
            parsed=SimpleNamespace(status=status, error_message=error_message),
        ),
    )


class TestRefreshRequest:
    def test_no_token_omits_the_optional_body_and_preserves_202_payload(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        captured: dict = {}
        _patch_refresh_endpoint(monkeypatch, _accepted(), captured)

        result = runner.invoke(app, ["--json", "refresh", str(DATASET_ID)])

        assert result.exit_code == 0, result.output
        assert "body" not in captured
        assert set(json.loads(result.output)) == {
            "run_id",
            "job_id",
            "dataset_id",
            "origin_kind",
            "trigger",
            "status",
            "message",
        }

    def test_explicit_token_body_contains_only_token_and_is_never_printed(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        captured: dict = {}
        secret = "protected-source-token-42"
        _patch_refresh_endpoint(monkeypatch, _accepted(trigger="cli"), captured)

        result = runner.invoke(
            app,
            ["--json", "refresh", str(DATASET_ID), "--token", secret],
        )

        assert result.exit_code == 0, result.output
        assert captured["body"].to_dict() == {"token": secret}
        assert secret not in result.output
        assert json.loads(result.output)["trigger"] == "cli"

    def test_bare_token_option_uses_a_hidden_prompt(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        captured: dict = {}
        secret = "prompt-only-secret-84"
        _patch_refresh_endpoint(monkeypatch, _accepted(), captured)

        result = runner.invoke(
            app,
            ["refresh", str(DATASET_ID), "--token"],
            input=f"{secret}\n",
        )

        assert result.exit_code == 0, result.output
        assert "Service token:" in result.output
        assert captured["body"].to_dict() == {"token": secret}
        assert secret not in result.output

    def test_bare_token_can_prompt_before_wait_flag(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        captured: dict = {}
        secret = "prompt-then-wait-secret"
        _patch_refresh_endpoint(monkeypatch, _accepted(), captured)
        _patch_job(monkeypatch, status="complete")

        result = runner.invoke(
            app,
            ["refresh", str(DATASET_ID), "--token", "--wait"],
            input=f"{secret}\n",
        )

        assert result.exit_code == 0, result.output
        assert captured["body"].to_dict() == {"token": secret}
        assert secret not in result.output

    def test_timeout_without_wait_is_rejected_before_dispatch(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        called = False

        def should_not_run(**_kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr(
            "geolens.api.datasets_refresh."
            "refresh_dataset_datasets_dataset_id_refresh_post.sync_detailed",
            should_not_run,
        )
        result = runner.invoke(
            app,
            ["refresh", str(DATASET_ID), "--timeout", "10"],
        )

        assert result.exit_code == 2
        assert "--timeout requires --wait" in result.output
        assert called is False

    def test_non_finite_wait_timeout_is_a_usage_error(
        self, runner, tmp_xdg_home, mock_keyring
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        result = runner.invoke(
            app,
            ["refresh", str(DATASET_ID), "--wait", "--timeout", "nan"],
        )

        assert result.exit_code == 2
        assert "--timeout must be a finite number greater than 0" in result.output


@pytest.mark.parametrize(
    "code,expected",
    [
        ("refresh_not_applicable", "origin does not support refresh"),
        ("origin_unavailable", "stored source binding is incomplete"),
        ("dataset_busy", "already running"),
        ("origin_changed", "source changed"),
    ],
)
def test_409_refusals_are_actionable(
    code, expected, runner, tmp_xdg_home, mock_keyring, monkeypatch
) -> None:
    from geolens_cli.main import app

    _seed_login(mock_keyring)
    _patch_refresh_endpoint(
        monkeypatch,
        _problem(409, {"code": code, "message": "backend detail"}),
    )

    result = runner.invoke(app, ["refresh", str(DATASET_ID)])

    assert result.exit_code == 1
    assert expected in result.output


def test_credential_store_unavailable_is_a_server_error(
    runner, tmp_xdg_home, mock_keyring, monkeypatch
) -> None:
    from geolens_cli.main import app

    _seed_login(mock_keyring)
    _patch_refresh_endpoint(
        monkeypatch,
        _problem(
            503,
            {
                "code": "credential_store_unavailable",
                "message": "store unavailable",
            },
        ),
    )

    result = runner.invoke(app, ["refresh", str(DATASET_ID)])

    assert result.exit_code == 5
    assert "shared credential store" in result.output


def test_ssrf_refusal_does_not_repeat_the_stored_url(
    runner, tmp_xdg_home, mock_keyring, monkeypatch
) -> None:
    from geolens_cli.main import app

    _seed_login(mock_keyring)
    rejected_url = "http://127.0.0.1/private-source"
    _patch_refresh_endpoint(
        monkeypatch,
        _problem(400, f"Stored source URL is not reachable: {rejected_url}"),
    )

    result = runner.invoke(app, ["refresh", str(DATASET_ID)])

    assert result.exit_code == 1
    assert "network-safety checks" in result.output
    assert rejected_url not in result.output


class TestRefreshWait:
    @staticmethod
    def _timeout_tracking_client():
        class Client:
            def __init__(self, timeouts: list[float] | None = None) -> None:
                self.timeouts = timeouts if timeouts is not None else []
                self.transport = SimpleNamespace(timeout=None)

            def with_timeout(self, timeout: float):
                self.timeouts.append(timeout)
                clone = Client(self.timeouts)
                clone.transport.timeout = timeout
                return clone

            def get_httpx_client(self):
                return self.transport

        return Client()

    def test_default_wait_survives_queue_time_beyond_120_seconds(
        self, monkeypatch
    ) -> None:
        """Without an explicit bound, --wait follows the job to completion.

        Queue time is unbounded, so a healthy job can still be pending or
        running after the old 120-second default without having failed.
        """
        from geolens_cli.refresh import wait_for_refresh

        elapsed = [0.0]
        statuses = iter(("pending", "running", "complete"))

        def next_status(**_kwargs):
            elapsed[0] += 61.0
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(status=next(statuses), error_message=None),
            )

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            next_status,
        )

        result = wait_for_refresh(
            SimpleNamespace(),
            JOB_ID,
            interval=0,
            sleep=lambda _seconds: None,
            monotonic=lambda: elapsed[0],
        )

        assert elapsed[0] == 183.0
        assert result.status == "complete"

    def test_explicit_timeout_still_bounds_the_poll(self, monkeypatch) -> None:
        from geolens_cli.refresh import wait_for_refresh

        elapsed = [0.0]
        client = self._timeout_tracking_client()
        statuses = iter(("pending", "running", "complete"))

        def next_status(**_kwargs):
            elapsed[0] += 61.0
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(status=next(statuses), error_message=None),
            )

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            next_status,
        )

        result = wait_for_refresh(
            client,
            JOB_ID,
            interval=0,
            timeout=120.0,
            sleep=lambda _seconds: None,
            monotonic=lambda: elapsed[0],
        )

        assert elapsed[0] == 122.0
        assert result.status == "timed_out"

    def test_timeout_stops_before_sleeping_past_deadline_or_next_get(
        self, monkeypatch
    ) -> None:
        from geolens_cli.refresh import wait_for_refresh

        elapsed = [0.0]
        requests = [0]
        request_timeouts: list[float] = []
        sleeps: list[float] = []
        client = self._timeout_tracking_client()

        def next_status(**kwargs):
            requests[0] += 1
            request_timeouts.append(kwargs["client"].get_httpx_client().timeout)
            if requests[0] == 1:
                elapsed[0] += 9.75
                status = "pending"
            else:
                status = "complete"
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(status=status, error_message=None),
            )

        def advance_clock(seconds: float) -> None:
            sleeps.append(seconds)
            elapsed[0] += seconds

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            next_status,
        )

        result = wait_for_refresh(
            client,
            JOB_ID,
            interval=1.0,
            timeout=10.0,
            sleep=advance_clock,
            monotonic=lambda: elapsed[0],
        )

        assert result.status == "timed_out"
        assert requests[0] == 1
        assert sleeps == pytest.approx([0.25])
        assert request_timeouts == pytest.approx([10.0])

    def test_each_get_reuses_transport_with_remaining_timeout_budget(
        self, monkeypatch
    ) -> None:
        from geolens_cli.refresh import wait_for_refresh

        elapsed = [0.0]
        client = self._timeout_tracking_client()
        statuses = iter(("pending", "complete"))
        request_clients = []
        request_transports = []
        request_timeouts: list[float] = []

        def next_status(**kwargs):
            request_client = kwargs["client"]
            transport = request_client.get_httpx_client()
            request_clients.append(request_client)
            request_transports.append(transport)
            request_timeouts.append(transport.timeout)
            status = next(statuses)
            if status == "pending":
                elapsed[0] += 4.0
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(status=status, error_message=None),
            )

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            next_status,
        )

        result = wait_for_refresh(
            client,
            JOB_ID,
            interval=1.0,
            timeout=10.0,
            sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
            monotonic=lambda: elapsed[0],
        )

        assert result.status == "complete"
        assert request_clients == [client, client]
        assert request_transports[0] is request_transports[1]
        assert request_timeouts == pytest.approx([10.0, 5.0])
        assert client.timeouts == []
        assert client.transport.timeout is None

    def test_request_timeout_at_deadline_returns_timed_out_json(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        import httpx

        from geolens_cli.main import app
        from geolens_cli.refresh import wait_for_refresh

        _seed_login(mock_keyring)
        _patch_refresh_endpoint(monkeypatch, _accepted())
        elapsed = [0.0]

        def exhaust_request_budget(**_kwargs):
            elapsed[0] = 10.0
            raise httpx.ReadTimeout("request consumed the deadline budget")

        def wait_with_clock(client, job_id, **kwargs):
            return wait_for_refresh(
                client,
                job_id,
                **kwargs,
                sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
                monotonic=lambda: elapsed[0],
            )

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            exhaust_request_budget,
        )
        monkeypatch.setattr("geolens_cli.refresh.wait_for_refresh", wait_with_clock)

        result = runner.invoke(
            app,
            ["--json", "refresh", str(DATASET_ID), "--wait", "--timeout", "10"],
        )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "timed_out"
        assert "check its status later" in payload["error_message"]

    def test_request_timeout_before_deadline_is_retried_not_fatal(
        self, monkeypatch
    ) -> None:
        """fix(#1778 review round 8): a per-request timeout well before
        the operation's own deadline used to exit EXIT_NETWORK
        immediately (call_sdk's default, un-reraised behavior). It is
        now retried via poll_until() as long as the deadline hasn't
        passed — this drives the clock forward on each retry so the
        deadline IS eventually reached, then a successful read resolves
        the wait, proving the timeout alone didn't abort it."""
        import httpx

        from geolens_cli.refresh import RefreshPollResult, wait_for_refresh

        client = self._timeout_tracking_client()
        elapsed = [0.0]
        calls = {"n": 0}

        def flaky(**_kwargs):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise httpx.ReadTimeout("upstream stalled before the CLI deadline")
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(status="complete", error_message=None),
            )

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            flaky,
        )

        result = wait_for_refresh(
            client,
            JOB_ID,
            timeout=100.0,
            sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
            monotonic=lambda: elapsed[0],
        )

        assert result == RefreshPollResult(status="complete")
        assert calls["n"] == 3

    def test_request_timeout_that_never_resolves_exits_at_the_deadline(
        self, monkeypatch
    ) -> None:
        """The counterpart to the retry case above: if EVERY request
        times out, the wait still ends once the operation's own
        deadline is reached, rather than hanging forever."""
        import httpx

        from geolens_cli.refresh import wait_for_refresh

        client = self._timeout_tracking_client()
        elapsed = [0.0]

        def always_slow(**_kwargs):
            raise httpx.ReadTimeout("upstream never responds")

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            always_slow,
        )

        result = wait_for_refresh(
            client,
            JOB_ID,
            timeout=10.0,
            sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
            monotonic=lambda: elapsed[0],
        )

        assert result.status == "timed_out"

    def test_cli_default_wait_passes_no_deadline_to_the_poller(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app
        from geolens_cli.refresh import RefreshPollResult

        _seed_login(mock_keyring)
        _patch_refresh_endpoint(monkeypatch, _accepted())
        seen: dict = {}

        def capture_wait(_client, _job_id, **kwargs):
            seen.update(kwargs)
            return RefreshPollResult(status="complete")

        monkeypatch.setattr("geolens_cli.refresh.wait_for_refresh", capture_wait)

        result = runner.invoke(app, ["refresh", str(DATASET_ID), "--wait"])

        assert result.exit_code == 0, result.output
        assert seen["timeout"] is None

    def test_cli_explicit_timeout_reaches_the_poller(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app
        from geolens_cli.refresh import RefreshPollResult

        _seed_login(mock_keyring)
        _patch_refresh_endpoint(monkeypatch, _accepted())
        seen: dict = {}

        def capture_wait(_client, _job_id, **kwargs):
            seen.update(kwargs)
            return RefreshPollResult(status="complete")

        monkeypatch.setattr("geolens_cli.refresh.wait_for_refresh", capture_wait)

        result = runner.invoke(
            app,
            ["refresh", str(DATASET_ID), "--wait", "--timeout", "30"],
        )

        assert result.exit_code == 0, result.output
        assert seen["timeout"] == 30.0

    def test_wait_reports_terminal_success(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_refresh_endpoint(monkeypatch, _accepted())
        _patch_job(monkeypatch, status="complete")

        result = runner.invoke(
            app,
            ["--json", "refresh", str(DATASET_ID), "--wait"],
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["status"] == "complete"

    def test_failed_job_is_nonzero_and_redacts_the_submitted_token(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        secret = "never-print-this-service-token"
        _patch_refresh_endpoint(monkeypatch, _accepted())
        _patch_job(
            monkeypatch,
            status="failed",
            error_message=f"Upstream rejected credential {secret}",
        )

        result = runner.invoke(
            app,
            ["refresh", str(DATASET_ID), "--token", secret, "--wait"],
        )

        assert result.exit_code == 1
        assert secret not in result.output
        assert "[REDACTED]" in result.output


class TestDatasetStatus:
    @staticmethod
    def _dataset():
        return SimpleNamespace(
            id=DATASET_ID,
            title="Parcels",
            record_status="published",
            origin="service",
            source_freshness="overdue",
            source_health="inaccessible",
            source_health_detail="unauthorized",
            last_refreshed_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
            last_checked_at=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
            update_frequency="daily",
        )

    def _patch_status(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "geolens.api.datasets."
            "get_single_dataset_datasets_dataset_id_get.sync_detailed",
            lambda **_kwargs: SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=self._dataset(),
            ),
        )

    def test_human_status_shows_origin_freshness_and_health(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        self._patch_status(monkeypatch)

        result = runner.invoke(app, ["status", str(DATASET_ID)])

        assert result.exit_code == 0, result.output
        for value in ("service", "overdue", "inaccessible", "unauthorized"):
            assert value in result.output

    def test_quiet_status_suppresses_the_human_table(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        self._patch_status(monkeypatch)

        result = runner.invoke(app, ["--quiet", "status", str(DATASET_ID)])

        assert result.exit_code == 0, result.output
        assert result.output == ""

    def test_json_status_uses_the_shipped_dataset_fields(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        self._patch_status(monkeypatch)

        result = runner.invoke(
            app,
            ["--quiet", "--json", "status", str(DATASET_ID)],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["origin"] == "service"
        assert payload["source_freshness"] == "overdue"
        assert payload["source_health"] == "inaccessible"
        assert payload["source_health_detail"] == "unauthorized"


class TestDatasetStatusRefreshRetry:
    """fix(#1778): `geolens status` now spends a stored refresh token on a
    401 instead of hard-failing — previously only `whoami` did this (D-13),
    so a status check with an expired access token failed even though
    login had stored a refresh token that could have renewed it."""

    def test_expired_token_is_refreshed_and_the_retry_succeeds(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import config as _config
        from geolens_cli.main import app

        mock_keyring[("geolens", INSTANCE)] = "expired-access-token"
        mock_keyring[("geolens", f"{INSTANCE}:refresh")] = "valid-refresh-token"
        _pair_refresh_fingerprint(mock_keyring, "expired-access-token")
        _config.write_default_instance(INSTANCE, username="alice")

        calls = {"status": 0}

        def status_endpoint(**kwargs):
            calls["status"] += 1
            if calls["status"] == 1:
                return SimpleNamespace(status_code=HTTPStatus.UNAUTHORIZED, parsed=None)
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=TestDatasetStatus._dataset(),
            )

        monkeypatch.setattr(
            "geolens.api.datasets."
            "get_single_dataset_datasets_dataset_id_get.sync_detailed",
            status_endpoint,
        )
        monkeypatch.setattr(
            "geolens.api.auth.refresh_auth_refresh_post.sync_detailed",
            lambda **kwargs: SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(
                    access_token="rotated-access-token",
                    refresh_token=None,
                ),
            ),
        )

        result = runner.invoke(app, ["status", str(DATASET_ID)])

        assert result.exit_code == 0, result.output
        assert calls["status"] == 2
        assert mock_keyring[("geolens", INSTANCE)] == "rotated-access-token"

    def test_refresh_failure_still_exits_auth(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import config as _config
        from geolens_cli._sdk_helpers import EXIT_AUTH
        from geolens_cli.main import app

        mock_keyring[("geolens", INSTANCE)] = "expired-access-token"
        mock_keyring[("geolens", f"{INSTANCE}:refresh")] = "stale-refresh-token"
        _config.write_default_instance(INSTANCE, username="alice")

        monkeypatch.setattr(
            "geolens.api.datasets."
            "get_single_dataset_datasets_dataset_id_get.sync_detailed",
            lambda **kwargs: SimpleNamespace(
                status_code=HTTPStatus.UNAUTHORIZED, parsed=None
            ),
        )
        monkeypatch.setattr(
            "geolens.api.auth.refresh_auth_refresh_post.sync_detailed",
            lambda **kwargs: SimpleNamespace(status_code=HTTPStatus.UNAUTHORIZED, parsed=None),
        )

        result = runner.invoke(app, ["status", str(DATASET_ID)])

        assert result.exit_code == EXIT_AUTH, result.output


class TestReauthReviewRoundOne:
    """fix(#1778 review round 1, PR #1802): three follow-ups on
    call_sdk_with_reauth found on the initial review."""

    def test_403_never_triggers_a_refresh(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """A 403 is a real permission denial, not an expired token. Treating
        it like a 401 let a legacy profile holding both an API key and a
        stale refresh token silently retry as a different (renewed-bearer)
        identity instead of surfacing the denial."""
        from geolens_cli import config as _config
        from geolens_cli._sdk_helpers import EXIT_AUTH
        from geolens_cli.main import app

        mock_keyring[("geolens", INSTANCE)] = "current-api-key-holder-token"
        mock_keyring[("geolens", f"{INSTANCE}:refresh")] = "some-refresh-token"
        _config.write_default_instance(INSTANCE, username="alice")

        monkeypatch.setattr(
            "geolens.api.datasets."
            "get_single_dataset_datasets_dataset_id_get.sync_detailed",
            lambda **kwargs: SimpleNamespace(
                status_code=HTTPStatus.FORBIDDEN, parsed=None
            ),
        )

        refresh_calls = {"count": 0}

        def refresh_endpoint(**kwargs):
            refresh_calls["count"] += 1
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(
                    access_token="should-never-be-issued", refresh_token=None
                ),
            )

        monkeypatch.setattr(
            "geolens.api.auth.refresh_auth_refresh_post.sync_detailed",
            refresh_endpoint,
        )

        result = runner.invoke(app, ["status", str(DATASET_ID)])

        assert result.exit_code == EXIT_AUTH, result.output
        assert refresh_calls["count"] == 0, "try_refresh must not run on a 403"

    def test_refresh_request_is_bounded(
        self, tmp_xdg_home, mock_keyring
    ) -> None:
        """try_refresh() used to build its client with the SDK's default
        timeout=None (unbounded), so a stalled refresh endpoint hung the
        calling command forever. The request must carry a finite bound —
        simulated here by a refresh endpoint that raises TimeoutException,
        which try_refresh must absorb into a clean None rather than
        propagating or hanging."""
        import httpx

        from geolens_cli import auth as _auth
        from geolens_cli._sdk_helpers import DEFAULT_HTTP_TIMEOUT_SECONDS

        _auth.store_bearer_token(INSTANCE, "current-bearer")
        _auth.store_refresh_token(
            INSTANCE, "some-refresh-token", bearer_token="current-bearer"
        )

        seen_timeout = None

        def stalled_refresh(**kwargs):
            nonlocal seen_timeout
            seen_timeout = kwargs["client"].get_httpx_client().timeout
            raise httpx.TimeoutException("refresh endpoint never responded")

        import unittest.mock

        with unittest.mock.patch(
            "geolens.api.auth.refresh_auth_refresh_post.sync_detailed",
            stalled_refresh,
        ):
            result = _auth.try_refresh(INSTANCE)

        assert result is None
        assert seen_timeout is not None
        assert seen_timeout == httpx.Timeout(DEFAULT_HTTP_TIMEOUT_SECONDS)

    def test_env_token_401_is_never_refreshed_from_a_stored_session(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#1778 review round 26): this test used to pin the OPPOSITE
        of what it now asserts -- rebuild_client() re-resolved
        credentials from scratch, and a higher-precedence GEOLENS_TOKEN
        env var outranked a stored credential (D-35), so with an expired
        env token and a valid stored refresh token, the retry kept
        resending the SAME expired env token and burned the rotated
        refresh token for nothing. Round 1 "fixed" this by making the
        retry carry the token try_refresh() just returned instead of
        re-resolving -- but that meant an expired GEOLENS_TOKEN silently
        spent a stored login's refresh token and continued the command
        as THAT stored principal, never telling the operator their env
        override was rejected. Round 26: credential_provenance narrows
        the refresh attempt to a STORED bearer session only. An env
        token's 401 is now reported directly, naming GEOLENS_TOKEN, and
        the stored refresh token underneath it is never touched.

        Pin (P2 round 26): env token + 401 + a stored refresh token
        present -> no refresh call, error names GEOLENS_TOKEN, keyring
        (the refresh token entry) untouched."""
        from geolens_cli import config as _config
        from geolens_cli._sdk_helpers import EXIT_AUTH
        from geolens_cli.main import app

        monkeypatch.setenv("GEOLENS_TOKEN", "expired-env-token")
        mock_keyring[("geolens", f"{INSTANCE}:refresh")] = "valid-refresh-token"
        _config.write_default_instance(INSTANCE, username="alice")

        seen_tokens: list[str] = []
        refresh_calls = {"count": 0}

        def status_endpoint(**kwargs):
            seen_tokens.append(kwargs["client"].token)
            return SimpleNamespace(status_code=HTTPStatus.UNAUTHORIZED, parsed=None)

        def refresh_endpoint(**kwargs):
            refresh_calls["count"] += 1
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(
                    access_token="rotated-access-token",
                    refresh_token=None,
                ),
            )

        monkeypatch.setattr(
            "geolens.api.datasets."
            "get_single_dataset_datasets_dataset_id_get.sync_detailed",
            status_endpoint,
        )
        monkeypatch.setattr(
            "geolens.api.auth.refresh_auth_refresh_post.sync_detailed",
            refresh_endpoint,
        )

        result = runner.invoke(app, ["status", str(DATASET_ID)])

        assert result.exit_code == EXIT_AUTH, result.output
        assert "GEOLENS_TOKEN" in result.output
        # Exactly one request -- with the original expired env token --
        # was ever sent; no retry, so no second (rotated) token to see.
        assert seen_tokens == ["expired-env-token"]
        assert refresh_calls["count"] == 0, "the refresh endpoint must never be called"
        assert mock_keyring[("geolens", f"{INSTANCE}:refresh")] == "valid-refresh-token", (
            "the stored refresh token must be untouched"
        )


class TestWhoamiEnvTokenNeverRefreshes:
    """fix(#1778 review round 26): whoami shares call_sdk_with_reauth
    with status -- the same env-token-must-never-refresh rule applies
    there too, exercised through the actual whoami command rather than
    a direct call_sdk_with_reauth unit test."""

    def test_whoami_reports_the_env_token_rejection_without_refreshing(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Pin: env token + 401 + a stored refresh token present ->
        whoami refuses naming GEOLENS_TOKEN, no refresh call, the
        stored refresh token is untouched."""
        from unittest.mock import MagicMock

        import geolens
        import geolens.api.auth.me_auth_me_get as _me_mod
        from geolens_cli._sdk_helpers import EXIT_AUTH
        from geolens_cli.main import app

        monkeypatch.setenv("GEOLENS_TOKEN", "expired-env-token")
        mock_keyring[("geolens", f"{INSTANCE}:refresh")] = "valid-refresh-token"

        monkeypatch.setattr(geolens, "GeolensClient", MagicMock())
        monkeypatch.setattr(
            _me_mod,
            "sync_detailed",
            MagicMock(return_value=SimpleNamespace(status_code=401, parsed=None)),
        )
        refresh_calls = {"count": 0}

        def refresh_endpoint(**kwargs):
            refresh_calls["count"] += 1
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(
                    access_token="rotated-access-token", refresh_token=None
                ),
            )

        monkeypatch.setattr(
            "geolens.api.auth.refresh_auth_refresh_post.sync_detailed",
            refresh_endpoint,
        )

        result = runner.invoke(app, ["--instance", INSTANCE, "whoami"])

        assert result.exit_code == EXIT_AUTH, result.output
        assert "GEOLENS_TOKEN" in result.output
        assert refresh_calls["count"] == 0, "the refresh endpoint must never be called"
        assert mock_keyring[("geolens", f"{INSTANCE}:refresh")] == "valid-refresh-token"


class TestReauthReviewRoundThree:
    """fix(#1778 review round 3, PR #1802): refresh must only be attempted
    for a client authenticated with a bearer token."""

    def test_api_key_client_with_a_stored_refresh_token_never_refreshes_on_401(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """A revoked or mistyped API key gets 401 from _resolve_api_key()
        returning None (not 403 — the backend treats it the same as no
        credential at all). A legacy profile can hold both an API key
        AND an old refresh token; refreshing that unrelated bearer
        session and retrying with it would silently switch identity
        instead of reporting the invalid key."""
        from geolens_cli import config as _config
        from geolens_cli._sdk_helpers import EXIT_AUTH
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        mock_keyring[("geolens", f"{INSTANCE}:api_key")] = "revoked-or-mistyped-key"
        mock_keyring[("geolens", f"{INSTANCE}:refresh")] = "unrelated-stored-refresh-token"
        _config.write_default_instance(INSTANCE, username=None)

        monkeypatch.setattr(
            "geolens.api.datasets."
            "get_single_dataset_datasets_dataset_id_get.sync_detailed",
            lambda **kwargs: SimpleNamespace(
                status_code=HTTPStatus.UNAUTHORIZED, parsed=None
            ),
        )

        refresh_calls = {"count": 0}

        def refresh_endpoint(**kwargs):
            refresh_calls["count"] += 1
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(
                    access_token="should-never-be-issued", refresh_token=None
                ),
            )

        monkeypatch.setattr(
            "geolens.api.auth.refresh_auth_refresh_post.sync_detailed",
            refresh_endpoint,
        )

        result = runner.invoke(app, ["status", str(DATASET_ID)])

        assert result.exit_code == EXIT_AUTH, result.output
        assert refresh_calls["count"] == 0, (
            "try_refresh must not run for an API-key client, even with a "
            "stored refresh token present"
        )

    def test_anonymous_client_never_refreshes_on_401(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """No credential at all is the same story: no bearer session to
        refresh, so nothing should be attempted."""
        from geolens_cli import config as _config
        from geolens_cli._sdk_helpers import EXIT_AUTH
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        mock_keyring[("geolens", f"{INSTANCE}:refresh")] = "unrelated-stored-refresh-token"
        _config.write_default_instance(INSTANCE, username=None)

        monkeypatch.setattr(
            "geolens.api.datasets."
            "get_single_dataset_datasets_dataset_id_get.sync_detailed",
            lambda **kwargs: SimpleNamespace(
                status_code=HTTPStatus.UNAUTHORIZED, parsed=None
            ),
        )

        refresh_calls = {"count": 0}

        def refresh_endpoint(**kwargs):
            refresh_calls["count"] += 1
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(
                    access_token="should-never-be-issued", refresh_token=None
                ),
            )

        monkeypatch.setattr(
            "geolens.api.auth.refresh_auth_refresh_post.sync_detailed",
            refresh_endpoint,
        )

        result = runner.invoke(app, ["status", str(DATASET_ID)])

        assert result.exit_code == EXIT_AUTH, result.output
        assert refresh_calls["count"] == 0

    def test_bearer_client_still_refreshes_on_401(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Sanity check the gate doesn't over-fire: a genuine bearer
        client must still refresh-retry (unchanged from round 1)."""
        from geolens_cli import config as _config
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        mock_keyring[("geolens", INSTANCE)] = "expired-access-token"
        mock_keyring[("geolens", f"{INSTANCE}:refresh")] = "valid-refresh-token"
        _pair_refresh_fingerprint(mock_keyring, "expired-access-token")
        _config.write_default_instance(INSTANCE, username="alice")

        calls = {"status": 0}

        def status_endpoint(**kwargs):
            calls["status"] += 1
            if calls["status"] == 1:
                return SimpleNamespace(status_code=HTTPStatus.UNAUTHORIZED, parsed=None)
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=TestDatasetStatus._dataset(),
            )

        monkeypatch.setattr(
            "geolens.api.datasets."
            "get_single_dataset_datasets_dataset_id_get.sync_detailed",
            status_endpoint,
        )
        monkeypatch.setattr(
            "geolens.api.auth.refresh_auth_refresh_post.sync_detailed",
            lambda **kwargs: SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(
                    access_token="rotated-access-token", refresh_token=None
                ),
            ),
        )

        result = runner.invoke(app, ["status", str(DATASET_ID)])

        assert result.exit_code == 0, result.output
        assert calls["status"] == 2


class TestRefreshPersistenceFailureNeverCrashes:
    """fix(#1778 round 29): try_refresh()'s optional-return contract
    ("None on failure, never raise") covered the HTTP call and response
    parsing, but not the actual PERSISTENCE of a successful rotation --
    store_bearer_token()/store_refresh_token() propagate uncaught when
    a sink genuinely cannot be written (keyring locked AND the
    credentials.toml fallback also fails). The only caller
    (_sdk_helpers.call_sdk_with_reauth) does not catch storage
    exceptions, so a command already deep in its own request handling
    died with an unrelated traceback -- AFTER the server had already
    rotated the refresh token server-side, which is worse than an
    ordinary failed refresh: the old refresh token is now invalid too.

    Parametrized over every persistence sink named in the finding
    (bearer write, refresh-token write, an unwritable credentials.toml
    specifically) x both callers of try_refresh() through
    call_sdk_with_reauth (whoami, status). manifest apply's own retry
    path was also audited: it never calls call_sdk_with_reauth (plain
    call_sdk only, no reauth), so there is nothing to parametrize
    there."""

    def _break_bearer_sink(self, monkeypatch, mock_keyring) -> None:
        """The original session is keyring-backed; both the keyring
        write and the file fallback fail for the bearer account --
        store_bearer_token() has nowhere left to land the new access
        token."""
        from geolens_cli import auth as _auth
        from keyring.errors import KeyringError

        mock_keyring[("geolens", INSTANCE)] = "expired-access-token"
        mock_keyring[("geolens", f"{INSTANCE}:refresh")] = "valid-refresh-token"
        _pair_refresh_fingerprint(mock_keyring, "expired-access-token")

        monkeypatch.setattr(
            "keyring.set_password",
            lambda *a, **k: (_ for _ in ()).throw(KeyringError("keyring locked")),
        )
        monkeypatch.setattr(
            _auth,
            "_write_credentials_file",
            lambda *a, **k: (_ for _ in ()).throw(OSError("read-only file system")),
        )

    def _break_refresh_sink(self, monkeypatch, mock_keyring) -> None:
        """The original session is keyring-backed; the bearer write
        succeeds (keyring is fine for that account), but the refresh-
        token write's OWN keyring account is separately broken and the
        file fallback also fails."""
        from geolens_cli import auth as _auth
        from keyring.errors import KeyringError

        mock_keyring[("geolens", INSTANCE)] = "expired-access-token"
        mock_keyring[("geolens", f"{INSTANCE}:refresh")] = "valid-refresh-token"
        _pair_refresh_fingerprint(mock_keyring, "expired-access-token")

        real_set_password = __import__("keyring").set_password

        def flaky_set_password(service, account, value):
            if account.endswith(":refresh"):
                raise KeyringError("keyring locked for this account")
            return real_set_password(service, account, value)

        monkeypatch.setattr("keyring.set_password", flaky_set_password)
        monkeypatch.setattr(
            _auth,
            "_write_credentials_file",
            lambda *a, **k: (_ for _ in ()).throw(OSError("read-only file system")),
        )

    def _break_credentials_file_sink(self, monkeypatch, mock_keyring) -> None:
        """The ORIGINAL session is FILE-backed (--no-keyring login, or
        an unavailable keyring at the time), per _detect_credential_
        backend, so no_keyring=True forces both writes straight to
        credentials.toml with no keyring leg to fall back to -- and
        the file itself has since become unwritable."""
        from geolens_cli import auth as _auth

        _auth.store_bearer_token(INSTANCE, "expired-access-token", no_keyring=True)
        _auth.store_refresh_token(
            INSTANCE,
            "valid-refresh-token",
            bearer_token="expired-access-token",
            no_keyring=True,
        )

        monkeypatch.setattr(
            _auth,
            "_write_credentials_file",
            lambda *a, **k: (_ for _ in ()).throw(OSError("read-only file system")),
        )

    _SINKS = {
        "bearer_keyring_and_file_fail": _break_bearer_sink,
        "refresh_keyring_and_file_fail": _break_refresh_sink,
        "credentials_file_unwritable": _break_credentials_file_sink,
    }

    def _setup_refresh_endpoint(self, monkeypatch) -> dict:
        calls = {"count": 0}

        def refresh_endpoint(**kwargs):
            calls["count"] += 1
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(
                    access_token="rotated-access-token",
                    refresh_token="rotated-refresh-token",
                ),
            )

        monkeypatch.setattr(
            "geolens.api.auth.refresh_auth_refresh_post.sync_detailed",
            refresh_endpoint,
        )
        return calls

    @pytest.mark.parametrize("sink", sorted(_SINKS))
    @pytest.mark.parametrize("caller", ["whoami", "status"])
    def test_a_storage_failure_after_a_successful_rotation_never_crashes(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sink: str, caller: str
    ) -> None:
        from geolens_cli import auth as _auth
        from geolens_cli import config as _config
        from geolens_cli._sdk_helpers import EXIT_AUTH
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        _config.write_default_instance(INSTANCE, username="alice")

        self._SINKS[sink](self, monkeypatch, mock_keyring)
        refresh_calls = self._setup_refresh_endpoint(monkeypatch)

        warnings: list[str] = []
        original_warning = _auth.log.warning

        def spying_warning(event, **kwargs):
            warnings.append(event)
            return original_warning(event, **kwargs)

        monkeypatch.setattr(_auth.log, "warning", spying_warning)

        if caller == "whoami":
            import geolens
            import geolens.api.auth.me_auth_me_get as _me_mod
            from unittest.mock import MagicMock

            monkeypatch.setattr(geolens, "GeolensClient", MagicMock())
            monkeypatch.setattr(
                _me_mod,
                "sync_detailed",
                MagicMock(
                    return_value=SimpleNamespace(status_code=HTTPStatus.UNAUTHORIZED, parsed=None)
                ),
            )
            result = runner.invoke(app, ["--instance", INSTANCE, "whoami"])
        else:
            monkeypatch.setattr(
                "geolens.api.datasets."
                "get_single_dataset_datasets_dataset_id_get.sync_detailed",
                lambda **kwargs: SimpleNamespace(
                    status_code=HTTPStatus.UNAUTHORIZED, parsed=None
                ),
            )
            result = runner.invoke(app, ["status", str(DATASET_ID)])

        # No traceback: typer/click only ever produces a clean exit
        # this way when nothing propagated out uncaught.
        assert result.exception is None or isinstance(result.exception, SystemExit), (
            f"an exception escaped: {result.exception!r}"
        )
        assert result.exit_code == EXIT_AUTH, result.output
        # The refresh endpoint really was called (the rotation this
        # test is about genuinely happened server-side) -- the bug this
        # closes is specifically about what happens AFTER that succeeds.
        assert refresh_calls["count"] == 1
        # Exactly one warning explaining the situation, not a crash.
        assert warnings.count("refresh_rotated_but_not_stored") == 1


def _setup_bearer_provenance(mock_keyring: dict, monkeypatch, provenance: str) -> str:
    """Store a bearer credential per `provenance` and return its value
    (the value try_refresh() must PROVE a refresh token is paired
    with). "interactive" and "manual" are both keyring-stored bearers
    -- they produce the IDENTICAL credential_provenance == "stored-
    bearer" tag (round 26 does not distinguish HOW a stored bearer got
    there, only THAT it's stored vs. env) -- given distinct literal
    values purely so each row's setup and assertions read clearly."""
    if provenance == "env":
        monkeypatch.setenv("GEOLENS_TOKEN", "env-bearer-token")
        return "env-bearer-token"
    monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
    bearer = "interactive-bearer-token" if provenance == "interactive" else "manual-bearer-token"
    mock_keyring[("geolens", INSTANCE)] = bearer
    return bearer


def _setup_refresh_state(mock_keyring: dict, current_bearer: str, refresh_state: str) -> None:
    """Construct the refresh-token/fingerprint state named by
    `refresh_state`, relative to `current_bearer` (the bearer this
    test row just stored)."""
    from geolens_cli import auth as _auth

    if refresh_state == "absent":
        return
    mock_keyring[("geolens", f"{INSTANCE}:refresh")] = "some-refresh-token"
    if refresh_state == "paired":
        mock_keyring[("geolens", f"{INSTANCE}:refresh_fp")] = _auth._fingerprint_bearer(
            current_bearer
        )
    elif refresh_state == "unpaired-legacy":
        pass  # No fingerprint field at all -- a pre-round-31 profile.
    elif refresh_state == "mismatched":
        mock_keyring[("geolens", f"{INSTANCE}:refresh_fp")] = _auth._fingerprint_bearer(
            "some-other-stale-bearer"
        )
    else:
        raise AssertionError(f"unhandled refresh_state: {refresh_state!r}")


# fix(#1778 round 31): the refresh-pairing dimension of the credential-
# resolution matrix. Keys are (bearer_provenance, refresh_state); the
# value is whether try_refresh() may spend the refresh token (True) or
# must discard it and report the normal auth error with NO refresh
# call made (False).
#
# "interactive" and "manual" both resolve to credential_provenance ==
# "stored-bearer" (round 26 does not track HOW a stored bearer got
# there) -- the pairing mechanism (round 31) is intentionally NOT a
# provenance flag, only a fingerprint proving "this refresh token
# belongs to the CURRENTLY stored bearer." (manual, paired) is
# therefore a SYNTHETIC row: a real `login --token`/`--api-key` never
# calls store_refresh_token() at all (the server does not issue a
# refresh token for a manually-supplied credential), so this exact
# state cannot arise from ordinary command usage -- it is included to
# prove the mechanism is purely state-based, not provenance-based, and
# it legitimately succeeds under that mechanism. (manual, unpaired-
# legacy) and (manual, mismatched) ARE the realistic finding scenario:
# a stale refresh token an earlier interactive login left behind,
# surviving a later `login --token`/`--api-key` that never cleared it.
# "env" never reaches try_refresh() at all (round 26 gates on
# credential_provenance == "stored-bearer" before ever consulting a
# refresh token), so every env row is False regardless of refresh_state.
REFRESH_MATRIX = {
    ("interactive", "absent"): False,
    ("interactive", "paired"): True,
    ("interactive", "unpaired-legacy"): False,
    ("interactive", "mismatched"): False,
    ("manual", "absent"): False,
    ("manual", "paired"): True,
    ("manual", "unpaired-legacy"): False,
    ("manual", "mismatched"): False,
    ("env", "absent"): False,
    ("env", "paired"): False,
    ("env", "unpaired-legacy"): False,
    ("env", "mismatched"): False,
}


class TestRefreshPairingMatrix:
    """fix(#1778 round 31): the class-closing test for the refresh-
    pairing dimension, extending round 30's credential-resolution
    matrix. 12 rows: refresh in {absent, paired, unpaired-legacy,
    mismatched} x bearer provenance {interactive, manual, env}. Only
    a stored bearer with a correctly PAIRED refresh token may refresh;
    every other row ends in the normal auth error (EXIT_AUTH) with the
    refresh endpoint never called."""

    @pytest.mark.parametrize(
        "provenance,refresh_state", sorted(REFRESH_MATRIX), ids=lambda v: str(v)
    )
    def test_refresh_pairing_row(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        provenance: str,
        refresh_state: str,
    ) -> None:
        from geolens_cli import config as _config
        from geolens_cli._sdk_helpers import EXIT_AUTH
        from geolens_cli.main import app

        current_bearer = _setup_bearer_provenance(mock_keyring, monkeypatch, provenance)
        _setup_refresh_state(mock_keyring, current_bearer, refresh_state)
        _config.write_default_instance(INSTANCE, username="alice")

        refresh_calls = {"count": 0}

        def refresh_endpoint(**kwargs):
            refresh_calls["count"] += 1
            return SimpleNamespace(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(
                    access_token="rotated-access-token", refresh_token=None
                ),
            )

        monkeypatch.setattr(
            "geolens.api.auth.refresh_auth_refresh_post.sync_detailed",
            refresh_endpoint,
        )

        calls = {"status": 0}

        def status_endpoint(**kwargs):
            calls["status"] += 1
            if calls["status"] == 1:
                return SimpleNamespace(status_code=HTTPStatus.UNAUTHORIZED, parsed=None)
            return SimpleNamespace(
                status_code=HTTPStatus.OK, parsed=TestDatasetStatus._dataset()
            )

        monkeypatch.setattr(
            "geolens.api.datasets."
            "get_single_dataset_datasets_dataset_id_get.sync_detailed",
            status_endpoint,
        )

        result = runner.invoke(app, ["status", str(DATASET_ID)])

        should_succeed = REFRESH_MATRIX[(provenance, refresh_state)]
        if should_succeed:
            assert result.exit_code == 0, result.output
            assert refresh_calls["count"] == 1, (provenance, refresh_state)
        else:
            assert result.exit_code == EXIT_AUTH, result.output
            assert refresh_calls["count"] == 0, (
                provenance,
                refresh_state,
                "the refresh endpoint must never be called on this row",
            )
