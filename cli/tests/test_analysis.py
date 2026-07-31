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
        reject one the server already supports."""
        from geolens_cli.analysis import build_preview_request

        body = build_preview_request("spatial_join").to_dict()
        assert body["operation"] == "spatial_join"

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
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id", lambda c, j, **kw: "ds-new"
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
        """fix(#685 review): resolve_dataset_id returns None for a FAILED job
        as well as a timeout. Exiting 0 there would tell a script the analysis
        succeeded."""
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id", lambda c, j, **kw: None
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
            ],
        )
        assert result.exit_code == 1, result.output
        assert "failed" in result.output
        assert "job-1" in result.output

    def test_a_still_running_job_is_not_reported_as_failed(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#685 review): a materialize gets 300s of processing server-side
        and queues below uploads, so outliving the poll is not the same as
        failing. Still exit non-zero (no dataset), but do not call it failed."""
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id", lambda c, j, **kw: None
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
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id", lambda c, j, **kw: None
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
        """fix(#685 review): a 401/404/5xx on GET /jobs/{id} also yields None
        from the poll. Claiming the job outlived the wait asserts something
        that was never established."""
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id", lambda c, j, **kw: None
        )
        monkeypatch.setattr(
            "geolens_cli.analysis.job_snapshot", lambda c, j: (None, None)
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
        assert "outcome is unknown" in result.output

    def test_the_default_wait_has_no_deadline(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """The queue #703 imposes is unbounded, and the server refuses to fail
        a job that is merely waiting in it, so any fixed deadline here would
        report a job the server is still going to finish as producing
        nothing."""
        from geolens_cli.main import app

        seen: dict = {}

        def _capture(client, job_id, **kwargs):
            seen.update(kwargs)
            return "ds-new"

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
        from geolens_cli.main import app

        seen: dict = {}

        def _capture(client, job_id, **kwargs):
            seen.update(kwargs)
            return "ds-new"

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
            "geolens_cli.publish.resolve_dataset_id", lambda c, j, **kw: "ds-new"
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
        from geolens_cli.main import app

        _seed_login("https://x.example.com/api", mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.analysis.run_materialize", lambda c, d, r: _FakeJob()
        )
        monkeypatch.setattr(
            "geolens_cli.publish.resolve_dataset_id", lambda c, j, **kw: "ds-new"
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
