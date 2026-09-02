"""gh#1739: `geolens replace` reuploads a file over an existing dataset.

Hand-maintained, NOT regenerated. Mirrors the style of test_publish_unit.py
(module-surface unit tests) and test_refresh.py (CLI-level dispatch tests
against a mocked SDK transport).
"""

from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

DATASET_ID = UUID("00000000-0000-0000-0000-000000000201")
JOB_ID = UUID("00000000-0000-0000-0000-000000000202")
INSTANCE = "https://x.example.com"


def _seed_login(mock_keyring: dict) -> None:
    from geolens_cli import config as _config

    mock_keyring[("geolens", INSTANCE)] = "cli-auth-token"
    _config.write_default_instance(INSTANCE, username="alice")


@pytest.fixture
def sample_geojson(tmp_path: Path) -> Path:
    f = tmp_path / "cities.geojson"
    f.write_text('{"type":"FeatureCollection","features":[]}')
    return f


# ---------------------------------------------------------------------------
# Module-surface unit tests
# ---------------------------------------------------------------------------


class TestLayerSummaries:
    def test_none_all_layers_is_empty(self) -> None:
        from geolens_cli.replace import layer_summaries

        assert layer_summaries(SimpleNamespace(all_layers=None)) == []

    def test_unset_all_layers_is_empty(self) -> None:
        from geolens.types import UNSET

        from geolens_cli.replace import layer_summaries

        assert layer_summaries(SimpleNamespace(all_layers=UNSET)) == []

    def test_extracts_name_and_feature_count_from_additional_properties(self) -> None:
        from geolens_cli.replace import layer_summaries

        item_a = SimpleNamespace(
            additional_properties={"name": "roads", "feature_count": 120, "field_count": 3}
        )
        item_b = SimpleNamespace(
            additional_properties={"name": "buildings", "feature_count": 55, "field_count": 5}
        )
        result = layer_summaries(SimpleNamespace(all_layers=[item_a, item_b]))
        assert result == [
            {"name": "roads", "feature_count": 120},
            {"name": "buildings", "feature_count": 55},
        ]


class TestIsMultiLayer:
    def test_false_for_single_layer(self) -> None:
        from geolens_cli.replace import is_multi_layer

        assert is_multi_layer(SimpleNamespace(all_layers=None)) is False

    def test_true_when_layers_present(self) -> None:
        from geolens_cli.replace import is_multi_layer

        item = SimpleNamespace(additional_properties={"name": "roads", "feature_count": 1})
        assert is_multi_layer(SimpleNamespace(all_layers=[item])) is True


class TestPreviewSummary:
    def test_selects_stable_fields(self) -> None:
        from geolens_cli.replace import preview_summary

        preview = SimpleNamespace(
            layer_name="roads",
            feature_count=42,
            crs=4326,
            geometry_type="LineString",
            schema_diff=object(),
        )
        assert preview_summary(preview) == {
            "layer_name": "roads",
            "feature_count": 42,
            "srid": 4326,
            "geometry_type": "LineString",
        }


class TestMultiLayerRefusalMessage:
    def test_lists_every_layer_with_feature_count(self) -> None:
        from geolens_cli.replace import multi_layer_refusal_message

        message = multi_layer_refusal_message(
            [
                {"name": "roads", "feature_count": 120},
                {"name": "buildings", "feature_count": 55},
            ]
        )
        assert "--layer" in message
        assert "roads (120 features)" in message
        assert "buildings (55 features)" in message


class TestBuildPreviewRequest:
    def test_none_layer_is_unset(self) -> None:
        from geolens.types import UNSET

        from geolens_cli.replace import build_preview_request

        assert build_preview_request(None) is UNSET

    def test_named_layer_builds_request(self) -> None:
        from geolens_cli.replace import build_preview_request

        req = build_preview_request("roads")
        assert req.layer_name == "roads"


class TestBuildCommitRequest:
    def test_no_layer_or_srid_leaves_both_unset(self) -> None:
        from geolens.types import UNSET

        from geolens_cli.replace import build_commit_request

        req = build_commit_request(layer_name=None, srid_override=None)
        assert req.layer_name is UNSET
        assert req.srid_override is UNSET

    def test_layer_and_srid_are_set(self) -> None:
        from geolens_cli.replace import build_commit_request

        req = build_commit_request(layer_name="roads", srid_override=3857)
        assert req.layer_name == "roads"
        assert req.srid_override == 3857


