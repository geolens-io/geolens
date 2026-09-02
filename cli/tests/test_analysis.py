"""feat(#685): `geolens analysis preview` / `materialize` with a mocked SDK.

Hand-maintained — NOT regenerated. Covers the request builders (which params
are sent and which stay UNSET), the preview renderer and its truncation
notice, and both command bodies wired into main.py.
"""
from __future__ import annotations

import json

import pytest


SAMPLE_GEOJSON: dict = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {"gid": 1},
        }
    ],
}


class _FakeGeoJson:
    """Stands in for the generated attrs model, which exposes to_dict()."""

    def to_dict(self) -> dict:
        return SAMPLE_GEOJSON


class _FakePreview:
    def __init__(self, *, truncated=False, feature_count=1, source_feature_count=None):
        self.geojson = _FakeGeoJson()
        self.truncated = truncated
        self.feature_count = feature_count
        self.source_feature_count = source_feature_count


class _FakeJob:
    def __init__(self, job_id="job-1"):
        self.job_id = job_id
        self.status = "pending"


def _seed_login(instance: str, mock_keyring: dict) -> None:
    from geolens_cli import config as _config

    mock_keyring[("geolens", instance)] = "tok-abc"
    _config.write_default_instance(instance, username="alice")


# ---------------------------------------------------------------------------
# Request builders
# ---------------------------------------------------------------------------


class TestRequestBuilders:
    def test_buffer_preview_sends_only_the_distance(self) -> None:
        from geolens_cli.analysis import build_preview_request

        body = build_preview_request("buffer", distance_meters=500).to_dict()
        assert body == {"operation": "buffer", "distance_meters": 500}

    def test_clip_preview_sends_the_mask_dataset_as_a_uuid(self) -> None:
        from geolens_cli.analysis import build_preview_request

        mask = "6d4c1b1e-2f3a-4d5b-8c7e-9a0b1c2d3e4f"
        body = build_preview_request("clip", mask_dataset_id=mask).to_dict()
        assert body == {"operation": "clip", "mask_dataset_id": mask}

    def test_centroid_preview_sends_nothing_but_the_operation(self) -> None:
        from geolens_cli.analysis import build_preview_request

        assert build_preview_request("centroid").to_dict() == {"operation": "centroid"}

    def test_dissolve_materialize_sends_the_group_column(self) -> None:
        from geolens_cli.analysis import build_materialize_request

        body = build_materialize_request(
            "dissolve", "Counties", by_field="state"
        ).to_dict()
        assert body == {
            "operation": "dissolve",
            "title": "Counties",
            "by_field": "state",
        }

    def test_an_unknown_operation_is_passed_through_untouched(self) -> None:
        """The SDK's generated enum is the authority (#685). A CLI-side list
        would have to be updated for every new backend operation, and would
        reject one the server already supports.

        The operation named here is deliberately one no enum has: it used to
        be spatial_join, which the server has since gained, so the test stopped
        exercising the pass-through it is named for (#1105)."""
        from geolens_cli.analysis import build_preview_request

        body = build_preview_request("voronoi").to_dict()
        assert body["operation"] == "voronoi"

    def test_spatial_join_preview_sends_the_join_layer_and_its_columns(self) -> None:
        from geolens_cli.analysis import build_preview_request

        join = "0f0f0f0f-1111-4222-8333-444444444444"
        body = build_preview_request(
            "spatial_join", join_dataset_id=join, join_fields="name, pop_2020"
        ).to_dict()
        assert body == {
            "operation": "spatial_join",
            "join_dataset_id": join,
            "join_fields": ["name", "pop_2020"],
        }

    def test_spatial_join_materialize_sends_the_join_layer(self) -> None:
        from geolens_cli.analysis import build_materialize_request

        join = "0f0f0f0f-1111-4222-8333-444444444444"
        body = build_materialize_request(
            "spatial_join", "Parcels with tracts", join_dataset_id=join
        ).to_dict()
        assert body == {
            "operation": "spatial_join",
            "title": "Parcels with tracts",
            "join_dataset_id": join,
        }

    def test_the_join_layer_is_omitted_for_every_other_operation(self) -> None:
        """Unset beats null — see build_preview_request."""
        from geolens_cli.analysis import build_preview_request

        body = build_preview_request("centroid").to_dict()
        assert "join_dataset_id" not in body
        assert "join_fields" not in body

    def test_a_spatial_join_without_a_join_dataset_is_rejected(self) -> None:
        """fix(#1105): the server answers this 422, which unwrap reports as a
        generic failure naming a JSON field the user never typed."""
        from geolens_cli.analysis import (
            build_materialize_request,
            build_preview_request,
        )

        with pytest.raises(ValueError, match="--join-dataset-id"):
            build_preview_request("spatial_join")
        with pytest.raises(ValueError, match="--join-dataset-id"):
            build_materialize_request("spatial_join", "Joined")

    def test_a_malformed_join_dataset_id_names_its_own_flag(self) -> None:
        from geolens_cli.analysis import build_preview_request

        with pytest.raises(ValueError, match=r"--join-dataset-id is not a valid id"):
            build_preview_request("spatial_join", join_dataset_id="not-a-uuid")

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("name", ["name"]),
            (" name , pop ", ["name", "pop"]),
            ("name,,pop", ["name", "pop"]),
        ],
    )
    def test_join_fields_split_on_commas(self, raw: str, expected: list) -> None:
        from geolens_cli.analysis import parse_join_fields

        assert parse_join_fields(raw) == expected

    def test_join_fields_with_no_column_names_is_rejected(self) -> None:
        from geolens_cli.analysis import parse_join_fields

        with pytest.raises(ValueError, match="at least one column"):
            parse_join_fields(" , ")


