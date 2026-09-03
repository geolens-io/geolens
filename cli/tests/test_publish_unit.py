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
            ("h.kml", "application/vnd.google-earth.kml+xml"),
            ("i.kmz", "application/vnd.google-earth.kmz"),
            ("j.fgb", "application/vnd.flatgeobuf"),
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

    def test_fix588_drops_the_canonical_api_suffix_for_the_web_url(self) -> None:
        """The stored instance is always /api-suffixed; the printed URL must
        point at the browser page, not the JSON endpoint."""
        from geolens_cli.publish import construct_dataset_url

        assert (
            construct_dataset_url(
                "http://localhost:8080/api", dataset_id="ds-1", job_id="j"
            )
            == "http://localhost:8080/datasets/ds-1"
        )
        # subpath deployments keep their prefix
        assert (
            construct_dataset_url(
                "https://x.example.com/geolens/api", dataset_id="ds-1", job_id="j"
            )
            == "https://x.example.com/geolens/datasets/ds-1"
        )
        # no-dataset-id fallback strips it too
        assert (
            construct_dataset_url(
                "http://localhost:8080/api", dataset_id=None, job_id="j9"
            )
            == "http://localhost:8080/datasets?job_id=j9"
        )

    def test_fix588_leaves_a_host_named_api_alone(self) -> None:
        from geolens_cli.publish import construct_dataset_url

        # Path-segment aware: 'api' as the HOST is not a trailing /api path.
        assert (
            construct_dataset_url(
                "https://api.example.com", dataset_id="ds-1", job_id="j"
            )
            == "https://api.example.com/datasets/ds-1"
        )
        assert (
            construct_dataset_url("http://api", dataset_id="ds-1", job_id="j")
            == "http://api/datasets/ds-1"
        )
        # …but a real /api path segment on such a host still goes
        assert (
            construct_dataset_url(
                "https://api.example.com/api", dataset_id="ds-1", job_id="j"
            )
            == "https://api.example.com/datasets/ds-1"
        )


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
        from geolens.types import UNSET

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

        resp = MagicMock(
            status_code=HTTPStatus.BAD_REQUEST,
            parsed=MagicMock(detail="Job already processed"),
        )
        # Make isinstance(resp.parsed, ProblemDetail) work for the helper:
        from geolens.models.problem_detail import ProblemDetail

        resp.parsed = ProblemDetail(
            detail="Job already processed",
            status=400,
            title="Bad Request",
            type_="about:blank",
        )
        resp.status_code = HTTPStatus.BAD_REQUEST
        assert is_duplicate_commit_response(resp) is True

    def test_409_with_already_processed_detail(self) -> None:
        from geolens_cli.publish import is_duplicate_commit_response
        from geolens.models.problem_detail import ProblemDetail

        resp = MagicMock()
        resp.status_code = HTTPStatus.CONFLICT
        resp.parsed = ProblemDetail(
            detail="Job already processed",
            status=409,
            title="Conflict",
            type_="about:blank",
        )
        assert is_duplicate_commit_response(resp) is True

    def test_400_with_unrelated_detail_returns_false(self) -> None:
        from geolens_cli.publish import is_duplicate_commit_response
        from geolens.models.problem_detail import ProblemDetail

        resp = MagicMock()
        resp.status_code = HTTPStatus.BAD_REQUEST
        resp.parsed = ProblemDetail(
            detail="Validation failed",
            status=400,
            title="Bad Request",
            type_="about:blank",
        )
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

    def test_upload_raises_the_timeout_then_restores_it(
        self, tmp_path: Path
    ) -> None:
        """fix(#1778): AppState.sdk() now bounds every request to
        _sdk_helpers.DEFAULT_HTTP_TIMEOUT_SECONDS (30s), too short for a
        large geospatial file on an ordinary connection. upload_file()
        must raise the bound for the POST itself and put the original
        value back afterward, so a later request on this same client
        (preview/commit/poll) is not left with the upload's longer bound.
        """
        from geolens_cli._sdk_helpers import EXTENDED_REQUEST_TIMEOUT_SECONDS
        from geolens_cli.publish import upload_file

        sample = tmp_path / "cities.geojson"
        sample.write_text('{"type":"FeatureCollection","features":[]}')

        seen_timeout_during_post = None

        mock_httpx = MagicMock()
        mock_httpx.timeout = 30.0  # AppState.sdk()'s default bound

        def fake_post(*args, **kwargs):
            nonlocal seen_timeout_during_post
            seen_timeout_during_post = mock_httpx.timeout
            raw_response = MagicMock()
            raw_response.status_code = 201
            raw_response.content = (
                b'{"job_id":"00000000-0000-0000-0000-000000000001",'
                b'"status":"pending","message":"ok"}'
            )
            raw_response.headers = {}
            raw_response.json.return_value = {
                "job_id": "00000000-0000-0000-0000-000000000001",
                "status": "pending",
                "message": "ok",
            }
            return raw_response

        mock_httpx.post.side_effect = fake_post

        sdk_client = MagicMock()
        sdk_client.get_httpx_client.return_value = mock_httpx
        sdk_client.raise_on_unexpected_status = False

        upload_file(sdk_client, sample)

        assert seen_timeout_during_post == EXTENDED_REQUEST_TIMEOUT_SECONDS
        assert seen_timeout_during_post != 30.0
        assert mock_httpx.timeout == 30.0


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
      - geolens.api.datasets.preview_file_ingest_preview_job_id_post.sync_detailed
      - geolens.api.datasets.commit_import_ingest_commit_job_id_post.sync_detailed
      - geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed
    """

    def _install(*, upload, preview, commit, job_status=None):
        # BUG-034: publish now invokes upload_file via call_sdk with keyword
        # args (client=, path=); accept both positional and keyword shapes.
        monkeypatch.setattr("geolens_cli.publish.upload_file", lambda *a, **k: upload)
        monkeypatch.setattr(
            "geolens.api.datasets.preview_file_ingest_preview_job_id_post.sync_detailed",
            lambda **kw: preview,
        )
        monkeypatch.setattr(
            "geolens.api.datasets.commit_import_ingest_commit_job_id_post.sync_detailed",
            lambda **kw: commit,
        )
        if job_status is not None:
            monkeypatch.setattr(
                "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
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

    return MagicMock(
        status_code=HTTPStatus(_publish.PREVIEW_OK_STATUS), parsed=MagicMock()
    )


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
    return MagicMock(
        status_code=HTTPStatus(_publish.JOB_STATUS_OK_STATUS), parsed=parsed
    )


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
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(
                dataset_id="00000000-0000-0000-0000-000000000042"
            ),
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 0, result.output
        assert (
            "https://x.example.com/datasets/00000000-0000-0000-0000-000000000042"
            in result.output
        )

    def test_publish_no_wait_emits_job_search_url(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
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
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        from geolens_cli.main import app
        from geolens.models.problem_detail import ProblemDetail

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
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """Task 0 Q3: backend actually emits 400 (not 409) for duplicate commits."""
        from geolens_cli.main import app
        from geolens.models.problem_detail import ProblemDetail

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
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """CliRunner output is not a TTY; rich.Progress(disable=True) emits nothing."""
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(
                dataset_id="00000000-0000-0000-0000-000000000042"
            ),
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 0, result.output
        for spinner in ("⠋", "⠙", "⠚", "⠞", "⠦", "⠧"):
            assert spinner not in result.output

    def test_json_mode_emits_payload(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(
                dataset_id="00000000-0000-0000-0000-000000000042"
            ),
        )

        result = runner.invoke(app, ["--json", "publish", str(sample_geojson)])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["dataset_url"].endswith(
            "/datasets/00000000-0000-0000-0000-000000000042"
        )
        assert payload["job_id"] == "00000000-0000-0000-0000-000000000001"

    def test_publish_uses_filename_stem_when_no_name(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """The CommitRequest title falls back to file.stem when --name is omitted."""
        from geolens_cli.main import app
        from geolens.models.commit_request import CommitRequest

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

        monkeypatch.setattr(
            "geolens_cli.publish.upload_file", lambda *a, **k: _ok_upload()
        )
        monkeypatch.setattr(
            "geolens.api.datasets.preview_file_ingest_preview_job_id_post.sync_detailed",
            lambda **kw: _ok_preview(),
        )
        monkeypatch.setattr(
            "geolens.api.datasets.commit_import_ingest_commit_job_id_post.sync_detailed",
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
        from geolens.models.commit_request import CommitRequest

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

        monkeypatch.setattr(
            "geolens_cli.publish.upload_file", lambda *a, **k: _ok_upload()
        )
        monkeypatch.setattr(
            "geolens.api.datasets.preview_file_ingest_preview_job_id_post.sync_detailed",
            lambda **kw: _ok_preview(),
        )
        monkeypatch.setattr(
            "geolens.api.datasets.commit_import_ingest_commit_job_id_post.sync_detailed",
            capture_commit,
        )

        result = runner.invoke(
            app,
            [
                "publish",
                str(sample_geojson),
                "--name",
                "My Cities",
                "--description",
                "hello",
                "--no-wait",
            ],
        )
        assert result.exit_code == 0, result.output
        assert isinstance(captured["body"], CommitRequest)
        assert captured["body"].title == "My Cities"
        assert captured["body"].summary == "hello"


# ---------------------------------------------------------------------------
# fix(#1778) — `publish --wait` must not report success (exit 0,
# "Published: ...") for a job that failed, was cancelled, timed out, or
# could not be read back because the token expired mid-poll. Mirrors
# analysis materialize --wait's job_snapshot fallback.
# ---------------------------------------------------------------------------


class TestPublishWaitTerminalOutcomes:
    def test_wait_job_failed_exits_nonzero_and_does_not_print_published(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(dataset_id=None, status="failed"),
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 1, result.output
        assert "Published:" not in result.output
        assert "failed" in result.output
        assert "job record" in result.output

    def test_wait_job_failed_with_tags_does_not_claim_a_dataset_was_created(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """fix(#1778, codex round 1 P2): a failed/cancelled/timed-out job
        never resolves a dataset_id, so --tags/--collection are never
        attempted against it. The output must carry only the terminal
        failure line, not a "Dataset created, but: ... not applied" line
        that contradicts it."""
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(dataset_id=None, status="failed"),
        )

        result = runner.invoke(
            app, ["publish", str(sample_geojson), "--tags", "hydro"]
        )
        assert result.exit_code == 1, result.output
        assert "failed" in result.output
        assert "Dataset created" not in result.output
        assert "not applied" not in result.output

    def test_wait_job_failed_json_mode_carries_status_and_null_dataset_id(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(dataset_id=None, status="failed"),
        )

        result = runner.invoke(app, ["--json", "publish", str(sample_geojson)])
        assert result.exit_code == 1, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "failed"
        assert payload["dataset_id"] is None

    def test_wait_job_cancelled_exits_nonzero_and_does_not_print_published(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """fix(#1778): cancelled was previously not terminal, so --wait
        polled a cancelled job for the full 120s timeout and then reported
        success."""
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(dataset_id=None, status="cancelled"),
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 1, result.output
        assert "Published:" not in result.output
        assert "cancelled" in result.output

    def test_wait_job_cancelled_json_mode_carries_status(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(dataset_id=None, status="cancelled"),
        )

        result = runner.invoke(app, ["--json", "publish", str(sample_geojson)])
        assert result.exit_code == 1, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "cancelled"
        assert payload["dataset_id"] is None

    def test_wait_job_fanned_out_exits_zero_and_does_not_claim_a_timeout(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """fix(#1778, codex round 2 P2): fanned_out is TERMINAL and a
        SUCCESS — the parent job of a multi-layer commit lands here the
        moment each layer's own import is queued, and it never gets a
        dataset_id of its own. Reporting "still fanned_out ... has not
        finished" would be a false diagnosis (nothing timed out), so this
        exits 0 and says the job fanned out."""
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(dataset_id=None, status="fanned_out"),
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 0, result.output
        assert "fanned out" in result.output
        assert "has not finished" not in result.output
        assert "still fanned_out" not in result.output

    def test_wait_job_fanned_out_json_mode_carries_status(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(dataset_id=None, status="fanned_out"),
        )

        result = runner.invoke(app, ["--json", "publish", str(sample_geojson)])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "fanned_out"
        assert payload["dataset_id"] is None

    def test_wait_job_fanned_out_with_tags_records_an_extras_failure(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """fix(#1778, codex round 9): --tags/--collection cannot be applied
        to a fanned-out job — there is no single dataset id, since every
        layer became its own dataset. That omission must exit non-zero and
        say so: recording only a note in the success message (the
        pre-round-9 behavior) left extras_failures empty, so the command
        exited 0 despite a requested operation never running."""
        from geolens_cli._sdk_helpers import EXIT_GENERIC
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(dataset_id=None, status="fanned_out"),
        )

        result = runner.invoke(
            app, ["publish", str(sample_geojson), "--tags", "hydro"]
        )
        assert result.exit_code == EXIT_GENERIC, result.output
        assert "fanned out" in result.output
        assert "Dataset created, but" in result.output
        assert "tags not applied" in result.output

    def test_wait_job_fanned_out_with_extras_json_mode_carries_the_failures(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """One extras_failures entry per requested extra (fix(#1778, codex
        round 9)): both --tags and --collection here, both skipped."""
        from geolens_cli._sdk_helpers import EXIT_GENERIC
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(dataset_id=None, status="fanned_out"),
        )

        result = runner.invoke(
            app,
            [
                "--json",
                "publish",
                str(sample_geojson),
                "--tags",
                "hydro",
                "--collection",
                "terrain",
            ],
        )
        assert result.exit_code == EXIT_GENERIC, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "fanned_out"
        assert len(payload["extras_failures"]) == 2
        assert any("tags not applied" in f for f in payload["extras_failures"])
        assert any(
            "collection not applied" in f for f in payload["extras_failures"]
        )

    def test_wait_poll_timed_out_exits_nonzero(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """The 120s default poll gave up while the job was still running.

        resolve_dataset_id and job_snapshot are monkeypatched directly (not
        driven through a real 120s poll) so the test stays fast; this is the
        same technique cli/tests/test_analysis.py uses for the sibling
        materialize --wait timeout test.
        """
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(), preview=_ok_preview(), commit=_ok_commit()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(
                status="running", stopped_because="timeout"
            ),
        )
        monkeypatch.setattr(
            "geolens_cli.analysis.job_snapshot", lambda c, j: ("running", None)
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 1, result.output
        assert "Published:" not in result.output
        assert "still running" in result.output
        assert "has not finished" in result.output

    def test_wait_poll_timed_out_json_mode_carries_raw_status(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(), preview=_ok_preview(), commit=_ok_commit()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(
                status="running", stopped_because="timeout"
            ),
        )
        monkeypatch.setattr(
            "geolens_cli.analysis.job_snapshot", lambda c, j: ("running", None)
        )

        result = runner.invoke(app, ["--json", "publish", str(sample_geojson)])
        assert result.exit_code == 1, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "running"
        assert payload["stopped_because"] == "timeout"
        assert payload["dataset_id"] is None

    def test_wait_poll_failed_is_not_reported_as_a_timeout(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """fix(#1778, codex round 3): the bug this fix closes. A transient
        poll failure (HTTP 500) followed by a job_snapshot() follow-up read
        that happens to succeed and report "running" must NOT be reported
        as a false "still running after 120s" timeout — nothing timed out;
        one read failed, and the next one (a DIFFERENT request) recovered."""
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(), preview=_ok_preview(), commit=_ok_commit()
        )
        calls = {"n": 0}

        def flaky_then_running(**kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return MagicMock(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR, parsed=None
                )
            return _ok_job_status(dataset_id=None, status="running")

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            flaky_then_running,
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        # fix(#1778, codex round 7): 500 is a 5xx, so this now maps to
        # EXIT_SERVER rather than the old hard-coded EXIT_GENERIC — see
        # TestPublishPollFailedExitCodes below for the dedicated coverage.
        from geolens_cli._sdk_helpers import EXIT_SERVER

        assert result.exit_code == EXIT_SERVER, result.output
        assert "Published:" not in result.output
        assert "could not be read" in result.output
        assert "HTTP 500" in result.output
        assert "still running" not in result.output
        assert "has not finished" not in result.output

    def test_wait_poll_failed_json_mode_carries_stopped_because(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(), preview=_ok_preview(), commit=_ok_commit()
        )
        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            lambda **kw: MagicMock(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR, parsed=None
            ),
        )

        result = runner.invoke(app, ["--json", "publish", str(sample_geojson)])
        # fix(#1778, codex round 7): 500 is a 5xx, so this now maps to
        # EXIT_SERVER rather than the old hard-coded EXIT_GENERIC.
        from geolens_cli._sdk_helpers import EXIT_SERVER

        assert result.exit_code == EXIT_SERVER, result.output
        payload = json.loads(result.output)
        assert payload["stopped_because"] == "poll_failed"
        assert payload["dataset_id"] is None

    def test_wait_poll_timeout_then_failed_snapshot_reports_the_failure(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """fix(#1778, codex round 4): the poll timed out, but the follow-up
        read shows the job has SINCE become failed — that definitive
        answer must win over the stale "still running after 120s"
        wording, which the previous implementation used to report."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(), preview=_ok_preview(), commit=_ok_commit()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(
                status="running", stopped_because="timeout"
            ),
        )
        monkeypatch.setattr(
            "geolens_cli.analysis.job_snapshot", lambda c, j: ("failed", None)
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 1, result.output
        assert "Published:" not in result.output
        assert "failed" in result.output
        assert "job record" in result.output
        assert "still running" not in result.output
        assert "has not finished" not in result.output

    def test_wait_poll_timeout_then_failed_snapshot_json_mode(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(), preview=_ok_preview(), commit=_ok_commit()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(
                status="running", stopped_because="timeout"
            ),
        )
        monkeypatch.setattr(
            "geolens_cli.analysis.job_snapshot", lambda c, j: ("failed", None)
        )

        result = runner.invoke(app, ["--json", "publish", str(sample_geojson)])
        assert result.exit_code == 1, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "failed"
        assert payload["stopped_because"] == "terminal"

    def test_wait_poll_failed_then_cancelled_snapshot_reports_cancellation(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """fix(#1778, codex round 4): the poll itself failed (a transient
        500), but the follow-up read shows the job has SINCE been
        cancelled — that definitive answer must win over the "status
        could not be read" wording."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(), preview=_ok_preview(), commit=_ok_commit()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(
                stopped_because="poll_failed", detail="HTTP 500"
            ),
        )
        monkeypatch.setattr(
            "geolens_cli.analysis.job_snapshot", lambda c, j: ("cancelled", None)
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 1, result.output
        assert "Published:" not in result.output
        assert "cancelled" in result.output
        assert "could not be read" not in result.output

    def test_wait_poll_timeout_then_running_snapshot_still_reports_the_timeout(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """fix(#1778, codex round 4): only a DEFINITIVE terminal snapshot
        (failed/cancelled/fanned_out) overrides the original outcome — a
        pending/running snapshot leaves the job's fate genuinely
        unresolved, so the original timeout wording stands."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(), preview=_ok_preview(), commit=_ok_commit()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(
                status="running", stopped_because="timeout"
            ),
        )
        monkeypatch.setattr(
            "geolens_cli.analysis.job_snapshot", lambda c, j: ("running", None)
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 1, result.output
        assert "still running" in result.output
        assert "has not finished" in result.output

    def test_wait_snapshot_read_timeout_does_not_hang_and_reports_original_outcome(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """fix(#1778, codex round 5): sdk.client's generated transport
        defaults to timeout=None (unbounded), so a stalled connection on
        the follow-up diagnostic read could hang the command forever
        instead of reporting the timeout it already reached. The read is
        now bound (_SNAPSHOT_REQUEST_TIMEOUT_SECONDS); when it ALSO times
        out, the command must not hang or crash — it falls back to the
        original outcome. resolve_dataset_id is mocked directly (so this
        test cannot itself hang on the real 120s poll); the SDK call the
        real job_snapshot() makes is mocked to raise httpx.TimeoutException,
        standing in for the bound actually firing.
        """
        import httpx

        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(), preview=_ok_preview(), commit=_ok_commit()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(
                status="running", stopped_because="timeout"
            ),
        )

        def boom(**kw):
            raise httpx.TimeoutException("stalled")

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            boom,
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 1, result.output
        assert "still running" in result.output
        assert "has not finished" in result.output

    def test_wait_snapshot_read_does_not_leak_its_timeout_into_stage_5(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """fix(#1778, codex round 6): `with_timeout()` MUTATES the shared
        transport's timeout in place before returning an "evolved" client
        that is really a decoy (sdks/python/geolens/client.py) — Stage 5
        (--tags/--collection) reuses sdk.client, so binding the follow-up
        snapshot read used to leave every metadata request capped at 5s
        afterward too, reporting an otherwise-successful publish as a
        partial failure. The shared transport's timeout must be back to
        its ORIGINAL value by the time Stage 5 runs.

        The httpx.Client is force-constructed before the command runs
        (via ``.get_httpx_client()``) because the pre-round-6 bug only
        mutates an ALREADY-CONSTRUCTED transport in place — a lazily
        constructed one (the normal case, since every earlier stage is
        mocked at the SDK-function level here) would not have exposed it.
        """
        import httpx
        from geolens import GeolensClient

        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)

        real_sdk = GeolensClient(base_url=instance + "/api", bearer_token="tok-abc")
        original_timeout = real_sdk.client.get_httpx_client().timeout
        monkeypatch.setattr("geolens_cli.main.AppState.sdk", lambda self: real_sdk)

        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(
                dataset_id="00000000-0000-0000-0000-000000000042", status="complete"
            ),
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(
                status="running", stopped_because="timeout"
            ),
        )

        observed: dict = {}

        def stage_5_extras(client, dataset_id, tags, collection):
            observed["timeout"] = client.get_httpx_client().timeout
            return []

        monkeypatch.setattr(
            "geolens_cli.publish.apply_publish_extras", stage_5_extras
        )

        result = runner.invoke(
            app, ["publish", str(sample_geojson), "--tags", "hydro"]
        )
        assert result.exit_code == 0, result.output
        assert observed["timeout"] == original_timeout
        assert observed["timeout"] != httpx.Timeout(
            _publish._SNAPSHOT_REQUEST_TIMEOUT_SECONDS
        )

    def test_wait_token_expired_mid_poll_exits_auth(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """A token that expires mid-poll makes every job-status call 401.

        fix(#1778, codex round 3): resolve_dataset_id detects the 401/403
        itself now (PollOutcome.stopped_because == "token_expired") instead
        of returning a bare None for the caller to reinterpret via a second
        job_snapshot() read; the command exits EXIT_AUTH directly off that,
        naming what actually went wrong rather than reporting a generic
        failure.
        """
        from geolens.models.problem_detail import ProblemDetail
        from geolens_cli._sdk_helpers import EXIT_AUTH
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        expired = MagicMock(
            status_code=HTTPStatus.UNAUTHORIZED,
            parsed=ProblemDetail(
                detail="Token expired",
                status=401,
                title="Unauthorized",
                type_="about:blank",
            ),
        )
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=expired,
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == EXIT_AUTH, result.output
        assert "Authentication failed" in result.output

    def test_wait_token_expired_json_mode_carries_stopped_because(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        from geolens.models.problem_detail import ProblemDetail
        from geolens_cli._sdk_helpers import EXIT_AUTH
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        expired = MagicMock(
            status_code=HTTPStatus.UNAUTHORIZED,
            parsed=ProblemDetail(
                detail="Token expired",
                status=401,
                title="Unauthorized",
                type_="about:blank",
            ),
        )
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=expired,
        )

        result = runner.invoke(app, ["--json", "publish", str(sample_geojson)])
        assert result.exit_code == EXIT_AUTH, result.output
        payload = json.loads(result.output)
        assert payload["stopped_because"] == "token_expired"
        assert payload["dataset_id"] is None

    def test_wait_success_case_is_unchanged(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """Regression guard: a job that resolves normally still prints
        "Published: ..." and exits 0 — the new failure branch must not fire
        on the happy path."""
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(
                dataset_id="00000000-0000-0000-0000-000000000042", status="complete"
            ),
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == 0, result.output
        assert "Published:" in result.output
        assert "00000000-0000-0000-0000-000000000042" in result.output


class TestPublishPollFailedExitCodes:
    """fix(#1778, codex round 7): a poll_failed outcome must select the
    CLI's established exit code for the HTTP status that caused it — a
    5xx (server outage) is EXIT_SERVER, anything else is the pre-existing
    EXIT_GENERIC — matching the matrix `_sdk_helpers.unwrap()` already
    uses. Previously every poll_failed exited 1 regardless of status,
    hiding a server outage from a script checking the exit code."""

    def test_503_poll_exits_exit_server_with_poll_failed_wording(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        from geolens_cli._sdk_helpers import EXIT_SERVER
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(), preview=_ok_preview(), commit=_ok_commit()
        )
        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            lambda **kw: MagicMock(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE, parsed=None
            ),
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == EXIT_SERVER, result.output
        assert "could not be read" in result.output
        assert "HTTP 503" in result.output

    def test_404_poll_exits_generic_with_poll_failed_wording(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        from geolens_cli._sdk_helpers import EXIT_GENERIC
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(), preview=_ok_preview(), commit=_ok_commit()
        )
        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            lambda **kw: MagicMock(status_code=HTTPStatus.NOT_FOUND, parsed=None),
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == EXIT_GENERIC, result.output
        assert "could not be read" in result.output
        assert "HTTP 404" in result.output


class TestResolveDatasetIdTerminalStatuses:
    """Unit-level: resolve_dataset_id stops polling as soon as the job status
    is terminal, rather than sleeping and re-polling until timeout, and
    reports it via PollOutcome.stopped_because == "terminal"
    (fix(#1778, codex round 3))."""

    def test_cancelled_stops_polling_immediately(self, monkeypatch) -> None:
        from geolens_cli import publish as _publish

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            lambda **kw: _ok_job_status(dataset_id=None, status="cancelled"),
        )
        sleeps: list[float] = []

        outcome = _publish.resolve_dataset_id(
            MagicMock(),
            "00000000-0000-0000-0000-000000000001",
            sleep=sleeps.append,
            monotonic=iter([0.0, 1.0, 2.0]).__next__,
        )
        assert outcome.dataset_id is None
        assert outcome.status == "cancelled"
        assert outcome.stopped_because == "terminal"
        assert sleeps == []

    def test_fanned_out_stops_polling_immediately(self, monkeypatch) -> None:
        from geolens_cli import publish as _publish

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            lambda **kw: _ok_job_status(dataset_id=None, status="fanned_out"),
        )
        sleeps: list[float] = []

        outcome = _publish.resolve_dataset_id(
            MagicMock(),
            "00000000-0000-0000-0000-000000000001",
            sleep=sleeps.append,
            monotonic=iter([0.0, 1.0, 2.0]).__next__,
        )
        assert outcome.dataset_id is None
        assert outcome.status == "fanned_out"
        assert outcome.stopped_because == "terminal"
        assert sleeps == []


class TestResolveDatasetIdPollOutcomeShape:
    """Unit-level: resolve_dataset_id's PollOutcome for the other three
    stopped_because reasons — "timeout", "poll_failed", "token_expired" —
    added in fix(#1778, codex round 3) so a caller never has to guess why
    the poll gave up from a bare None."""

    def test_timeout_preserves_the_last_known_status(self, monkeypatch) -> None:
        """The deadline is reached while the job is still pending/running;
        the last valid read's status is preserved, not discarded."""
        from geolens_cli import publish as _publish

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            lambda **kw: _ok_job_status(dataset_id=None, status="running"),
        )

        outcome = _publish.resolve_dataset_id(
            MagicMock(),
            "00000000-0000-0000-0000-000000000001",
            sleep=lambda *_: None,
            monotonic=iter([0.0, 1.0, 200.0]).__next__,
        )
        assert outcome.dataset_id is None
        assert outcome.status == "running"
        assert outcome.stopped_because == "timeout"

    def test_poll_failed_carries_the_http_status_and_last_known_status(
        self, monkeypatch
    ) -> None:
        """A non-200/401/403 response (a transient 500 here) stops the poll
        immediately with the HTTP status in ``detail``, and preserves
        whatever status an EARLIER successful read saw."""
        from geolens_cli import publish as _publish

        responses = iter(
            [
                _ok_job_status(dataset_id=None, status="running"),
                MagicMock(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, parsed=None),
            ]
        )
        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            lambda **kw: next(responses),
        )
        sleeps: list[float] = []

        outcome = _publish.resolve_dataset_id(
            MagicMock(),
            "00000000-0000-0000-0000-000000000001",
            sleep=sleeps.append,
            monotonic=iter([0.0, 1.0, 2.0, 3.0]).__next__,
        )
        assert outcome.dataset_id is None
        assert outcome.stopped_because == "poll_failed"
        assert outcome.detail == "HTTP 500"
        assert outcome.status == "running"
        assert outcome.http_status == 500

    def test_poll_failed_exit_code_maps_5xx_to_exit_server(self) -> None:
        from geolens_cli import publish as _publish
        from geolens_cli._sdk_helpers import EXIT_GENERIC, EXIT_SERVER

        assert _publish.poll_failed_exit_code(500) == EXIT_SERVER
        assert _publish.poll_failed_exit_code(503) == EXIT_SERVER
        assert _publish.poll_failed_exit_code(599) == EXIT_SERVER
        assert _publish.poll_failed_exit_code(404) == EXIT_GENERIC
        assert _publish.poll_failed_exit_code(499) == EXIT_GENERIC
        assert _publish.poll_failed_exit_code(None) == EXIT_GENERIC

    def test_token_expired_stops_polling_immediately(self, monkeypatch) -> None:
        from geolens_cli import publish as _publish

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            lambda **kw: MagicMock(status_code=HTTPStatus.UNAUTHORIZED, parsed=None),
        )
        sleeps: list[float] = []

        outcome = _publish.resolve_dataset_id(
            MagicMock(),
            "00000000-0000-0000-0000-000000000001",
            sleep=sleeps.append,
            monotonic=iter([0.0, 1.0, 2.0]).__next__,
        )
        assert outcome.dataset_id is None
        assert outcome.stopped_because == "token_expired"
        assert sleeps == []


# ---------------------------------------------------------------------------
# BUG-034 — network failures during upload / job-status poll map to EXIT_NETWORK
# ---------------------------------------------------------------------------


class TestPublishNetworkErrors:
    """BUG-034: httpx network errors in the upload and poll stages exit 4 cleanly."""

    def test_upload_network_error_exits_network(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        import httpx

        from geolens_cli._sdk_helpers import EXIT_NETWORK
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)

        def boom(client, path):  # noqa: ANN001
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr("geolens_cli.publish.upload_file", boom)

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == EXIT_NETWORK, result.output
        # Clean exit-code path, not a dumped traceback.
        assert result.exc_info is None or not isinstance(
            result.exc_info[1], httpx.HTTPError
        ), result.output

    def test_upload_timeout_exits_network(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        import httpx

        from geolens_cli._sdk_helpers import EXIT_NETWORK
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)

        def boom(client, path):  # noqa: ANN001
            raise httpx.ConnectTimeout("timed out")

        monkeypatch.setattr("geolens_cli.publish.upload_file", boom)

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == EXIT_NETWORK, result.output

    def test_job_status_poll_network_error_exits_network(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        import httpx

        from geolens_cli._sdk_helpers import EXIT_NETWORK
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)

        def boom(**kwargs):
            raise httpx.ReadError("connection dropped mid-poll")

        # Upload/preview/commit succeed; the post-commit poll fails on the wire.
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
        )
        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            boom,
        )

        result = runner.invoke(app, ["publish", str(sample_geojson)])
        assert result.exit_code == EXIT_NETWORK, result.output