class TestUploadFile:
    def test_posts_multipart_to_the_reupload_endpoint(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        from geolens_cli.replace import upload_file

        sample = tmp_path / "cities.geojson"
        sample.write_text('{"type":"FeatureCollection","features":[]}')

        mock_httpx = MagicMock()
        raw_response = MagicMock()
        raw_response.status_code = 201
        raw_response.content = b'{"job_id":"00000000-0000-0000-0000-000000000202","status":"pending","message":"ok"}'
        raw_response.headers = {}
        raw_response.json.return_value = {
            "job_id": "00000000-0000-0000-0000-000000000202",
            "status": "pending",
            "message": "ok",
        }
        mock_httpx.post.return_value = raw_response

        sdk_client = MagicMock()
        sdk_client.get_httpx_client.return_value = mock_httpx
        sdk_client.raise_on_unexpected_status = False

        result = upload_file(sdk_client, DATASET_ID, sample)

        sdk_client.get_httpx_client.assert_called_once()
        post_call = mock_httpx.post.call_args
        assert post_call.args[0] == f"/datasets/{DATASET_ID}/reupload"
        files = post_call.kwargs["files"]
        assert files["file"][0] == "cities.geojson"
        assert files["file"][2] == "application/geo+json"
        assert int(result.status_code) == 201


def _problem(status: int, detail: str | dict) -> SimpleNamespace:
    from geolens.models.problem_detail import ProblemDetail
    from geolens.models.problem_detail_detail_type_1 import ProblemDetailDetailType1

    parsed_detail = (
        ProblemDetailDetailType1.from_dict(detail) if isinstance(detail, dict) else detail
    )
    return SimpleNamespace(
        status_code=HTTPStatus(status),
        parsed=ProblemDetail(
            title="Replace refused",
            status=status,
            detail=parsed_detail,
        ),
    )


class TestReplaceRequestError:
    def test_404_is_plain(self) -> None:
        from geolens_cli.replace import replace_request_error

        err = replace_request_error(_problem(404, "Dataset not found"))
        assert err.message == "Dataset not found"
        assert err.exit_code == 1

    def test_403_is_plain_and_exits_auth(self) -> None:
        from geolens_cli._sdk_helpers import EXIT_AUTH
        from geolens_cli.replace import replace_request_error

        err = replace_request_error(_problem(403, "Permission denied"))
        assert err.message == "Permission denied"
        assert err.exit_code == EXIT_AUTH

    def test_refresh_not_applicable_points_at_refresh(self) -> None:
        from geolens_cli.replace import replace_request_error

        err = replace_request_error(
            _problem(409, {"code": "refresh_not_applicable", "message": "backend text"})
        )
        assert "geolens refresh" in err.message
        assert err.exit_code == 1

    def test_dataset_busy_is_actionable(self) -> None:
        from geolens_cli.replace import replace_request_error

        err = replace_request_error(
            _problem(409, {"code": "dataset_busy", "message": "backend text"})
        )
        assert "already running" in err.message

    def test_server_error_exits_server(self) -> None:
        from geolens_cli._sdk_helpers import EXIT_SERVER
        from geolens_cli.replace import replace_request_error

        err = replace_request_error(_problem(500, "boom"))
        assert err.exit_code == EXIT_SERVER

    def test_unmapped_status_falls_back_to_server_detail(self) -> None:
        from geolens_cli.replace import replace_request_error

        err = replace_request_error(_problem(422, "Layer 'x' not found in this file."))
        assert "Layer 'x' not found" in err.message


class TestUnwrapOrRaise:
    def test_returns_parsed_on_expected_status(self) -> None:
        from geolens_cli.replace import unwrap_or_raise

        resp = SimpleNamespace(status_code=HTTPStatus.OK, parsed="ok")
        assert unwrap_or_raise(resp, expected=200) == "ok"

    def test_raises_replace_request_error_otherwise(self) -> None:
        from geolens_cli.replace import ReplaceRequestError, unwrap_or_raise

        with pytest.raises(ReplaceRequestError):
            unwrap_or_raise(_problem(404, "Dataset not found"), expected=200)


class TestIsRasterDataset:
    def test_true_for_raster_record_type(self) -> None:
        from geolens_cli.replace import is_raster_dataset

        assert is_raster_dataset(SimpleNamespace(record_type="raster_dataset")) is True

    def test_false_for_vector_record_type(self) -> None:
        from geolens_cli.replace import is_raster_dataset

        assert is_raster_dataset(SimpleNamespace(record_type="vector_dataset")) is False

    def test_false_when_record_type_missing(self) -> None:
        from geolens_cli.replace import is_raster_dataset

        assert is_raster_dataset(SimpleNamespace()) is False


class TestOriginRefusalMessage:
    def test_service_origin_points_at_refresh(self) -> None:
        from geolens_cli.replace import origin_refusal_message

        message = origin_refusal_message("service")
        assert message is not None
        assert "geolens refresh" in message

    def test_postgis_origin_explains_registered_table(self) -> None:
        from geolens_cli.replace import origin_refusal_message

        message = origin_refusal_message("postgis")
        assert message is not None
        assert "registered database table" in message
        assert "geolens refresh" in message

    @pytest.mark.parametrize("origin", ["upload", "created", None])
    def test_other_origins_are_not_refused(self, origin: str | None) -> None:
        from geolens_cli.replace import origin_refusal_message

        assert origin_refusal_message(origin) is None


class TestFetchDataset:
    def test_forwards_dataset_id_and_client(self, monkeypatch) -> None:
        from geolens_cli.replace import fetch_dataset

        seen: dict = {}

        def fake_sync_detailed(**kw):
            seen.update(kw)
            return SimpleNamespace(status_code=HTTPStatus.OK, parsed="dataset")

        monkeypatch.setattr(
            "geolens.api.datasets.get_single_dataset_datasets_dataset_id_get.sync_detailed",
            fake_sync_detailed,
        )

        client = object()
        result = fetch_dataset(client, DATASET_ID)

        assert seen == {"dataset_id": DATASET_ID, "client": client}
        assert result.parsed == "dataset"


# ---------------------------------------------------------------------------
# CLI-level dispatch tests
# ---------------------------------------------------------------------------


def _ok_upload(job_id: UUID = JOB_ID) -> SimpleNamespace:
    from geolens_cli import replace as _replace

    return SimpleNamespace(
        status_code=HTTPStatus(_replace.UPLOAD_OK_STATUS),
        parsed=SimpleNamespace(job_id=job_id, status="pending", message="ok"),
    )


def _ok_preview(
    *,
    layer_name: str = "roads",
    feature_count: int = 42,
    crs: int | None = 4326,
    geometry_type: str | None = "LineString",
    all_layers=None,
) -> SimpleNamespace:
    from geolens_cli import replace as _replace

    return SimpleNamespace(
        status_code=HTTPStatus(_replace.PREVIEW_OK_STATUS),
        parsed=SimpleNamespace(
            job_id=JOB_ID,
            layer_name=layer_name,
            feature_count=feature_count,
            crs=crs,
            geometry_type=geometry_type,
            all_layers=all_layers,
        ),
    )


def _ok_commit(job_id: UUID = JOB_ID, status: str = "pending") -> SimpleNamespace:
    from geolens_cli import replace as _replace

    return SimpleNamespace(
        status_code=HTTPStatus(_replace.COMMIT_OK_STATUS),
        parsed=SimpleNamespace(job_id=job_id, status=status, message="Re-upload queued"),
    )


def _multi_layer_items() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(additional_properties={"name": "roads", "feature_count": 120}),
        SimpleNamespace(additional_properties={"name": "buildings", "feature_count": 55}),
    ]