# ---------------------------------------------------------------------------
# Operation help text
# ---------------------------------------------------------------------------


class TestOperationHelp:
    """fix(#1105): `--operation` help named three operations while the server
    took eight, so spatial_join and measure were invisible from the CLI.

    The list stays a literal rather than being derived from the generated enum,
    because Typer resolves help at import time and reading the enum there would
    make every `geolens --help` pay for an eager SDK import. These tests are
    what keeps the literal honest instead: adding a backend operation fails
    here until the help names it.
    """

    def _operation_help(self, command_name: str) -> str:
        from typer.main import get_command

        from geolens_cli.main import app

        analysis = get_command(app).commands["analysis"]
        command = analysis.commands[command_name]
        param = next(p for p in command.params if p.name == "operation")
        return param.help or ""

    def test_preview_help_names_every_operation_the_sdk_accepts(self) -> None:
        from geolens.models.analysis_preview_request_operation import (
            ANALYSIS_PREVIEW_REQUEST_OPERATION_VALUES,
        )

        help_text = self._operation_help("preview")
        missing = [
            op
            for op in sorted(ANALYSIS_PREVIEW_REQUEST_OPERATION_VALUES)
            if op not in help_text
        ]
        assert not missing, f"--operation help omits {missing}: {help_text}"

    def test_materialize_help_names_every_operation_the_sdk_accepts(self) -> None:
        from geolens.models.analysis_materialize_request_operation import (
            ANALYSIS_MATERIALIZE_REQUEST_OPERATION_VALUES,
        )

        help_text = self._operation_help("materialize")
        missing = [
            op
            for op in sorted(ANALYSIS_MATERIALIZE_REQUEST_OPERATION_VALUES)
            if op not in help_text
        ]
        assert not missing, f"--operation help omits {missing}: {help_text}"

    def test_preview_help_does_not_offer_the_materialize_only_operation(self) -> None:
        """dissolve creates a dataset; there is no preview endpoint for it."""
        from geolens.models.analysis_preview_request_operation import (
            ANALYSIS_PREVIEW_REQUEST_OPERATION_VALUES,
        )

        assert "dissolve" not in ANALYSIS_PREVIEW_REQUEST_OPERATION_VALUES
        assert "materialize-only" in self._operation_help("preview")

    def test_a_malformed_mask_dataset_id_is_rejected_before_the_request(self) -> None:
        from geolens_cli.analysis import build_preview_request

        with pytest.raises(ValueError, match="not a valid id"):
            build_preview_request("clip", mask_dataset_id="not-a-uuid")

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_distance_is_rejected_before_serialization(
        self, bad: float
    ) -> None:
        """fix(#685 review): Click parses nan/inf/1e309 into real floats, and
        JSON cannot spell any of them — the failure would otherwise surface
        from inside the SDK's encoder."""
        from geolens_cli.analysis import build_preview_request

        with pytest.raises(ValueError, match="finite"):
            build_preview_request("buffer", distance_meters=bad)