class TestResolveDatasetIdNetworkError:
    """BUG-034 unit-level: the poll's sync_detailed is routed through call_sdk."""

    def test_resolve_propagates_network_exit(self, monkeypatch) -> None:
        import httpx
        import typer

        from geolens_cli import publish as _publish
        from geolens_cli._sdk_helpers import EXIT_NETWORK

        def boom(**kwargs):
            raise httpx.NetworkError("down")

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            boom,
        )

        with pytest.raises(typer.Exit) as exc_info:
            _publish.resolve_dataset_id(
                MagicMock(),
                "00000000-0000-0000-0000-000000000001",
                sleep=lambda *_: None,
                monotonic=iter([0.0, 1.0]).__next__,
            )
        assert exc_info.value.exit_code == EXIT_NETWORK


class TestResolveDatasetIdBoundsEachRequest:
    """fix(#1778, #1787): resolve_dataset_id's own poll requests inherited
    the client's default timeout=None (unbounded) — the deadline computed
    from `timeout` is only checked BETWEEN polls, so a single stalled
    connection could hang --wait forever regardless of how short the
    caller's overall deadline was. Each request must be bound to
    _SNAPSHOT_REQUEST_TIMEOUT_SECONDS (the same short bound already used
    for the one-shot follow-up read of this identical endpoint), and the
    transport's original timeout restored once polling stops."""

    def test_each_poll_request_is_bounded_and_original_timeout_restored(
        self, monkeypatch
    ) -> None:
        from types import SimpleNamespace

        from geolens_cli import publish as _publish

        transport = SimpleNamespace(timeout="unset-original")
        client = MagicMock()
        client.get_httpx_client.return_value = transport

        seen_timeouts: list = []

        def next_status(**kwargs):
            seen_timeouts.append(transport.timeout)
            return MagicMock(
                status_code=HTTPStatus.OK,
                parsed=SimpleNamespace(status="running", dataset_id=None),
            )

        monkeypatch.setattr(
            "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
            next_status,
        )

        outcome = _publish.resolve_dataset_id(
            client,
            "00000000-0000-0000-0000-000000000001",
            timeout=120.0,
            sleep=lambda *_: None,
            monotonic=iter([0.0, 1.0, 200.0]).__next__,
        )

        assert outcome.stopped_because == "timeout"
        assert seen_timeouts, "no poll request was observed"
        # Every poll request was bounded well under the 120s overall
        # deadline — previously it inherited the client's default
        # (unbounded) timeout.
        assert all(
            t == _publish._SNAPSHOT_REQUEST_TIMEOUT_SECONDS for t in seen_timeouts
        )
        # The transport's timeout is restored to whatever it was before
        # polling started, not left at the short per-request bound.
        assert transport.timeout == "unset-original"