def _patch_upload(monkeypatch, upload) -> None:
    monkeypatch.setattr("geolens_cli.replace.upload_file", lambda *a, **k: upload)


def _patch_preview(monkeypatch, preview) -> None:
    monkeypatch.setattr(
        "geolens.api.datasets_reupload."
        "reupload_preview_datasets_dataset_id_reupload_job_id_preview_post.sync_detailed",
        lambda **kw: preview,
    )


def _patch_commit(monkeypatch, commit) -> None:
    monkeypatch.setattr(
        "geolens.api.datasets_reupload."
        "reupload_commit_datasets_dataset_id_reupload_job_id_commit_post.sync_detailed",
        lambda **kw: commit,
    )


def _patch_job_status(monkeypatch, *, status: str, error_message: str | None = None) -> None:
    monkeypatch.setattr(
        "geolens.api.admin.get_job_status_jobs_job_id_get.sync_detailed",
        lambda **kw: SimpleNamespace(
            status_code=HTTPStatus.OK,
            parsed=SimpleNamespace(status=status, error_message=error_message),
        ),
    )


def _ok_dataset(
    *, origin: str | None = "upload", record_type: str = "vector_dataset"
) -> SimpleNamespace:
    from geolens_cli import replace as _replace

    return SimpleNamespace(
        status_code=HTTPStatus(_replace.GET_DATASET_OK_STATUS),
        parsed=SimpleNamespace(origin=origin, record_type=record_type),
    )