# ---------------------------------------------------------------------------
# Preview rendering
# ---------------------------------------------------------------------------


class TestPreviewRendering:
    def test_geojson_is_unwrapped_from_the_response_envelope(self) -> None:
        from geolens_cli.analysis import preview_geojson

        assert preview_geojson(_FakePreview()) == SAMPLE_GEOJSON

    def test_an_empty_response_still_renders_a_feature_collection(self) -> None:
        from geolens_cli.analysis import preview_geojson

        empty = _FakePreview()
        empty.geojson = None
        assert preview_geojson(empty) == {"type": "FeatureCollection", "features": []}

    def test_no_warning_for_a_complete_preview(self) -> None:
        from geolens_cli.analysis import truncation_warning

        assert truncation_warning(_FakePreview()) is None

    def test_a_capped_preview_names_both_numbers(self) -> None:
        from geolens_cli.analysis import truncation_warning

        message = truncation_warning(
            _FakePreview(truncated=True, feature_count=500, source_feature_count=22324)
        )
        assert "500 of 22324" in message

    def test_a_capped_preview_without_a_total_still_warns(self) -> None:
        from geolens_cli.analysis import truncation_warning

        message = truncation_warning(_FakePreview(truncated=True, feature_count=500))
        assert "500" in message


# ---------------------------------------------------------------------------
# CLI command bodies
# ---------------------------------------------------------------------------