# ---------------------------------------------------------------------------
# fix(#569) — --tags / --collection wiring
# ---------------------------------------------------------------------------


class TestSplitTags:
    def test_trims_dedupes_and_preserves_order(self) -> None:
        from geolens_cli.publish import _split_tags

        assert _split_tags(" hydro, Hydro, dem ,, terrain ") == [
            "hydro",
            "dem",
            "terrain",
        ]


class TestResolveRecordId:
    """fix(#588): keywords are RECORD-scoped; Dataset.id != Dataset.record_id."""

    def test_returns_record_id_not_dataset_id(self, monkeypatch) -> None:
        import geolens_cli.publish as publish

        dataset_id = "40e4c02d-d509-4046-8718-baadad2b59c7"
        record_id = UUID("d736d1bb-0191-4ca4-a473-c2bcc6d123da")
        resp = MagicMock(status_code=200, parsed=MagicMock(record_id=record_id))
        monkeypatch.setattr(publish, "call_sdk", lambda *a, **k: resp)

        got = publish._resolve_record_id(MagicMock(), dataset_id)
        assert got == record_id
        assert str(got) != dataset_id

    def test_lookup_failure_returns_description(self, monkeypatch) -> None:
        import geolens_cli.publish as publish

        resp = MagicMock(status_code=404, parsed=None)
        monkeypatch.setattr(publish, "call_sdk", lambda *a, **k: resp)
        got = publish._resolve_record_id(
            MagicMock(), "40e4c02d-d509-4046-8718-baadad2b59c7"
        )
        assert isinstance(got, str) and "record lookup failed" in got


