"""OCCLI-04: publish unit tests with mocked SDK.

Plan 04 Task 1 covers the publish.py module surface (MIME guesser,
multipart upload, CommitRequest builder, dataset URL construction, 409
handler). Plan 04 Task 2 covers the publish command body wired into
main.py and the rich.Progress UI.

Hand-maintained — NOT regenerated.
"""
from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest


# ---------------------------------------------------------------------------
# Task 1 — publish.py module surface
# ---------------------------------------------------------------------------


class TestGuessMime:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("a.geojson", "application/geo+json"),
            ("b.json", "application/json"),
            ("c.gpkg", "application/geopackage+sqlite3"),
            ("d.tif", "image/tiff"),
            ("e.tiff", "image/tiff"),
            ("f.zip", "application/zip"),
            ("g.csv", "text/csv"),
        ],
    )
    def test_known_extensions(self, name: str, expected: str) -> None:
        from geolens_cli.publish import guess_mime

        assert guess_mime(Path(name)) == expected

    def test_unknown_extension_falls_back(self) -> None:
        from geolens_cli.publish import guess_mime

        # mimetypes may guess something for .txt; either way the result is a
        # non-empty string and the function does not raise.
        result = guess_mime(Path("notes.txt"))
        assert isinstance(result, str)
        assert len(result) > 0

    def test_no_extension_yields_octet_stream(self) -> None:
        from geolens_cli.publish import guess_mime

        assert guess_mime(Path("noext")) == "application/octet-stream"


class TestConstructDatasetUrl:
    def test_uses_resolved_dataset_id_when_present(self) -> None:
        from geolens_cli.publish import construct_dataset_url

        url = construct_dataset_url(
            "https://x.example.com",
            dataset_id="ds-abc-123",
            job_id="job-9",
        )
        assert url == "https://x.example.com/datasets/ds-abc-123"

    def test_strips_trailing_slash(self) -> None:
        from geolens_cli.publish import construct_dataset_url

        url = construct_dataset_url(
            "https://x.example.com/",
            dataset_id="ds-abc-123",
            job_id="job-9",
        )
        assert url == "https://x.example.com/datasets/ds-abc-123"

    def test_falls_back_to_job_search_when_no_dataset_id(self) -> None:
        from geolens_cli.publish import construct_dataset_url

        url = construct_dataset_url(
            "https://x.example.com",
            dataset_id=None,
            job_id="job-9",
        )
        assert "job_id=job-9" in url
        assert url.startswith("https://x.example.com/datasets")


class TestBuildCommitRequest:
    def test_title_only(self) -> None:
        from geolens_cli.publish import build_commit_request

        req = build_commit_request(title="cities", description=None)
        assert req.title == "cities"

    def test_description_maps_to_summary(self) -> None:
        from geolens_cli.publish import build_commit_request

        req = build_commit_request(title="cities", description="my dataset")
        # Plan 04 Task 0 Q2: description→summary mapping (CommitRequest has
        # `summary`, not `description`).
        assert req.summary == "my dataset"

    def test_no_description_leaves_summary_unset(self) -> None:
        from geolens_cli.publish import build_commit_request
        from geolens_sdk.types import UNSET

        req = build_commit_request(title="cities", description=None)
        # When summary isn't supplied, the field stays UNSET so it never
        # serializes onto the wire (CommitRequest.to_dict skips UNSET fields).
        assert req.summary is UNSET


class TestHandleCommitAlreadyProcessed:
    def test_exits_generic_with_message(self) -> None:
        import typer

        from geolens_cli.publish import handle_commit_already_processed
        from geolens_cli._sdk_helpers import EXIT_GENERIC

        output = MagicMock()
        with pytest.raises(typer.Exit) as exc_info:
            handle_commit_already_processed("job-dupe", output)
        assert exc_info.value.exit_code == EXIT_GENERIC
        # The message must mention the job_id and the "already committed"
        # phrase so the user can grep their shell history.
        output.error.assert_called_once()
        msg = output.error.call_args[0][0]
        assert "job-dupe" in msg
        assert "already committed" in msg