def _patch_dataset(monkeypatch, dataset) -> None:
    monkeypatch.setattr(
        "geolens.api.datasets.get_single_dataset_datasets_dataset_id_get.sync_detailed",
        lambda **kw: dataset,
    )


class TestReplaceSingleLayerHappyPath:
    def test_success_without_wait_prints_job_id(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset())
        _patch_upload(monkeypatch, _ok_upload())
        _patch_preview(monkeypatch, _ok_preview())
        _patch_commit(monkeypatch, _ok_commit())

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson), "--yes"]
        )

        assert result.exit_code == 0, result.output
        assert str(JOB_ID) in result.output

    def test_json_mode_emits_a_single_payload(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset())
        _patch_upload(monkeypatch, _ok_upload())
        _patch_preview(monkeypatch, _ok_preview())
        _patch_commit(monkeypatch, _ok_commit())

        result = runner.invoke(
            app, ["--json", "replace", str(DATASET_ID), str(sample_geojson), "--yes"]
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["job_id"] == str(JOB_ID)
        assert payload["dataset_id"] == str(DATASET_ID)
        assert payload["preview"]["layer_name"] == "roads"

    def test_wait_reports_terminal_success(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset())
        _patch_upload(monkeypatch, _ok_upload())
        _patch_preview(monkeypatch, _ok_preview())
        _patch_commit(monkeypatch, _ok_commit())
        _patch_job_status(monkeypatch, status="complete")

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson), "--yes", "--wait"]
        )

        assert result.exit_code == 0, result.output