class TestApplyTags:
    def test_posts_keywords_against_the_record_id(self, monkeypatch) -> None:
        import geolens_cli.publish as publish

        dataset_id = "40e4c02d-d509-4046-8718-baadad2b59c7"
        record_id = UUID("d736d1bb-0191-4ca4-a473-c2bcc6d123da")
        monkeypatch.setattr(publish, "_resolve_record_id", lambda *a: record_id)
        seen: list = []

        def fake_call_sdk(fn, **kwargs):
            seen.append(kwargs)
            return MagicMock(status_code=201)

        monkeypatch.setattr(publish, "call_sdk", fake_call_sdk)
        failures = publish._apply_tags(MagicMock(), dataset_id, "hydro, dem")

        assert failures == []
        assert [k["record_id"] for k in seen] == [record_id, record_id]
        assert [k["body"].keyword for k in seen] == ["hydro", "dem"]

    def test_record_lookup_failure_short_circuits(self, monkeypatch) -> None:
        import geolens_cli.publish as publish

        monkeypatch.setattr(
            publish, "_resolve_record_id", lambda *a: "record lookup failed: HTTP 404"
        )

        def explode(*a, **k):  # pragma: no cover - must not be reached
            raise AssertionError("keyword POST attempted despite failed record lookup")

        monkeypatch.setattr(publish, "call_sdk", explode)
        assert publish._apply_tags(MagicMock(), "d-id", "x") == [
            "record lookup failed: HTTP 404"
        ]

    def test_non_201_is_reported_per_tag(self, monkeypatch) -> None:
        import geolens_cli.publish as publish

        monkeypatch.setattr(publish, "_resolve_record_id", lambda *a: UUID(int=7))
        monkeypatch.setattr(
            publish, "call_sdk", lambda *a, **k: MagicMock(status_code=500)
        )
        assert publish._apply_tags(MagicMock(), "d-id", "x,y") == [
            "tag 'x': HTTP 500",
            "tag 'y': HTTP 500",
        ]


