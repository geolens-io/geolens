"""OCCLI-05: export stac unit tests with mocked SDK.

Plan 05 Task 1 covers the export_stac.py module surface (record-type
pre-flight, raster classifier, STAC fetch unwrap, JSON renderer, atomic
file write). Plan 05 Task 2 covers the export stac CLI command body
wired into main.py.

Hand-maintained — NOT regenerated.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Sample STAC payload used by all CLI + file-write tests.
# ---------------------------------------------------------------------------

SAMPLE_STAC: dict = {
    "type": "Feature",
    "stac_version": "1.1.0",
    "id": "ds-1",
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
    },
    "properties": {"datetime": "2026-04-27T00:00:00Z"},
    "assets": {},
    "links": [],
}


# ---------------------------------------------------------------------------
# Task 1 — render_stac_json (D-27 output formatting)
# ---------------------------------------------------------------------------


class TestRenderStacJson:
    def test_pretty_indent_2_sorted_keys(self) -> None:
        from geolens_cli.export_stac import render_stac_json

        out = render_stac_json({"b": 1, "a": 2})
        assert out.startswith("{\n")
        assert out.endswith("\n")
        # Sorted keys: "a" appears before "b"
        assert out.index('"a":') < out.index('"b":')
        # Indent of 2 spaces
        assert '\n  "a"' in out

    def test_compact_single_line(self) -> None:
        from geolens_cli.export_stac import render_stac_json

        out = render_stac_json({"b": 1, "a": 2}, compact=True)
        assert out == '{"a":1,"b":2}'

    def test_pretty_emits_trailing_newline(self) -> None:
        from geolens_cli.export_stac import render_stac_json

        out = render_stac_json({"a": 1})
        assert out.endswith("\n")

    def test_compact_no_trailing_newline(self) -> None:
        from geolens_cli.export_stac import render_stac_json

        out = render_stac_json({"a": 1}, compact=True)
        assert not out.endswith("\n")


# ---------------------------------------------------------------------------
# Task 1 — is_raster classifier (D-26 vector guard)
# ---------------------------------------------------------------------------


class TestIsRaster:
    @pytest.mark.parametrize(
        "rt,expected",
        [
            ("raster_dataset", True),
            ("RasterDataset", True),
            ("raster", True),
            ("vector_dataset", False),
            ("collection", False),
            ("", False),
            ("unknown", False),
        ],
    )
    def test_classification(self, rt: str, expected: bool) -> None:
        from geolens_cli.export_stac import is_raster

        assert is_raster(rt) is expected


# ---------------------------------------------------------------------------
# Task 1 — vector_rejection_message (D-26 user-facing message)
# ---------------------------------------------------------------------------


class TestVectorRejectionMessage:
    def test_includes_record_type(self) -> None:
        from geolens_cli.export_stac import vector_rejection_message

        msg = vector_rejection_message("vector_dataset")
        assert "raster" in msg.lower()
        assert "vector_dataset" in msg


# ---------------------------------------------------------------------------
# Task 1 — write_stac_to_file (D-27 atomic write, mode 0o644)
# ---------------------------------------------------------------------------


class TestWriteStacToFile:
    @pytest.mark.skipif(os.name == "nt", reason="POSIX file modes only")
    def test_writes_with_mode_0644(self, tmp_path: Path) -> None:
        from geolens_cli.export_stac import write_stac_to_file

        target = tmp_path / "out.stac.json"
        write_stac_to_file(SAMPLE_STAC, target)
        actual = stat.S_IMODE(target.stat().st_mode)
        assert actual == 0o644, f"got {oct(actual)}"

    def test_pretty_content(self, tmp_path: Path) -> None:
        from geolens_cli.export_stac import write_stac_to_file

        target = tmp_path / "out.stac.json"
        write_stac_to_file(SAMPLE_STAC, target)
        text = target.read_text()
        payload = json.loads(text)
        assert payload["id"] == "ds-1"
        assert text.startswith("{\n")
        assert text.endswith("\n")

    def test_compact_content(self, tmp_path: Path) -> None:
        from geolens_cli.export_stac import write_stac_to_file

        target = tmp_path / "out.stac.json"
        write_stac_to_file(SAMPLE_STAC, target, compact=True)
        text = target.read_text()
        assert "\n" not in text
        json.loads(text)  # must still parse


# ---------------------------------------------------------------------------
# Task 2 — geolens export stac CLI command body
# ---------------------------------------------------------------------------


def _seed_login(instance: str, mock_keyring: dict) -> None:
    """Pre-seed login state so `state.sdk()` returns a valid client."""
    from geolens_cli import config as _config

    mock_keyring[("geolens", instance)] = "tok-abc"
    _config.write_default_instance(instance, username="alice")


class TestExportStacCli:
    def test_raster_pass_through_to_stdout(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.export_stac.fetch_record_type",
            lambda c, did: "raster_dataset",
        )
        monkeypatch.setattr(
            "geolens_cli.export_stac.fetch_stac_item",
            lambda c, did: SAMPLE_STAC,
        )

        result = runner.invoke(app, ["export", "stac", "ds-1"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["id"] == "ds-1"
        assert payload["stac_version"] == "1.1.0"

    def test_vector_rejected_with_exit_2(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.export_stac.fetch_record_type",
            lambda c, did: "vector_dataset",
        )

        result = runner.invoke(app, ["export", "stac", "ds-1"])
        assert result.exit_code == 2, result.output
        # Rejection message goes to stderr; CliRunner mixes stderr into output
        # by default, so checking the merged stream is sufficient.
        combined = result.output
        if hasattr(result, "stderr") and result.stderr:
            combined = combined + result.stderr
        assert "raster" in combined.lower()

    def test_not_found_exits_generic(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.export_stac.fetch_record_type",
            lambda c, did: "not_found",
        )

        result = runner.invoke(app, ["export", "stac", "missing"])
        assert result.exit_code == 1, result.output
        assert "not found" in result.output.lower()

    def test_output_file_atomic_write(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch, tmp_path
    ) -> None:
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.export_stac.fetch_record_type",
            lambda c, did: "raster_dataset",
        )
        monkeypatch.setattr(
            "geolens_cli.export_stac.fetch_stac_item",
            lambda c, did: SAMPLE_STAC,
        )

        target = tmp_path / "ds-1.stac.json"
        result = runner.invoke(app, ["export", "stac", "ds-1", "-o", str(target)])
        assert result.exit_code == 0, result.output
        assert target.is_file()
        payload = json.loads(target.read_text())
        assert payload["id"] == "ds-1"

    def test_compact_flag_emits_single_line(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        instance = "https://x.example.com"
        _seed_login(instance, mock_keyring)
        monkeypatch.setattr(
            "geolens_cli.export_stac.fetch_record_type",
            lambda c, did: "raster_dataset",
        )
        monkeypatch.setattr(
            "geolens_cli.export_stac.fetch_stac_item",
            lambda c, did: SAMPLE_STAC,
        )

        result = runner.invoke(app, ["export", "stac", "ds-1", "--compact"])
        assert result.exit_code == 0, result.output
        # Compact JSON has no internal newlines (CliRunner may add a trailing
        # newline depending on platform; rstrip then assert single line).
        stripped = result.output.rstrip("\n")
        assert "\n" not in stripped
        json.loads(stripped)