class TestReplaceMultiLayerRefusal:
    def test_refuses_without_layer_and_lists_layers(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app
        from geolens_cli._sdk_helpers import EXIT_USAGE

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset())
        _patch_upload(monkeypatch, _ok_upload())
        _patch_preview(monkeypatch, _ok_preview(all_layers=_multi_layer_items()))

        def must_not_commit(**kw):  # pragma: no cover - guard
            raise AssertionError("commit must not be called without --layer")

        monkeypatch.setattr(
            "geolens.api.datasets_reupload."
            "reupload_commit_datasets_dataset_id_reupload_job_id_commit_post.sync_detailed",
            must_not_commit,
        )

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson), "--yes"]
        )

        assert result.exit_code == EXIT_USAGE, result.output
        assert "roads (120 features)" in result.output
        assert "buildings (55 features)" in result.output

    def test_layer_flag_commits_the_chosen_layer(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset())
        _patch_upload(monkeypatch, _ok_upload())
        _patch_preview(
            monkeypatch,
            _ok_preview(layer_name="buildings", all_layers=_multi_layer_items()),
        )
        captured: dict = {}

        def capture_commit(**kw):
            captured.update(kw)
            return _ok_commit()

        monkeypatch.setattr(
            "geolens.api.datasets_reupload."
            "reupload_commit_datasets_dataset_id_reupload_job_id_commit_post.sync_detailed",
            capture_commit,
        )

        result = runner.invoke(
            app,
            [
                "replace",
                str(DATASET_ID),
                str(sample_geojson),
                "--layer",
                "buildings",
                "--yes",
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["body"].layer_name == "buildings"


class TestReplaceSridFlag:
    def test_srid_sends_srid_override(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset())
        _patch_upload(monkeypatch, _ok_upload())
        _patch_preview(monkeypatch, _ok_preview())
        captured: dict = {}

        def capture_commit(**kw):
            captured.update(kw)
            return _ok_commit()

        monkeypatch.setattr(
            "geolens.api.datasets_reupload."
            "reupload_commit_datasets_dataset_id_reupload_job_id_commit_post.sync_detailed",
            capture_commit,
        )

        result = runner.invoke(
            app,
            [
                "replace",
                str(DATASET_ID),
                str(sample_geojson),
                "--srid",
                "3857",
                "--yes",
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["body"].srid_override == 3857


class TestReplaceWaitFailure:
    def test_wait_exits_nonzero_on_failed_job(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset())
        _patch_upload(monkeypatch, _ok_upload())
        _patch_preview(monkeypatch, _ok_preview())
        _patch_commit(monkeypatch, _ok_commit())
        _patch_job_status(monkeypatch, status="failed", error_message="ogr2ogr exited 1")

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson), "--yes", "--wait"]
        )

        assert result.exit_code == 1, result.output
        assert "ogr2ogr exited 1" in result.output


class TestReplaceConfirmationPrompt:
    def test_yes_flag_skips_the_prompt(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset())
        _patch_upload(monkeypatch, _ok_upload())
        _patch_preview(monkeypatch, _ok_preview())
        _patch_commit(monkeypatch, _ok_commit())

        # No `input=` supplied; a prompt read would hang/fail on empty stdin.
        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson), "--yes"]
        )

        assert result.exit_code == 0, result.output
        assert "Replace" in result.output or str(JOB_ID) in result.output

    def test_declining_the_prompt_cancels(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset())
        _patch_upload(monkeypatch, _ok_upload())
        _patch_preview(monkeypatch, _ok_preview())

        def must_not_commit(**kw):  # pragma: no cover - guard
            raise AssertionError("commit must not be called after declining")

        monkeypatch.setattr(
            "geolens.api.datasets_reupload."
            "reupload_commit_datasets_dataset_id_reupload_job_id_commit_post.sync_detailed",
            must_not_commit,
        )

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson)], input="n\n"
        )

        assert result.exit_code == 1, result.output
        assert "cancelled" in result.output.lower()

    def test_confirming_the_prompt_proceeds(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset())
        _patch_upload(monkeypatch, _ok_upload())
        _patch_preview(monkeypatch, _ok_preview())
        _patch_commit(monkeypatch, _ok_commit())

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson)], input="y\n"
        )

        assert result.exit_code == 0, result.output


class TestReplace409Hint:
    def test_refresh_not_applicable_hints_at_refresh_command(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        # Upload-origin at fetch time; the 409 below is the fallback for a
        # race where the origin changed after the pre-check ran.
        _patch_dataset(monkeypatch, _ok_dataset())
        _patch_upload(
            monkeypatch,
            _problem(
                409,
                {
                    "code": "refresh_not_applicable",
                    "message": "This dataset's origin does not support reupload.",
                },
            ),
        )

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson), "--yes"]
        )

        assert result.exit_code == 1, result.output
        assert "geolens refresh" in result.output

    def test_dataset_busy_is_actionable(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset())
        _patch_upload(
            monkeypatch,
            _problem(409, {"code": "dataset_busy", "message": "backend detail"}),
        )

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson), "--yes"]
        )

        assert result.exit_code == 1, result.output
        assert "already running" in result.output