class TestResolveCollectionId:
    def test_uuid_passthrough(self) -> None:
        from geolens_cli.publish import _resolve_collection_id

        cid = "00000000-0000-0000-0000-00000000abcd"
        assert _resolve_collection_id(MagicMock(), cid) == UUID(cid)

    def _collections_response(self, names_ids: list[tuple[str, str]]) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.parsed = MagicMock(
            collections=[MagicMock(id=UUID(cid), name=name) for name, cid in names_ids]
        )
        # MagicMock(name=...) sets the mock's name, not the attribute
        for m, (name, _cid) in zip(resp.parsed.collections, names_ids):
            m.name = name
        return resp

    def test_exact_name_match_case_insensitive(self, monkeypatch) -> None:
        import geolens_cli.publish as publish

        resp = self._collections_response(
            [
                ("Human World", "00000000-0000-0000-0000-000000000001"),
                ("Terrain", "00000000-0000-0000-0000-000000000002"),
            ]
        )
        monkeypatch.setattr(publish, "call_sdk", lambda *a, **k: resp)
        got = publish._resolve_collection_id(MagicMock(), "human world")
        assert got == UUID("00000000-0000-0000-0000-000000000001")

    def test_missing_name_returns_failure_string(self, monkeypatch) -> None:
        import geolens_cli.publish as publish

        resp = self._collections_response(
            [("Terrain", "00000000-0000-0000-0000-000000000002")]
        )
        monkeypatch.setattr(publish, "call_sdk", lambda *a, **k: resp)
        got = publish._resolve_collection_id(MagicMock(), "nope")
        assert isinstance(got, str) and "not found" in got