class TestAnalysisPreviewCli:
    def test_geojson_goes_to_stdout(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_preview", lambda c, d, r: _FakePreview()
        )

        result = runner.invoke(
            app,
            ["analysis", "preview", "ds-1", "--operation", "buffer", "--distance", "500"],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["type"] == "FeatureCollection"

    def test_stdout_stays_parseable_when_the_preview_is_capped(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """The cap notice is stderr-only: a caller redirecting stdout into a
        .geojson file must not get a sentence in the middle of it."""
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_preview",
            lambda c, d, r: _FakePreview(
                truncated=True, feature_count=500, source_feature_count=22324
            ),
        )

        result = runner.invoke(
            app,
            ["--quiet", "analysis", "preview", "ds-1", "--operation", "centroid"],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["type"] == "FeatureCollection"

    def test_a_malformed_mask_dataset_exits_2(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)

        result = runner.invoke(
            app,
            [
                "analysis",
                "preview",
                "ds-1",
                "--operation",
                "clip",
                "--mask-dataset",
                "nope",
            ],
        )
        assert result.exit_code == 2, result.output

    def test_a_spatial_join_without_a_join_dataset_exits_2_naming_the_flag(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#1105): the flag exists now, so the miss is a usage error the
        CLI can name rather than a 422 that exits 1."""
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)

        def _must_not_post(*args, **kwargs):  # pragma: no cover - failure path
            raise AssertionError("the request must not reach the server")

        monkeypatch.setattr("geolens_cli.analysis.run_preview", _must_not_post)

        result = runner.invoke(
            app,
            ["analysis", "preview", "ds-1", "--operation", "spatial_join"],
        )
        assert result.exit_code == 2, result.output
        assert "--join-dataset-id" in result.output

    def test_a_spatial_join_sends_the_join_layer_and_its_columns(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login("https://x.example.com", mock_keyring)
        sent: dict = {}

        def _capture(client, dataset_id, request):
            sent.update(request.to_dict())
            return _FakePreview()

        monkeypatch.setattr("geolens_cli.analysis.run_preview", _capture)

        join = "0f0f0f0f-1111-4222-8333-444444444444"
        result = runner.invoke(
            app,
            [
                "analysis",
                "preview",
                "ds-1",
                "--operation",
                "spatial_join",
                "--join-dataset-id",
                join,
                "--join-fields",
                "name,pop_2020",
            ],
        )
        assert result.exit_code == 0, result.output
        assert sent == {
            "operation": "spatial_join",
            "join_dataset_id": join,
            "join_fields": ["name", "pop_2020"],
        }

    def test_no_instance_exits_with_the_auth_code(
        self, runner, tmp_xdg_home, mock_keyring
    ) -> None:
        """fix(#685 review): materialize maps this to EXIT_AUTH; preview let
        state.sdk() raise BadParameter and exited 2 for the same condition."""
        from geolens_cli.main import app

        result = runner.invoke(
            app, ["analysis", "preview", "ds-1", "--operation", "centroid"]
        )
        assert result.exit_code == 3, result.output


class TestAnalysisMaterializeCli:
    def test_wait_resolves_the_dataset_url(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(dataset_id="ds-new"),
        )

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "buffer",
                "--distance",
                "500",
                "--title",
                "Buffered lakes",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "/datasets/ds-new" in result.output

    def test_a_spatial_join_reaches_the_materialize_endpoint(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#1105): spatial_join was undrivable from the CLI — there was no
        flag to carry the join layer."""
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        sent: dict = {}

        def _capture(client, dataset_id, request):
            sent.update(request.to_dict())
            return _FakeJob()

        monkeypatch.setattr("geolens_cli.analysis.run_materialize", _capture)
        from geolens_cli import publish as _publish

        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(dataset_id="ds-new"),
        )

        join = "0f0f0f0f-1111-4222-8333-444444444444"
        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "spatial_join",
                "--title",
                "Parcels with tracts",
                "--join-dataset-id",
                join,
                "--join-fields",
                "name",
            ],
        )
        assert result.exit_code == 0, result.output
        assert sent == {
            "operation": "spatial_join",
            "title": "Parcels with tracts",
            "join_dataset_id": join,
            "join_fields": ["name"],
        }

    def test_a_spatial_join_without_a_join_dataset_exits_2(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)

        def _must_not_post(*args, **kwargs):  # pragma: no cover - failure path
            raise AssertionError("the request must not reach the server")

        monkeypatch.setattr("geolens_cli.analysis.run_materialize", _must_not_post)

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "spatial_join",
                "--title",
                "Joined",
            ],
        )
        assert result.exit_code == 2, result.output
        assert "--join-dataset-id" in result.output

    def test_no_wait_reports_the_job_id_without_polling(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )

        def _must_not_poll(*args, **kwargs):  # pragma: no cover - failure path
            raise AssertionError("--no-wait must not poll the job endpoint")

        monkeypatch.setattr("geolens_cli.publish.resolve_dataset_id", _must_not_poll)

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
                "--no-wait",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "job-1" in result.output

    def test_a_failed_job_exits_non_zero_and_says_so(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#685 review): resolve_dataset_id reports a terminal status for
        a FAILED job as well as a timeout — see PollOutcome
        (fix(#1778, codex round 3)). Exiting 0 there would tell a script the
        analysis succeeded."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(
                status="failed", stopped_because="terminal"
            ),
        )

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
            ],
        )
        assert result.exit_code == 1, result.output
        assert "failed" in result.output
        assert "job-1" in result.output

    def test_a_cancelled_job_exits_non_zero_and_says_so(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#1778): resolve_dataset_id now treats cancelled as terminal
        (it previously polled a cancelled job forever under POLL_FOREVER),
        so this status is reachable here. It must not fall into the
        "still {status}" wording, which would claim the job might still
        finish."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(
                status="cancelled", stopped_because="terminal"
            ),
        )

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
            ],
        )
        assert result.exit_code == 1, result.output
        assert "cancelled" in result.output
        assert "has not finished" not in result.output

    def test_a_still_running_job_is_not_reported_as_failed(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#685 review): a materialize gets 300s of processing server-side
        and queues below uploads, so outliving the poll is not the same as
        failing. Still exit non-zero (no dataset), but do not call it failed."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
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

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
                "--timeout",
                "30",
            ],
        )
        assert result.exit_code == 1, result.output
        assert "still running" in result.output
        assert "has not finished" in result.output
        assert "failed" not in result.output

    def test_a_job_that_finishes_during_the_final_read_is_a_success(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#685 review): the job can finish between the poll's last look
        and the status re-read, and that response carries the dataset id.
        Reporting it as unfinished would be the worst of the three answers."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(
                status="running", stopped_because="timeout"
            ),
        )
        monkeypatch.setattr(
            "geolens_cli.analysis.job_snapshot",
            lambda c, j: ("complete", "ds-late"),
        )

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
                "--timeout",
                "30",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "/datasets/ds-late" in result.output

    def test_an_unreadable_status_is_not_reported_as_a_timeout(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#1778, codex round 3): resolve_dataset_id's own poll failure
        (a transient 500 here, mapped to stopped_because="poll_failed") must
        not be reported as a timeout, even when a LATER, separate
        job_snapshot() read happens to succeed and report "pending" — that
        second read's status is discarded and used only to check for a
        dataset_id (the fix(#685 review) case, preserved below). Claiming
        the job outlived the wait, or was "still pending", asserts something
        that was never established — the read failed, it did not run out."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(
                stopped_because="poll_failed", detail="HTTP 500"
            ),
        )
        monkeypatch.setattr(
            "geolens_cli.analysis.job_snapshot", lambda c, j: ("pending", None)
        )

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
            ],
        )
        assert result.exit_code == 1, result.output
        assert "could not be read" in result.output
        assert "HTTP 500" in result.output
        assert "still pending" not in result.output
        assert "has not finished" not in result.output

    def test_a_token_expired_mid_poll_exits_auth(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#1778, codex round 3): resolve_dataset_id detects a 401/403
        itself (stopped_because == "token_expired"). No follow-up read is
        attempted — retrying the same dead token is pointless — and the
        command exits EXIT_AUTH directly, naming what went wrong."""
        from geolens_cli import publish as _publish
        from geolens_cli._sdk_helpers import EXIT_AUTH
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(stopped_because="token_expired"),
        )

        def _must_not_read(*args, **kwargs):  # pragma: no cover - failure path
            raise AssertionError("token_expired must not trigger a follow-up read")

        monkeypatch.setattr("geolens_cli.analysis.job_snapshot", _must_not_read)

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
            ],
        )
        assert result.exit_code == EXIT_AUTH, result.output
        assert "Authentication failed" in result.output

    def test_a_fanned_out_job_exits_zero_and_does_not_claim_a_timeout(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """A fanned-out job is a SUCCESS whose children each carry their own
        dataset — see publish()'s equivalent branch (fix(#1778)). materialize
        jobs are never fanned out by the current backend (fan-out is
        ingest-only), so this is defensive coverage, not a reachable
        production path today."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(
                status="fanned_out", stopped_because="terminal"
            ),
        )

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "fanned out" in result.output
        assert "has not finished" not in result.output

    def test_timeout_then_failed_snapshot_reports_the_failure(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#1778, codex round 4): the poll timed out, but the follow-up
        read shows the job has SINCE become failed — that definitive
        answer must win over the stale "still running" wording, which the
        previous implementation used to report."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
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

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
                "--timeout",
                "30",
            ],
        )
        assert result.exit_code == 1, result.output
        assert "failed" in result.output
        assert "job record" in result.output
        assert "still running" not in result.output
        assert "has not finished" not in result.output

    def test_poll_failed_then_cancelled_snapshot_reports_cancellation(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#1778, codex round 4): the poll itself failed (a transient
        500), but the follow-up read shows the job has SINCE been
        cancelled — that definitive answer must win over the "status
        could not be read" wording."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
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

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
            ],
        )
        assert result.exit_code == 1, result.output
        assert "cancelled" in result.output
        assert "could not be read" not in result.output

    def test_timeout_then_running_snapshot_still_reports_the_timeout(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#1778, codex round 4): only a DEFINITIVE terminal snapshot
        (failed/cancelled/fanned_out) overrides the original outcome — a
        pending/running snapshot leaves the job's fate genuinely
        unresolved, so the original timeout wording stands."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
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

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
                "--timeout",
                "30",
            ],
        )
        assert result.exit_code == 1, result.output
        assert "still running" in result.output
        assert "has not finished" in result.output

    def test_the_default_wait_has_no_deadline(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """The queue #703 imposes is unbounded, and the server refuses to fail
        a job that is merely waiting in it, so any fixed deadline here would
        report a job the server is still going to finish as producing
        nothing."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        seen: dict = {}

        def _capture(client, job_id, **kwargs):
            seen.update(kwargs)
            return _publish.PollOutcome(dataset_id="ds-new")

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr("geolens_cli.publish.resolve_dataset_id", _capture)

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
            ],
        )
        assert result.exit_code == 0, result.output
        assert seen["timeout"] == float("inf")

    def test_an_explicit_timeout_bounds_the_wait(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        seen: dict = {}

        def _capture(client, job_id, **kwargs):
            seen.update(kwargs)
            return _publish.PollOutcome(dataset_id="ds-new")

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr("geolens_cli.publish.resolve_dataset_id", _capture)

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
                "--timeout",
                "30",
            ],
        )
        assert result.exit_code == 0, result.output
        assert seen["timeout"] == 30.0

    def test_an_explicit_timeout_also_bounds_each_request(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#685 review): the poll deadline is only checked between
        iterations, and the SDK builds its httpx client with no request
        timeout at all, so a stalled response would outlive --timeout."""
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        bounded: dict = {}

        class _Bounded:
            def with_timeout(self, value):  # pragma: no cover - trivial
                bounded["value"] = value
                return self

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.main.AppState.sdk",
            lambda self: type("S", (), {"client": _Bounded()})(),
        )
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(dataset_id="ds-new"),
        )

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
                "--timeout",
                "30",
            ],
        )
        assert result.exit_code == 0, result.output
        assert bounded["value"] == 30.0

    def test_a_non_finite_timeout_is_a_usage_error(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#685 review): --timeout inf parses fine and would turn an
        explicitly bounded wait into an unbounded one."""
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)

        def _must_not_poll(*args, **kwargs):  # pragma: no cover - failure path
            raise AssertionError("--timeout inf must not start an unbounded poll")

        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr("geolens_cli.publish.resolve_dataset_id", _must_not_poll)

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
                "--timeout",
                "inf",
            ],
        )
        assert result.exit_code == 2, result.output
        assert "finite" in result.output

    def test_a_zero_timeout_is_a_usage_error_not_an_endless_wait(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#685 review): `timeout or POLL_FOREVER` read an explicit 0 as
        "no bound", which is the opposite of what it asks for."""
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)

        def _must_not_poll(*args, **kwargs):  # pragma: no cover - failure path
            raise AssertionError("--timeout 0 must not start an unbounded poll")

        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr("geolens_cli.publish.resolve_dataset_id", _must_not_poll)

        result = runner.invoke(
            app,
            [
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "centroid",
                "--title",
                "Centroids",
                "--timeout",
                "0",
            ],
        )
        assert result.exit_code == 2, result.output
        assert "--no-wait" in result.output

    def test_json_mode_emits_the_job_and_dataset_ids(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import publish as _publish
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id",
            lambda c, j, **kw: _publish.PollOutcome(dataset_id="ds-new"),
        )

        result = runner.invoke(
            app,
            [
                "--json",
                "analysis",
                "materialize",
                "ds-1",
                "--operation",
                "buffer",
                "--distance",
                "500",
                "--title",
                "Buffered lakes",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["job_id"] == "job-1"
        assert payload["dataset_id"] == "ds-new"
        assert payload["stopped_because"] is None
