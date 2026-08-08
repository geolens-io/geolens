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
        assert "--timeout must be finite" in result.output


@pytest.mark.parametrize(
    "code,expected",
    [
        ("refresh_not_applicable", "no refreshable service origin"),
        ("origin_unavailable", "stored service binding is incomplete"),
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

    def test_json_status_uses_the_shipped_dataset_fields(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        self._patch_status(monkeypatch)

        result = runner.invoke(app, ["--json", "status", str(DATASET_ID)])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["origin"] == "service"
        assert payload["source_freshness"] == "overdue"
        assert payload["source_health"] == "inaccessible"
        assert payload["source_health_detail"] == "unauthorized"