class TestApplyPublishExtras:
    def test_collects_failures_from_both_paths(self, monkeypatch) -> None:
        import geolens_cli.publish as publish

        monkeypatch.setattr(publish, "_apply_tags", lambda *a: ["tag 'x': HTTP 500"])
        monkeypatch.setattr(
            publish, "_apply_collection", lambda *a: ["collection add: HTTP 404"]
        )
        failures = publish.apply_publish_extras(MagicMock(), "d-id", "x", "c")
        assert failures == ["tag 'x': HTTP 500", "collection add: HTTP 404"]

    def test_noop_without_flags(self) -> None:
        from geolens_cli.publish import apply_publish_extras

        assert apply_publish_extras(MagicMock(), "d-id", None, None) == []


class TestApplyPublishExtrasNeverRaises:
    """fix(#588): a transport error after commit must not swallow the URL."""

    def test_typer_exit_from_tags_becomes_a_failure_line(self, monkeypatch) -> None:
        import typer

        import geolens_cli.publish as publish

        def boom(*a, **k):
            raise typer.Exit(4)

        monkeypatch.setattr(publish, "_apply_tags", boom)
        failures = publish.apply_publish_extras(MagicMock(), "d-id", "x", None)
        assert failures == ["tags: request failed (exit code 4)"]

    def test_collection_still_attempted_after_tags_transport_failure(
        self, monkeypatch
    ) -> None:
        import typer

        import geolens_cli.publish as publish

        def boom(*a, **k):
            raise typer.Exit(4)

        monkeypatch.setattr(publish, "_apply_tags", boom)
        monkeypatch.setattr(publish, "_apply_collection", lambda *a: [])
        failures = publish.apply_publish_extras(MagicMock(), "d-id", "x", "Terrain")
        # tags reported; the collection attempt was NOT skipped (it succeeded)
        assert failures == ["tags: request failed (exit code 4)"]

    def test_unexpected_exception_is_described_not_propagated(
        self, monkeypatch
    ) -> None:
        import geolens_cli.publish as publish

        def boom(*a, **k):
            raise ValueError("bad uuid")

        monkeypatch.setattr(publish, "_apply_collection", boom)
        failures = publish.apply_publish_extras(MagicMock(), "d-id", None, "Terrain")
        assert failures == ["collection: ValueError: bad uuid"]