class TestIsDuplicateCommitResponse:
    """The detection helper — defensive on 400 OR 409 with matching detail."""

    def test_400_with_already_processed_detail(self) -> None:
        from geolens_cli.publish import is_duplicate_commit_response

        resp = MagicMock(status_code=HTTPStatus.BAD_REQUEST, parsed=MagicMock(detail="Job already processed"))
        # Make isinstance(resp.parsed, ProblemDetail) work for the helper:
        from geolens_sdk.models.problem_detail import ProblemDetail
        resp.parsed = ProblemDetail(detail="Job already processed", status=400, title="Bad Request", type_="about:blank")
        resp.status_code = HTTPStatus.BAD_REQUEST
        assert is_duplicate_commit_response(resp) is True

    def test_409_with_already_processed_detail(self) -> None:
        from geolens_cli.publish import is_duplicate_commit_response
        from geolens_sdk.models.problem_detail import ProblemDetail

        resp = MagicMock()
        resp.status_code = HTTPStatus.CONFLICT
        resp.parsed = ProblemDetail(detail="Job already processed", status=409, title="Conflict", type_="about:blank")
        assert is_duplicate_commit_response(resp) is True

    def test_400_with_unrelated_detail_returns_false(self) -> None:
        from geolens_cli.publish import is_duplicate_commit_response
        from geolens_sdk.models.problem_detail import ProblemDetail

        resp = MagicMock()
        resp.status_code = HTTPStatus.BAD_REQUEST
        resp.parsed = ProblemDetail(detail="Validation failed", status=400, title="Bad Request", type_="about:blank")
        assert is_duplicate_commit_response(resp) is False

    def test_202_returns_false(self) -> None:
        from geolens_cli.publish import is_duplicate_commit_response

        resp = MagicMock()
        resp.status_code = HTTPStatus.ACCEPTED
        resp.parsed = None
        assert is_duplicate_commit_response(resp) is False


class TestUploadFile:
    """upload_file uses the SDK-owned httpx client (OCCLI-06 invariant)."""

    def test_upload_file_calls_sdk_get_httpx_client(self, tmp_path: Path) -> None:
        from geolens_cli.publish import upload_file

        sample = tmp_path / "cities.geojson"
        sample.write_text('{"type":"FeatureCollection","features":[]}')

        # Mock the SDK client's get_httpx_client method
        mock_httpx = MagicMock()
        raw_response = MagicMock()
        raw_response.status_code = 201
        raw_response.content = b'{"job_id":"00000000-0000-0000-0000-000000000001","status":"pending","message":"ok"}'
        raw_response.headers = {}
        raw_response.json.return_value = {
            "job_id": "00000000-0000-0000-0000-000000000001",
            "status": "pending",
            "message": "ok",
        }
        mock_httpx.post.return_value = raw_response

        sdk_client = MagicMock()
        sdk_client.get_httpx_client.return_value = mock_httpx
        sdk_client.raise_on_unexpected_status = False

        result = upload_file(sdk_client, sample)

        # Confirms get_httpx_client() was used (NOT a direct httpx import).
        sdk_client.get_httpx_client.assert_called_once()
        # Confirms the multipart workaround was applied (files= not body=).
        post_call = mock_httpx.post.call_args
        assert post_call.args[0] == "/ingest/upload"
        assert "files" in post_call.kwargs
        files = post_call.kwargs["files"]
        # files["file"] is a (name, fh, mime) tuple
        assert files["file"][0] == "cities.geojson"
        assert files["file"][2] == "application/geo+json"
        # Result has the SDK Response shape
        assert int(result.status_code) == 201


# ---------------------------------------------------------------------------
# Task 2 — geolens publish CLI command body
# ---------------------------------------------------------------------------


def _seed_login(instance: str, mock_keyring: dict) -> None:
    """Pre-seed login state so `state.sdk()` returns a valid client."""
    from geolens_cli import config as _config

    # Drop a token directly into the in-memory keyring fixture and write
    # config.toml so AppState.active_instance() resolves the URL.
    mock_keyring[("geolens", instance)] = "tok-abc"
    _config.write_default_instance(instance, username="alice")


@pytest.fixture
def sample_geojson(tmp_path: Path) -> Path:
    f = tmp_path / "cities.geojson"
    f.write_text('{"type":"FeatureCollection","features":[]}')
    return f


