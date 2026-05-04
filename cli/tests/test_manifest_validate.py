"""CLI tests for offline `geolens validate`."""

from __future__ import annotations

import json
from pathlib import Path

from geolens_cli.main import app
from geolens_cli.manifest.template import minimal_manifest_text


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "geolens_cli" / "manifest" / "fixtures"
)


def test_validate_valid_fixture_exits_zero(runner, tmp_xdg_home) -> None:
    manifest = FIXTURE_ROOT / "valid" / "vector-relative.yaml"

    result = runner.invoke(app, ["validate", str(manifest)])

    assert result.exit_code == 0, result.output
    assert str(manifest) in result.output


def test_validate_invalid_fixture_exits_two_with_paths(runner, tmp_xdg_home) -> None:
    manifest = FIXTURE_ROOT / "invalid" / "missing-dataset-key.yaml"

    result = runner.invoke(app, ["validate", str(manifest)])

    assert result.exit_code == 2
    assert str(manifest) in result.output
    assert "$.datasets[0].key" in result.output
    assert "required" in result.output
    assert "Remediation" in result.output


def test_validate_uses_default_manifest_path(
    runner,
    tmp_path: Path,
    tmp_xdg_home,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "geolens.yaml").write_text(minimal_manifest_text(), encoding="utf-8")

    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 0, result.output
    assert "geolens.yaml" in result.output


def test_validate_missing_file_exits_two(
    runner,
    tmp_path: Path,
    tmp_xdg_home,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 2
    assert "geolens.yaml" in result.output
    assert "Could not read manifest" in result.output


def test_validate_malformed_yaml_exits_two(
    runner,
    tmp_path: Path,
    tmp_xdg_home,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "geolens.yaml").write_text("manifest_version: [\n", encoding="utf-8")

    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 2
    assert "geolens.yaml" in result.output
    assert "Invalid YAML" in result.output


def test_validate_non_mapping_yaml_exits_two(
    runner,
    tmp_path: Path,
    tmp_xdg_home,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "geolens.yaml").write_text("[]\n", encoding="utf-8")

    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 2
    assert "geolens.yaml" in result.output
    assert "Manifest root must be a mapping" in result.output


def test_validate_json_output_is_deterministic(runner, tmp_xdg_home) -> None:
    manifest = FIXTURE_ROOT / "invalid" / "missing-dataset-key.yaml"

    result = runner.invoke(app, ["--json", "validate", str(manifest)])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["path"] == str(manifest)
    assert payload["errors"] == [
        {
            "code": "required",
            "message": "Missing required field: key",
            "path": "$.datasets[0].key",
            "remediation": "Add the missing required field at this manifest path.",
        }
    ]