class TestReplace404And403:
    """These land on the dataset pre-fetch: the first request the command
    issues (gh#1767 review), so it is what a missing/forbidden dataset
    actually hits before any upload is attempted."""

    def test_404_prints_plain_server_message(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _problem(404, "Dataset not found"))

        def must_not_upload(*a, **k):  # pragma: no cover - guard
            raise AssertionError("upload must not be attempted for a missing dataset")

        monkeypatch.setattr("geolens_cli.replace.upload_file", must_not_upload)

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson), "--yes"]
        )

        assert result.exit_code == 1, result.output
        assert "Dataset not found" in result.output

    def test_403_prints_plain_server_message_and_exits_auth(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app
        from geolens_cli._sdk_helpers import EXIT_AUTH

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _problem(403, "Permission denied"))

        def must_not_upload(*a, **k):  # pragma: no cover - guard
            raise AssertionError("upload must not be attempted without permission")

        monkeypatch.setattr("geolens_cli.replace.upload_file", must_not_upload)

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson), "--yes"]
        )

        assert result.exit_code == EXIT_AUTH, result.output
        assert "Permission denied" in result.output


class TestReplaceInvalidDatasetId:
    def test_non_uuid_dataset_id_is_a_usage_error(
        self, runner, tmp_xdg_home, mock_keyring, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        result = runner.invoke(app, ["replace", "not-a-uuid", str(sample_geojson)])

        assert result.exit_code == 2, result.output


class TestReplaceOriginGuard:
    """gh#1767 review P2: a service or registered-table origin is refused
    before any upload request, since the reupload worker always rebinds a
    committed dataset to `upload` and would silently sever the refresh
    source."""

    def test_service_origin_is_refused_with_no_upload_request(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset(origin="service"))

        def must_not_upload(*a, **k):  # pragma: no cover - guard
            raise AssertionError("upload must not be attempted for a service origin")

        monkeypatch.setattr("geolens_cli.replace.upload_file", must_not_upload)

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson), "--yes"]
        )

        assert result.exit_code == 1, result.output
        assert "geolens refresh" in result.output

    def test_registered_table_origin_is_refused_with_no_upload_request(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset(origin="postgis"))

        def must_not_upload(*a, **k):  # pragma: no cover - guard
            raise AssertionError(
                "upload must not be attempted for a registered table origin"
            )

        monkeypatch.setattr("geolens_cli.replace.upload_file", must_not_upload)

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson), "--yes"]
        )

        assert result.exit_code == 1, result.output
        assert "registered database table" in result.output
        assert "geolens refresh" in result.output

    def test_upload_origin_proceeds(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset(origin="upload"))
        _patch_upload(monkeypatch, _ok_upload())
        _patch_preview(monkeypatch, _ok_preview())
        _patch_commit(monkeypatch, _ok_commit())

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson), "--yes"]
        )

        assert result.exit_code == 0, result.output


class TestReplaceRasterDataset:
    """gh#1767 review P1: `reupload_preview` 400s for a raster dataset by
    design (router_reupload.py); the supported flow is upload then commit
    with no preview step."""

    def test_raster_dataset_skips_preview_and_commits(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset(record_type="raster_dataset"))
        _patch_upload(monkeypatch, _ok_upload())
        _patch_commit(monkeypatch, _ok_commit())

        def must_not_preview(**kw):  # pragma: no cover - guard
            raise AssertionError("preview must not be called for a raster dataset")

        monkeypatch.setattr(
            "geolens.api.datasets_reupload."
            "reupload_preview_datasets_dataset_id_reupload_job_id_preview_post.sync_detailed",
            must_not_preview,
        )

        result = runner.invoke(
            app, ["replace", str(DATASET_ID), str(sample_geojson), "--yes"]
        )

        assert result.exit_code == 0, result.output
        assert "without preview" in result.output.lower()

    def test_layer_flag_on_raster_is_a_usage_error(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, sample_geojson
    ) -> None:
        from geolens_cli.main import app
        from geolens_cli._sdk_helpers import EXIT_USAGE

        _seed_login(mock_keyring)
        _patch_dataset(monkeypatch, _ok_dataset(record_type="raster_dataset"))

        def must_not_upload(*a, **k):  # pragma: no cover - guard
            raise AssertionError("--layer on a raster must fail before uploading")

        monkeypatch.setattr("geolens_cli.replace.upload_file", must_not_upload)

        result = runner.invoke(
            app,
            [
                "replace",
                str(DATASET_ID),
                str(sample_geojson),
                "--layer",
                "roads",
                "--yes",
            ],
        )

        assert result.exit_code == EXIT_USAGE, result.output
        assert "--layer" in result.output