@pytest.fixture
def patch_sdk_for_publish(monkeypatch):
    """Returns a helper to install the three SDK function mocks.

    The helper takes upload/preview/commit/job_status mocks and patches:
      - geolens_cli.publish.upload_file
      - geolens_sdk.api.datasets.preview_file_ingest_preview_job_id_post.sync_detailed
      - geolens_sdk.api.datasets.commit_import_ingest_commit_job_id_post.sync_detailed
      - geolens_sdk.api.admin.get_job_status_jobs_job_id_get.sync_detailed
    """

    def _install(*, upload, preview, commit, job_status=None):
        monkeypatch.setattr("geolens_cli.publish.upload_file", lambda c, p: upload)
        monkeypatch.setattr(
            "geolens_sdk.api.datasets.preview_file_ingest_preview_job_id_post.sync_detailed",
            lambda **kw: preview,
        )
        monkeypatch.setattr(
            "geolens_sdk.api.datasets.commit_import_ingest_commit_job_id_post.sync_detailed",
            lambda **kw: commit,
        )
        if job_status is not None:
            monkeypatch.setattr(
                "geolens_sdk.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
                lambda **kw: job_status,
            )

    return _install


def _ok_upload(job_id: str = "00000000-0000-0000-0000-000000000001"):
    from geolens_cli import publish as _publish

    parsed = MagicMock()
    parsed.job_id = UUID(job_id)
    return MagicMock(status_code=HTTPStatus(_publish.UPLOAD_OK_STATUS), parsed=parsed)


def _ok_preview():
    from geolens_cli import publish as _publish

    return MagicMock(status_code=HTTPStatus(_publish.PREVIEW_OK_STATUS), parsed=MagicMock())


def _ok_commit(job_id: str = "00000000-0000-0000-0000-000000000001"):
    from geolens_cli import publish as _publish

    parsed = MagicMock()
    parsed.job_id = UUID(job_id)
    parsed.status = "pending"
    parsed.message = "Import queued"
    return MagicMock(status_code=HTTPStatus(_publish.COMMIT_OK_STATUS), parsed=parsed)


def _ok_job_status(dataset_id: str | None, status: str = "completed"):
    from geolens_cli import publish as _publish

    parsed = MagicMock()
    parsed.dataset_id = UUID(dataset_id) if dataset_id else None
    parsed.status = status
    return MagicMock(status_code=HTTPStatus(_publish.JOB_STATUS_OK_STATUS), parsed=parsed)