class TestPublishExtrasCli:
    def test_tags_with_no_wait_exits_usage(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        result = runner.invoke(
            app, ["publish", str(sample_geojson), "--no-wait", "--tags", "a,b"]
        )
        assert result.exit_code == 2, result.output
        assert "--wait" in result.output

    def test_extras_failure_reports_partial_and_exits_nonzero(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        import geolens_cli.publish as publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(
                dataset_id="00000000-0000-0000-0000-000000000042"
            ),
        )
        monkeypatch.setattr(
            publish, "apply_publish_extras", lambda *a, **k: ["tag 'x': HTTP 500"]
        )

        result = runner.invoke(app, ["publish", str(sample_geojson), "--tags", "x"])
        assert result.exit_code == 1, result.output
        assert "Dataset created, but" in result.output

    def test_transport_failure_in_extras_still_prints_dataset_url(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        """fix(#588): the dataset exists — never exit without the recovery info."""
        import typer

        import geolens_cli.publish as publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(
                dataset_id="00000000-0000-0000-0000-000000000042"
            ),
        )

        def network_boom(*a, **k):
            raise typer.Exit(4)

        # Simulate the raise happening INSIDE the extras (call_sdk's behavior).
        monkeypatch.setattr(publish, "_apply_tags", network_boom)

        result = runner.invoke(app, ["publish", str(sample_geojson), "--tags", "x"])
        assert result.exit_code == 1, result.output
        assert "00000000-0000-0000-0000-000000000042" in result.output
        assert "Dataset created, but" in result.output

    def test_extras_success_keeps_exit_zero(
        self,
        runner,
        tmp_xdg_home,
        mock_keyring,
        monkeypatch,
        sample_geojson,
        patch_sdk_for_publish,
    ) -> None:
        import geolens_cli.publish as publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        patch_sdk_for_publish(
            upload=_ok_upload(),
            preview=_ok_preview(),
            commit=_ok_commit(),
            job_status=_ok_job_status(
                dataset_id="00000000-0000-0000-0000-000000000042"
            ),
        )
        applied: dict = {}

        def fake_extras(client, dataset_id, tags, collection):
            applied["args"] = (dataset_id, tags, collection)
            return []

        monkeypatch.setattr(publish, "apply_publish_extras", fake_extras)

        result = runner.invoke(
            app,
            [
                "publish",
                str(sample_geojson),
                "--tags",
                "hydro,dem",
                "--collection",
                "Terrain",
            ],
        )
        assert result.exit_code == 0, result.output
        assert applied["args"] == (
            "00000000-0000-0000-0000-000000000042",
            "hydro,dem",
            "Terrain",
        )
