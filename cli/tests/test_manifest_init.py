"""CLI tests for `geolens init` manifest scaffolding."""

from __future__ import annotations

from pathlib import Path

from geolens_cli.main import app
from geolens_cli.manifest import load_manifest, validate_manifest


def test_init_creates_default_manifest(
    runner,
    tmp_path: Path,
    tmp_xdg_home,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init"])

    manifest = tmp_path / "geolens.yaml"
    assert result.exit_code == 0, result.output
    assert manifest.is_file()
    assert validate_manifest(load_manifest(manifest)) == []
    assert "geolens.yaml" in result.output


def test_init_creates_explicit_manifest_path(
    runner,
    tmp_path: Path,
    tmp_xdg_home,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["init", "configs/catalog.yaml"])

    manifest = tmp_path / "configs" / "catalog.yaml"
    assert result.exit_code == 0, result.output
    assert manifest.is_file()
    assert validate_manifest(load_manifest(manifest)) == []


def test_init_refuses_to_overwrite_existing_manifest(
    runner,
    tmp_path: Path,
    tmp_xdg_home,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = tmp_path / "geolens.yaml"
    manifest.write_text("existing: true\n", encoding="utf-8")

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 2
    assert manifest.read_text(encoding="utf-8") == "existing: true\n"
    assert "geolens.yaml" in result.output
    assert "already exists" in result.output


def test_init_force_overwrites_existing_manifest(
    runner,
    tmp_path: Path,
    tmp_xdg_home,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = tmp_path / "geolens.yaml"
    manifest.write_text("existing: true\n", encoding="utf-8")

    result = runner.invoke(app, ["init", "--force"])

    assert result.exit_code == 0, result.output
    assert "existing: true" not in manifest.read_text(encoding="utf-8")
    assert validate_manifest(load_manifest(manifest)) == []