class TestPublishCli:
    def test_no_instance_exits_auth_error(
        self, runner, tmp_xdg_home, mock_keyring, sample_geojson, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        # No login state seeded — AppState.sdk() raises typer.BadParameter
        # which Typer translates to exit 2.
        monkeypatch.delenv("GEOLENS_INSTANCE", raising=False)
        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code != 0, result.output

    def test_publish_success_prints_dataset_url(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson, patch_sdk_for_publish
    ) -> None:
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(dataset_id="00000000-0000-0000-0000-000000000042"),
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 0, result.output
        assert "https://x.example.com/datasets/00000000-0000-0000-0000-000000000042" in result.output

    def test_publish_no_wait_emits_job_search_url(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson, patch_sdk_for_publish
    ) -> None:
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)
        # --no-wait skips the job-status poll; URL falls back to job-search form
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
        )

        result = runner.invoke(app, ["publish", str(sample_geojson), "--no-wait"])
        assert result.exit_code == 0, result.output
        assert "job_id=00000000-0000-0000-0000-000000000001" in result.output

    def test_publish_409_exits_generic(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson, patch_sdk_for_publish
    ) -> None:
        from geolens_cli.main import app
        from geolens_sdk.models.problem_detail import ProblemDetail

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)

        # Backend actually returns 400 for already-processed (per Task 0 Q3)
        # but we exercise the 409 branch defensively here.
        commit_dup = MagicMock()
        commit_dup.status_code = HTTPStatus.CONFLICT
        commit_dup.parsed = ProblemDetail(
            detail="Job already processed",
            status=409,
            title="Conflict",
            type_="about:blank",
        )

        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=commit_dup,
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 1, result.output
        assert "already committed" in result.output

    def test_publish_400_already_processed_exits_generic(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson, patch_sdk_for_publish
    ) -> None:
        """Task 0 Q3: backend actually emits 400 (not 409) for duplicate commits."""
        from geolens_cli.main import app
        from geolens_sdk.models.problem_detail import ProblemDetail

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)

        commit_dup = MagicMock()
        commit_dup.status_code = HTTPStatus.BAD_REQUEST
        commit_dup.parsed = ProblemDetail(
            detail="Job already processed",
            status=400,
            title="Bad Request",
            type_="about:blank",
        )

        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=commit_dup,
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 1, result.output
        assert "already committed" in result.output

    def test_progress_suppressed_non_tty(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson, patch_sdk_for_publish
    ) -> None:
        """CliRunner output is not a TTY; rich.Progress(disable=True) emits nothing."""
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(dataset_id="00000000-0000-0000-0000-000000000042"),
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 0, result.output
        for spinner in ("⠋", "⠙", "⠚", "⠞", "⠦", "⠧"):
            assert spinner not in result.output

    def test_json_mode_emits_payload(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson, patch_sdk_for_publish
    ) -> None:
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(dataset_id="00000000-0000-0000-0000-000000000042"),
        )

        result = runner.invoke(app, ["--json", "publish", str(sample_geojson)])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["dataset_url"].endswith("/datasets/00000000-0000-0000-0000-000000000042")
        assert payload["job_id"] == "00000000-0000-0000-0000-000000000001"

    def test_publish_uses_filename_stem_when_no_name(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson, patch_sdk_for_publish
    ) -> None:
        """The CommitRequest title falls back to file.stem when --name is omitted."""
        from geolens_cli.main import app
        from geolens_sdk.models.commit_request import CommitRequest

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)

        captured: dict = {}

        def capture_commit(**kw):
            captured["body"] = kw["body"]
            from geolens_cli import publish as _publish

            return MagicMock(
                status_code=HTTPStatus(_publish.COMMIT_OK_STATUS),
                parsed=MagicMock(
                    job_id=UUID("00000000-0000-0000-0000-000000000001"),
                    status="pending",
                    message="ok",
                ),
            )

        monkeypatch.setattr("geolens_cli.publish.upload_file", lambda c, p: _ok_upload())
        monkeypatch.setattr(
            "geolens_sdk.api.datasets.preview_file_ingest_preview_job_id_post.sync_detailed",
            lambda **kw: _ok_preview(),
        )
        monkeypatch.setattr(
            "geolens_sdk.api.datasets.commit_import_ingest_commit_job_id_post.sync_detailed",
            capture_commit,
        )

        result = runner.invoke(app, ["publish", str(sample_geojson), "--no-wait"])
        assert result.exit_code == 0, result.output
        assert isinstance(captured["body"], CommitRequest)
        assert captured["body"].title == "cities"  # file stem of cities.geojson

    def test_publish_name_overrides_title(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app
        from geolens_sdk.models.commit_request import CommitRequest

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)

        captured: dict = {}

        def capture_commit(**kw):
            captured["body"] = kw["body"]
            from geolens_cli import publish as _publish

            return MagicMock(
                status_code=HTTPStatus(_publish.COMMIT_OK_STATUS),
                parsed=MagicMock(
                    job_id=UUID("00000000-0000-0000-0000-000000000001"),
                    status="pending",
                    message="ok",
                ),
            )

        monkeypatch.setattr("geolens_cli.publish.upload_file", lambda c, p: _ok_upload())
        monkeypatch.setattr(
            "geolens_sdk.api.datasets.preview_file_ingest_preview_job_id_post.sync_detailed",
            lambda **kw: _ok_preview(),
        )
        monkeypatch.setattr(
            "geolens_sdk.api.datasets.commit_import_ingest_commit_job_id_post.sync_detailed",
            capture_commit,
        )

        result = runner.invoke(
            app, ["publish", str(sample_geojson), "--name", "My Cities", "--description", "hello", "--no-wait"]
        )
        assert result.exit_code == 0, result.output
        assert isinstance(captured["body"], CommitRequest)
        assert captured["body"].title == "My Cities"
        assert captured["body"].summary == "hello"
