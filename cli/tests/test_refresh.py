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

    def test_request_timeout_before_deadline_remains_a_network_error(
        self, monkeypatch
    ) -> None:
        import httpx
        import typer

        from geolens_cli._sdk_helpers import EXIT_NETWORK
        from geolens_cli.refresh import wait_for_refresh

        client = self._timeout_tracking_client()

        def timeout_before_deadline(**_kwargs):
            raise httpx.ReadTimeout("upstream stalled before the CLI deadline")

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            timeout_before_deadline,
        )

        with pytest.raises(typer.Exit) as exc_info:
            wait_for_refresh(
                client,
                JOB_ID,
                timeout=10.0,
                monotonic=lambda: 0.0,
            )

        assert exc_info.value.exit_code == EXIT_NETWORK

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
